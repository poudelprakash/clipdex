"""Search: Postgres FTS → 30-60s clip context → LLM rerank, with 7-day cache.

Pipeline per query:

1. ``websearch_to_tsquery`` against ``transcript_segments_search`` for the top
   50 segments ordered by ``ts_rank``.
2. For each FTS hit, expand into a 30–60 second *clip*: pull the surrounding
   segments inside ``CLIP_WINDOW_MS`` of the hit, capped at ``CLIP_MAX_MS``,
   and snap the boundaries to sentence-ish punctuation where possible.
3. Send the (query, clip-texts) pair to the cheap LLM for a rerank. The model
   returns a JSON list of clip ids, best-first.
4. Cache the result keyed on ``(sha1(query), sha1(top-50-ids))``. Re-runs in
   the next 7 days are instant.

Top-N is configurable per request (default 10).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clipdex_api.db import session
from llm_client import complete

log = logging.getLogger("clipdex.search")

FTS_TOP_N = 50
CLIP_WINDOW_MS = 30_000  # ±30s on each side of the hit
CLIP_MAX_MS = 60_000  # never exceed 60s of total clip
CACHE_TTL = timedelta(days=7)

router = APIRouter()


class ClipHit(BaseModel):
    video_id: str
    seq: int  # segment_id of the FTS hit (anchor segment)
    start_ms: int
    end_ms: int
    text: str  # joined clip text (anchor + neighbors, sentence-snapped)
    youtube_url: str  # https://youtu.be/<id>?t=<seconds>
    fts_rank: float
    rerank_rationale: str | None = None


class SearchResponse(BaseModel):
    query: str
    cached: bool
    results: list[ClipHit]


# --- Routes ----------------------------------------------------------------


@router.get("/api/search", response_model=SearchResponse)
async def search_endpoint(
    q: str = Query(..., min_length=1, max_length=500),
    n: int = Query(10, ge=1, le=25),
    use_llm: bool = Query(True),
) -> SearchResponse:
    if not q.strip():
        raise HTTPException(status_code=400, detail="query is empty")
    async with session() as s:
        return await run_search(s, q=q, top_n=n, use_llm=use_llm)


@router.post("/api/search/refresh")
async def refresh_endpoint() -> dict[str, str]:
    async with session() as s:
        await refresh_search(s)
    return {"status": "ok"}


# --- Implementation --------------------------------------------------------


async def refresh_search(s: AsyncSession) -> None:
    """REFRESH MATERIALIZED VIEW transcript_segments_search (concurrent if
    possible — falls back to plain refresh on a cold view)."""
    try:
        await s.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY transcript_segments_search")
        )
    except Exception:
        await s.rollback()
        await s.execute(text("REFRESH MATERIALIZED VIEW transcript_segments_search"))
    await s.commit()


async def run_search(
    s: AsyncSession, *, q: str, top_n: int = 10, use_llm: bool = True
) -> SearchResponse:
    fts_rows = await _fts_top(s, q=q, limit=FTS_TOP_N)
    if not fts_rows:
        return SearchResponse(query=q, cached=False, results=[])

    top_ids_hash = _hash_ids([(r["video_id"], r["seq"]) for r in fts_rows])
    q_hash = _hash_text(q)

    cached_ids = await _read_cache(s, q_hash, top_ids_hash) if use_llm else None
    if cached_ids is not None:
        ordered = _reorder_by_ids(fts_rows, cached_ids)
        clips = [await _build_clip(s, row, rationale=None) for row in ordered[:top_n]]
        return SearchResponse(query=q, cached=True, results=clips)

    if use_llm:
        reranked = await _llm_rerank(q=q, hits=fts_rows, top_n=top_n)
        # Persist the rerank decision.
        await _write_cache(
            s,
            q=q,
            q_hash=q_hash,
            top_ids_hash=top_ids_hash,
            reranked=reranked,
        )
        rationale_by_key = {
            (r["video_id"], r["seq"]): r.get("rationale") for r in reranked
        }
        keyed = {(r["video_id"], r["seq"]): r for r in fts_rows}
        clips: list[ClipHit] = []
        for item in reranked[:top_n]:
            row = keyed.get((item["video_id"], item["seq"]))
            if row is None:
                continue
            clips.append(
                await _build_clip(
                    s, row, rationale=rationale_by_key.get((item["video_id"], item["seq"]))
                )
            )
        return SearchResponse(query=q, cached=False, results=clips)

    # No LLM, no cache — just FTS order.
    clips = [await _build_clip(s, row, rationale=None) for row in fts_rows[:top_n]]
    return SearchResponse(query=q, cached=False, results=clips)


# --- FTS layer -------------------------------------------------------------


async def _fts_top(s: AsyncSession, *, q: str, limit: int) -> list[dict]:
    r = await s.execute(
        text(
            """
            SELECT video_id, seq, start_ms, end_ms, text,
                   ts_rank(ts_doc, websearch_to_tsquery('english', :q)) AS rank
            FROM transcript_segments_search
            WHERE ts_doc @@ websearch_to_tsquery('english', :q)
            ORDER BY rank DESC, start_ms ASC
            LIMIT :n
            """
        ),
        {"q": q, "n": limit},
    )
    return [dict(row._mapping) for row in r]


# --- Clip extraction -------------------------------------------------------

_SENTENCE_BOUNDARY = re.compile(r"[.!?]\s+|[.!?]$")


async def _build_clip(
    s: AsyncSession, anchor: dict, *, rationale: str | None
) -> ClipHit:
    """Expand anchor into a 30–60s clip and return the assembled hit."""
    video_id = anchor["video_id"]
    anchor_start = int(anchor["start_ms"])
    anchor_end = int(anchor["end_ms"])

    lo = max(0, anchor_start - CLIP_WINDOW_MS)
    hi = anchor_end + CLIP_WINDOW_MS

    r = await s.execute(
        text(
            """
            SELECT seq, start_ms, end_ms, text
            FROM transcript_segments
            WHERE video_id = :v AND start_ms BETWEEN :lo AND :hi
            ORDER BY start_ms
            """
        ),
        {"v": video_id, "lo": lo, "hi": hi},
    )
    rows = list(r)
    if not rows:
        text_join = anchor["text"]
        start_ms, end_ms = anchor_start, anchor_end
    else:
        # Trim to <= CLIP_MAX_MS keeping the anchor inside.
        pruned = _prune_to_max(rows, anchor_start, anchor_end, CLIP_MAX_MS)
        start_ms = int(pruned[0].start_ms)
        end_ms = int(pruned[-1].end_ms)
        text_join = _snap_to_sentence(" ".join(row.text.strip() for row in pruned))

    yt_url = f"https://youtu.be/{video_id}?t={start_ms // 1000}"
    return ClipHit(
        video_id=video_id,
        seq=int(anchor["seq"]),
        start_ms=start_ms,
        end_ms=end_ms,
        text=text_join.strip(),
        youtube_url=yt_url,
        fts_rank=float(anchor["rank"]),
        rerank_rationale=rationale,
    )


def _prune_to_max(rows: list, anchor_start: int, anchor_end: int, max_ms: int) -> list:
    """Drop the outer rows until total span <= max_ms, keeping anchor in range."""
    pruned = list(rows)
    while pruned and (int(pruned[-1].end_ms) - int(pruned[0].start_ms)) > max_ms:
        # Decide which side to trim: trim the side farthest from the anchor.
        dist_left = anchor_start - int(pruned[0].start_ms)
        dist_right = int(pruned[-1].end_ms) - anchor_end
        if dist_left >= dist_right and len(pruned) > 1:
            pruned.pop(0)
        elif len(pruned) > 1:
            pruned.pop()
        else:
            break
    return pruned


def _snap_to_sentence(text_in: str) -> str:
    """If the clip starts mid-sentence, drop the leading partial.
    Same for trailing partials."""
    s = text_in.strip()
    if not s:
        return s
    # Trim leading lowercase partial if there's a sentence start further in.
    if s and s[0].islower():
        m = _SENTENCE_BOUNDARY.search(s)
        if m and m.end() < len(s) - 20:
            s = s[m.end() :].strip()
    # Trim incomplete trailing sentence: cut to last terminal punctuation.
    matches = list(_SENTENCE_BOUNDARY.finditer(s))
    if matches and matches[-1].end() < len(s) - 1:
        s = s[: matches[-1].end()].strip()
    return s


# --- LLM rerank ------------------------------------------------------------

_RERANK_SYSTEM = """\
You re-rank candidate podcast clips for a search query.

You will receive the user's query and a numbered list of up to 50 candidate
clips. Each clip has an id (the (video_id, seq) pair) and a short text
excerpt.

Pick the clips that best answer the query (most informative, most on-topic,
not just keyword-matching). Drop clips that share only an incidental keyword.
Return JSON of the form:

  {"results": [
     {"video_id": "...", "seq": 123, "rationale": "<one short sentence>"},
     ...
  ]}

Order matters; best first. You may return fewer than the requested N if not
enough candidates are good. Never invent ids that aren't in the input.
"""


async def _llm_rerank(*, q: str, hits: list[dict], top_n: int) -> list[dict]:
    """Returns a list of {video_id, seq, rationale}, best-first."""
    lines = [
        f"{i + 1}. id=({h['video_id']}, {h['seq']})  {h['text'][:200]}"
        for i, h in enumerate(hits)
    ]
    user = (
        f"Query: {q}\n\n"
        f"Pick up to {top_n} clips best matching the query.\n\n"
        "Candidates:\n" + "\n".join(lines)
    )
    raw = await complete(
        system=_RERANK_SYSTEM,
        messages=[{"role": "user", "content": user}],
        tier="cheap",
        cache_system=True,
        max_tokens=2048,
    )
    text_out = raw if isinstance(raw, str) else str(raw)
    start = text_out.find("{")
    end = text_out.rfind("}")
    if start == -1 or end == -1:
        log.warning("rerank: unparseable LLM reply; falling back to FTS order")
        return [
            {"video_id": h["video_id"], "seq": h["seq"], "rationale": None}
            for h in hits[:top_n]
        ]
    try:
        obj = json.loads(text_out[start : end + 1])
    except json.JSONDecodeError:
        log.warning("rerank: invalid JSON; falling back to FTS order")
        return [
            {"video_id": h["video_id"], "seq": h["seq"], "rationale": None}
            for h in hits[:top_n]
        ]
    raw_results = obj.get("results") or []
    valid_keys = {(h["video_id"], h["seq"]) for h in hits}
    out: list[dict] = []
    for item in raw_results:
        key = (item.get("video_id"), item.get("seq"))
        if key in valid_keys:
            out.append(
                {
                    "video_id": key[0],
                    "seq": key[1],
                    "rationale": str(item.get("rationale", ""))[:200] or None,
                }
            )
    return out or [
        {"video_id": h["video_id"], "seq": h["seq"], "rationale": None}
        for h in hits[:top_n]
    ]


# --- Cache -----------------------------------------------------------------


async def _read_cache(
    s: AsyncSession, q_hash: str, top_ids_hash: str
) -> list[tuple[str, int]] | None:
    r = await s.execute(
        text(
            """
            SELECT reranked, cached_at
            FROM search_cache
            WHERE query_hash = :q AND top_ids_hash = :t
            """
        ),
        {"q": q_hash, "t": top_ids_hash},
    )
    row = r.first()
    if not row:
        return None
    if datetime.now(timezone.utc) - row.cached_at > CACHE_TTL:
        return None
    items = row.reranked
    return [(item["video_id"], int(item["seq"])) for item in items]


async def _write_cache(
    s: AsyncSession,
    *,
    q: str,
    q_hash: str,
    top_ids_hash: str,
    reranked: list[dict],
) -> None:
    await s.execute(
        text(
            """
            INSERT INTO search_cache (query_hash, top_ids_hash, query_text, reranked)
            VALUES (:q, :t, :qt, CAST(:r AS jsonb))
            ON CONFLICT (query_hash, top_ids_hash) DO UPDATE
              SET reranked = EXCLUDED.reranked,
                  cached_at = now()
            """
        ),
        {
            "q": q_hash,
            "t": top_ids_hash,
            "qt": q,
            "r": json.dumps(reranked),
        },
    )
    await s.commit()


def _hash_text(t: str) -> str:
    return hashlib.sha1(t.strip().lower().encode("utf-8")).hexdigest()


def _hash_ids(ids: list[tuple[str, int]]) -> str:
    payload = "|".join(f"{v}:{seq}" for v, seq in ids)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _reorder_by_ids(
    rows: list[dict], ordered_ids: list[tuple[str, int]]
) -> list[dict]:
    by_key = {(r["video_id"], r["seq"]): r for r in rows}
    out: list[dict] = []
    for key in ordered_ids:
        row = by_key.get(key)
        if row is not None:
            out.append(row)
    return out
