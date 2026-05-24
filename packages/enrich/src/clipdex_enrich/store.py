from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clipdex_schema import Extraction, TranscriptSegment


async def load_segments(session: AsyncSession, video_id: str) -> list[TranscriptSegment]:
    r = await session.execute(
        text(
            """
            SELECT video_id, seq, start_ms, end_ms, text, source
            FROM transcript_segments
            WHERE video_id = :v
            ORDER BY seq
            """
        ),
        {"v": video_id},
    )
    return [
        TranscriptSegment(
            video_id=row.video_id,
            seq=row.seq,
            start_ms=row.start_ms,
            end_ms=row.end_ms,
            text=row.text,
            source=row.source,
        )
        for row in r
    ]


async def already_enriched(session: AsyncSession, video_id: str) -> bool:
    r = await session.execute(
        text("SELECT status FROM enriched_videos WHERE video_id = :v"),
        {"v": video_id},
    )
    row = r.first()
    return row is not None and row.status == "done"


async def list_done_videos(session: AsyncSession, limit: int = 0) -> list[str]:
    sql = """
        SELECT pv.video_id
        FROM processed_videos pv
        LEFT JOIN enriched_videos ev USING (video_id)
        WHERE pv.status = 'done'
          AND pv.segment_count > 0
          AND ev.video_id IS NULL
        ORDER BY pv.published_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    r = await session.execute(text(sql))
    return [row.video_id for row in r]


async def save_extractions(
    session: AsyncSession,
    *,
    video_id: str,
    per_chunk: list[tuple[int, Extraction]],
) -> dict[str, int]:
    """Replace any prior raw rows for `video_id` and insert fresh ones."""
    counts = {"guests": 0, "topics": 0, "quotes": 0}
    try:
        await session.execute(
            text("DELETE FROM guests_raw WHERE video_id = :v"), {"v": video_id}
        )
        await session.execute(
            text("DELETE FROM topics_raw WHERE video_id = :v"), {"v": video_id}
        )
        await session.execute(
            text("DELETE FROM quotes_raw WHERE video_id = :v"), {"v": video_id}
        )

        guest_rows = []
        topic_rows = []
        quote_rows = []
        for chunk_start_ms, ex in per_chunk:
            for g in ex.guests:
                guest_rows.append(
                    {
                        "vid": video_id,
                        "name": g.name,
                        "role": g.role,
                        "company": g.company,
                        "confidence": g.confidence,
                        "csm": chunk_start_ms,
                    }
                )
            for t in ex.topics:
                topic_rows.append(
                    {
                        "vid": video_id,
                        "name": t.name,
                        "segment_ids": t.segment_ids,
                        "confidence": t.confidence,
                        "csm": chunk_start_ms,
                    }
                )
            for q in ex.quotes:
                quote_rows.append(
                    {
                        "vid": video_id,
                        "text": q.text,
                        "segment_id": q.segment_id,
                        "speaker": q.speaker,
                        "qs": q.quotability_score,
                        "csm": chunk_start_ms,
                    }
                )

        if guest_rows:
            await session.execute(
                text(
                    """
                    INSERT INTO guests_raw
                      (video_id, name, role, company, confidence, chunk_start_ms)
                    VALUES
                      (:vid, :name, :role, :company, :confidence, :csm)
                    """
                ),
                guest_rows,
            )
        if topic_rows:
            await session.execute(
                text(
                    """
                    INSERT INTO topics_raw
                      (video_id, name, segment_ids, confidence, chunk_start_ms)
                    VALUES
                      (:vid, :name, :segment_ids, :confidence, :csm)
                    """
                ),
                topic_rows,
            )
        if quote_rows:
            await session.execute(
                text(
                    """
                    INSERT INTO quotes_raw
                      (video_id, text, segment_id, speaker, quotability_score, chunk_start_ms)
                    VALUES
                      (:vid, :text, :segment_id, :speaker, :qs, :csm)
                    """
                ),
                quote_rows,
            )

        counts["guests"] = len(guest_rows)
        counts["topics"] = len(topic_rows)
        counts["quotes"] = len(quote_rows)

        await session.execute(
            text(
                """
                INSERT INTO enriched_videos
                  (video_id, status, chunk_count, guest_count, topic_count, quote_count, enriched_at)
                VALUES
                  (:vid, 'done', :n, :g, :t, :q, now())
                ON CONFLICT (video_id) DO UPDATE
                SET status = 'done',
                    chunk_count = EXCLUDED.chunk_count,
                    guest_count = EXCLUDED.guest_count,
                    topic_count = EXCLUDED.topic_count,
                    quote_count = EXCLUDED.quote_count,
                    error = NULL,
                    enriched_at = EXCLUDED.enriched_at
                """
            ),
            {
                "vid": video_id,
                "n": len(per_chunk),
                "g": counts["guests"],
                "t": counts["topics"],
                "q": counts["quotes"],
            },
        )
        await session.commit()
        return counts
    except Exception:
        await session.rollback()
        raise


async def mark_failed(session: AsyncSession, video_id: str, error: str) -> None:
    try:
        await session.execute(
            text(
                """
                INSERT INTO enriched_videos (video_id, status, error, enriched_at)
                VALUES (:v, 'failed', :e, now())
                ON CONFLICT (video_id) DO UPDATE
                SET status = 'failed', error = EXCLUDED.error, enriched_at = now()
                """
            ),
            {"v": video_id, "e": error[:1000]},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
