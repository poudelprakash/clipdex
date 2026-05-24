from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clipdex_schema import TranscriptSegment


async def latest_published(session: AsyncSession) -> datetime | None:
    r = await session.execute(text("SELECT MAX(published_at) FROM processed_videos"))
    return r.scalar()


async def already_done(session: AsyncSession, video_id: str) -> bool:
    r = await session.execute(
        text("SELECT status FROM processed_videos WHERE video_id = :v"),
        {"v": video_id},
    )
    row = r.first()
    return row is not None and row.status == "done"


async def save_video(
    session: AsyncSession,
    *,
    video_id: str,
    title: str,
    published_at: datetime,
    segments: list[TranscriptSegment],
    source: str,
) -> None:
    """Replace any prior data for `video_id` and mark it done — all in one transaction."""
    async with session.begin():
        await session.execute(
            text(
                """
                INSERT INTO processed_videos
                  (video_id, title, published_at, status, source, segment_count, ingested_at)
                VALUES
                  (:vid, :title, :pub, 'done', :src, :n, now())
                ON CONFLICT (video_id) DO UPDATE
                SET status = 'done',
                    source = EXCLUDED.source,
                    segment_count = EXCLUDED.segment_count,
                    ingested_at = EXCLUDED.ingested_at,
                    error = NULL
                """
            ),
            {
                "vid": video_id,
                "title": title,
                "pub": published_at,
                "src": source,
                "n": len(segments),
            },
        )
        await session.execute(
            text("DELETE FROM transcript_segments WHERE video_id = :v"),
            {"v": video_id},
        )
        if segments:
            await session.execute(
                text(
                    """
                    INSERT INTO transcript_segments
                      (video_id, seq, start_ms, end_ms, text, source)
                    VALUES
                      (:video_id, :seq, :start_ms, :end_ms, :text, :source)
                    """
                ),
                [s.model_dump() for s in segments],
            )


async def mark_failed(session: AsyncSession, video_id: str, error: str) -> None:
    async with session.begin():
        await session.execute(
            text(
                """
                INSERT INTO processed_videos
                  (video_id, title, published_at, status, error, ingested_at)
                VALUES (:vid, :vid, now(), 'failed', :err, now())
                ON CONFLICT (video_id) DO UPDATE
                SET status = 'failed', error = EXCLUDED.error, ingested_at = now()
                """
            ),
            {"vid": video_id, "err": error[:1000]},
        )
