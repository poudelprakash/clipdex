import asyncio
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from clipdex_ingest.captions import fetch_captions
from clipdex_ingest.client import QuotaExceeded, list_uploads, resolve_uploads_playlist
from clipdex_ingest.settings import settings
from clipdex_ingest.store import already_done, latest_published, mark_failed, save_video

log = logging.getLogger("clipdex.ingest")


async def ingest_once(enable_fallback: bool | None = None) -> dict[str, int]:
    if enable_fallback is None:
        enable_fallback = os.getenv("CLIPDEX_ENABLE_FALLBACK", "").lower() in ("1", "true", "yes")

    if not settings.youtube_api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not set; copy .env.example to .env and fill it in.")

    playlist_id = settings.uploads_playlist_id
    if not playlist_id:
        if not (settings.youtube_channel_id or settings.youtube_channel_handle):
            raise RuntimeError(
                "Set UPLOADS_PLAYLIST_ID, YOUTUBE_CHANNEL_ID, or YOUTUBE_CHANNEL_HANDLE in .env."
            )
        playlist_id = await resolve_uploads_playlist(
            channel_id=settings.youtube_channel_id,
            handle=settings.youtube_channel_handle,
        )
        log.info("resolved uploads playlist: %s", playlist_id)

    db_url = settings.database_url
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://") :]
    engine = create_async_engine(db_url)
    stats = {"ok": 0, "skipped": 0, "failed": 0}

    async with AsyncSession(engine) as session:
        if settings.ingest_backfill_mode:
            since = None
            log.info("ingest: backfill mode — walking full uploads playlist")
        else:
            since = await latest_published(session)
        uploads = await list_uploads(playlist_id, since=since)
        if settings.max_videos_per_run > 0:
            uploads = uploads[: settings.max_videos_per_run]
        log.info("ingest: %d uploads to process (since %s)", len(uploads), since)

        for v in uploads:
            vid = v["video_id"]
            if await already_done(session, vid):
                continue
            try:
                segments = await fetch_captions(vid)
                source: str = "youtube-captions"
                if segments is None:
                    if not enable_fallback:
                        log.info("ingest: %s no captions, fallback disabled — skipped", vid)
                        stats["skipped"] += 1
                        continue
                    log.info("ingest: %s no captions, falling back to whisper", vid)
                    from clipdex_ingest.fallback import transcribe_with_whisper

                    segments = transcribe_with_whisper(vid)
                    source = "whisper-fallback"

                await save_video(
                    session,
                    video_id=vid,
                    title=v["title"],
                    published_at=v["published_at"],
                    segments=segments,
                    source=source,
                )
                log.info("ingest: %s -> %d segments (%s)", vid, len(segments), source)
                stats["ok"] += 1
            except QuotaExceeded as e:
                log.warning("ingest: quota exceeded, stopping cleanly: %s", e)
                break
            except Exception as e:  # noqa: BLE001 — we want broad capture per video
                log.exception("ingest: %s failed", vid)
                await session.rollback()
                await mark_failed(session, vid, str(e))
                stats["failed"] += 1
            if settings.ingest_per_video_delay_seconds > 0:
                await asyncio.sleep(settings.ingest_per_video_delay_seconds)

    await engine.dispose()
    log.info("ingest: done. %d ok, %d skipped, %d failed", stats["ok"], stats["skipped"], stats["failed"])
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(ingest_once())


if __name__ == "__main__":
    main()
