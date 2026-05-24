"""Guest list + detail routes.

These read straight from the canonical ``guests`` / ``guest_aliases`` tables
(post 4) plus the per-video ``topics_raw`` / ``quotes_raw`` tables (post 3).
Popularity scoring lands in post 8; for now `popularity = appearance_count`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clipdex_api.db import session
from clipdex_schema import (
    Appearance,
    GuestDetail,
    GuestQuote,
    GuestSummary,
    TopicMention,
)

router = APIRouter()


@router.get("/api/guests", response_model=list[GuestSummary])
async def list_guests(limit: int = 12) -> list[GuestSummary]:
    async with session() as s:
        return await _list_guests(s, limit=limit)


@router.get("/api/guests/{guest_id}", response_model=GuestDetail)
async def get_guest(guest_id: str) -> GuestDetail:
    async with session() as s:
        detail = await _get_guest(s, guest_id=guest_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="guest not found")
    return detail


# --- DB layer --------------------------------------------------------------


async def _list_guests(s: AsyncSession, *, limit: int) -> list[GuestSummary]:
    """`popularity = 0.7 * normalized_appearance + 0.3 * recency_score`.

    `recency_score` is 1.0 for a guest seen in the most recent video and decays
    to 0 for guests whose latest appearance is the oldest in the corpus. Both
    sides are normalized so the score sits in [0, 1] regardless of channel
    size. Memoize this for an hour in front of the route if the query gets hot
    (it doesn't yet, at our scale).
    """
    r = await s.execute(
        text(
            """
            WITH per_guest AS (
                SELECT g.id, g.canonical_name,
                       COUNT(DISTINCT ga.source_video_id) AS apps,
                       MAX(pv.published_at) AS latest
                FROM guests g
                LEFT JOIN guest_aliases ga ON ga.guest_id = g.id
                LEFT JOIN processed_videos pv ON pv.video_id = ga.source_video_id
                GROUP BY g.id, g.canonical_name
            ),
            extents AS (
                SELECT MAX(apps) AS max_apps,
                       MIN(latest) AS oldest, MAX(latest) AS newest
                FROM per_guest
            )
            SELECT pg.id::text AS id, pg.canonical_name, pg.apps,
                   CASE
                     WHEN extents.max_apps IS NULL OR extents.max_apps = 0 THEN 0
                     ELSE pg.apps::float / extents.max_apps
                   END AS norm_apps,
                   CASE
                     WHEN extents.newest IS NULL OR extents.newest = extents.oldest THEN 0
                     WHEN pg.latest IS NULL THEN 0
                     ELSE EXTRACT(EPOCH FROM (pg.latest - extents.oldest))
                          / GREATEST(1, EXTRACT(EPOCH FROM (extents.newest - extents.oldest)))
                   END AS recency
            FROM per_guest pg
            CROSS JOIN extents
            ORDER BY (0.7 * (
                       CASE
                         WHEN extents.max_apps IS NULL OR extents.max_apps = 0 THEN 0
                         ELSE pg.apps::float / extents.max_apps
                       END
                     ) + 0.3 * (
                       CASE
                         WHEN extents.newest IS NULL OR extents.newest = extents.oldest THEN 0
                         WHEN pg.latest IS NULL THEN 0
                         ELSE EXTRACT(EPOCH FROM (pg.latest - extents.oldest))
                              / GREATEST(1, EXTRACT(EPOCH FROM (extents.newest - extents.oldest)))
                       END
                     )) DESC,
                     pg.canonical_name ASC
            LIMIT :n
            """
        ),
        {"n": limit},
    )
    rows = list(r)
    return [
        GuestSummary(
            id=row.id,
            canonical_name=row.canonical_name,
            appearance_count=int(row.apps),
            popularity=float(
                0.7 * float(row.norm_apps) + 0.3 * float(row.recency)
            ),
        )
        for row in rows
    ]


async def _get_guest(s: AsyncSession, *, guest_id: str) -> GuestDetail | None:
    r = await s.execute(
        text(
            """
            SELECT g.id::text AS id, g.canonical_name
            FROM guests g WHERE g.id = CAST(:gid AS uuid)
            """
        ),
        {"gid": guest_id},
    )
    head = r.first()
    if head is None:
        return None

    appearances = await _appearances(s, guest_id=guest_id)
    topics = await _topics_for_videos(s, [a.video_id for a in appearances])
    quotes = await _quotes_for_videos(s, [a.video_id for a in appearances])

    return GuestDetail(
        id=head.id,
        canonical_name=head.canonical_name,
        appearances=appearances,
        topics=topics,
        quotes=quotes,
    )


async def _appearances(s: AsyncSession, *, guest_id: str) -> list[Appearance]:
    r = await s.execute(
        text(
            """
            SELECT ga.alias_name, ga.source_video_id
            FROM guest_aliases ga
            WHERE ga.guest_id = CAST(:gid AS uuid)
              AND ga.source_video_id IS NOT NULL
            ORDER BY ga.created_at
            """
        ),
        {"gid": guest_id},
    )
    out: list[Appearance] = []
    for row in r:
        vid = row.source_video_id
        out.append(
            Appearance(
                video_id=vid,
                alias_name=row.alias_name,
                youtube_url=f"https://youtu.be/{vid}",
            )
        )
    return out


async def _topics_for_videos(
    s: AsyncSession, video_ids: list[str]
) -> list[TopicMention]:
    if not video_ids:
        return []
    r = await s.execute(
        text(
            """
            SELECT name, COUNT(*) AS n
            FROM topics_raw
            WHERE video_id = ANY(:vids)
            GROUP BY name
            ORDER BY n DESC, name ASC
            LIMIT 20
            """
        ),
        {"vids": video_ids},
    )
    return [TopicMention(name=row.name, count=int(row.n)) for row in r]


async def _quotes_for_videos(
    s: AsyncSession, video_ids: list[str]
) -> list[GuestQuote]:
    if not video_ids:
        return []
    r = await s.execute(
        text(
            """
            SELECT text, video_id, quotability_score
            FROM quotes_raw
            WHERE video_id = ANY(:vids)
            ORDER BY quotability_score DESC, video_id
            LIMIT 10
            """
        ),
        {"vids": video_ids},
    )
    return [
        GuestQuote(
            text=row.text,
            video_id=row.video_id,
            youtube_url=f"https://youtu.be/{row.video_id}",
            quotability_score=float(row.quotability_score),
        )
        for row in r
    ]
