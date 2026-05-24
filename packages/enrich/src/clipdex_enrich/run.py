import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from clipdex_enrich.chunk import chunk_segments
from clipdex_enrich.extract import extract_chunk
from clipdex_enrich.router import is_substantive
from clipdex_enrich.settings import settings
from clipdex_enrich.store import (
    already_enriched,
    list_done_videos,
    load_segments,
    mark_failed,
    save_extractions,
)

log = logging.getLogger("clipdex.enrich")


def _engine_url() -> str:
    db_url = settings.database_url
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://") :]
    return db_url


async def enrich_video(session: AsyncSession, video_id: str) -> dict[str, int]:
    segments = await load_segments(session, video_id)
    if not segments:
        log.info("enrich: %s no segments — skipped", video_id)
        return {"chunks": 0, "guests": 0, "topics": 0, "quotes": 0}

    chunks = chunk_segments(
        segments,
        window_seconds=settings.chunk_window_seconds,
        overlap_seconds=settings.chunk_overlap_seconds,
    )
    log.info("enrich: %s -> %d chunks", video_id, len(chunks))

    per_chunk = []
    skipped = 0
    for c in chunks:
        chunk_text = c.to_prompt_text()
        if not await is_substantive(chunk_text):
            log.info("enrich: %s chunk@%ds triaged out", video_id, c.start_ms // 1000)
            skipped += 1
            continue
        ex = await extract_chunk(chunk_text)
        per_chunk.append((c.start_ms, ex))
        log.info(
            "enrich: %s chunk@%ds guests=%d topics=%d quotes=%d",
            video_id,
            c.start_ms // 1000,
            len(ex.guests),
            len(ex.topics),
            len(ex.quotes),
        )
    log.info(
        "enrich: %s triage kept %d / %d chunks",
        video_id,
        len(per_chunk),
        len(chunks),
    )
    _ = skipped

    counts = await save_extractions(session, video_id=video_id, per_chunk=per_chunk)
    return {"chunks": len(chunks), **counts}


async def enrich_once(target_video_id: str | None = None) -> dict[str, int]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set; add it to .env.")

    engine = create_async_engine(_engine_url())
    stats = {"ok": 0, "skipped": 0, "failed": 0}

    async with AsyncSession(engine) as session:
        if target_video_id:
            video_ids = [target_video_id]
        else:
            video_ids = await list_done_videos(
                session, limit=settings.max_videos_per_run
            )
        log.info("enrich: %d videos to process", len(video_ids))

        for vid in video_ids:
            if not target_video_id and await already_enriched(session, vid):
                stats["skipped"] += 1
                continue
            try:
                summary = await enrich_video(session, vid)
                log.info("enrich: %s done %s", vid, summary)
                stats["ok"] += 1
            except Exception as e:  # noqa: BLE001
                log.exception("enrich: %s failed", vid)
                await session.rollback()
                await mark_failed(session, vid, str(e))
                stats["failed"] += 1

    await engine.dispose()
    log.info("enrich: done. %s", stats)
    return stats


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    target = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(enrich_once(target))


if __name__ == "__main__":
    main()
