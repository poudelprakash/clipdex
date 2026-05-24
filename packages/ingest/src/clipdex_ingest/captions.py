"""Caption extraction via yt-dlp's subs-only mode.

The YouTube Data API's `captions.download` endpoint requires OAuth and is, in
practice, limited to videos you own. Third-party libraries that scrape the
watch page (e.g. youtube-transcript-api) are easily IP-blocked. yt-dlp uses
the YouTube player API directly and is the most robust path that doesn't
require downloading any media — `--write-auto-subs --skip-download` fetches
just the auto-generated WebVTT file.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import webvtt

from clipdex_ingest.settings import settings
from clipdex_schema import TranscriptSegment


def _cache_dir() -> Path:
    return Path(settings.cache_dir) / "captions"


def _fetch_vtt_sync(video_id: str) -> Path | None:
    """Download the auto-generated English subs as WebVTT. Returns the cached path or None."""
    import yt_dlp

    out_dir = _cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / f"{video_id}.%(ext)s")

    ydl_opts: dict = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "subtitlesformat": "vtt",
        "outtmpl": template,
        "quiet": True,
        "no_warnings": True,
        # Subs-only: don't fail when media formats can't be resolved (n-challenge etc).
        "ignore_no_formats_error": True,
    }
    if settings.ytdlp_cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (settings.ytdlp_cookies_from_browser,)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    for lang in ("en", "en-US", "en-GB"):
        candidate = out_dir / f"{video_id}.{lang}.vtt"
        if candidate.exists():
            return candidate
    return None


async def fetch_captions(video_id: str) -> list[TranscriptSegment] | None:
    """Return parsed segments, or None if no caption track is available."""
    out_dir = _cache_dir()
    cached: Path | None = None
    for lang in ("en", "en-US", "en-GB"):
        candidate = out_dir / f"{video_id}.{lang}.vtt"
        if candidate.exists():
            cached = candidate
            break
    if cached is None:
        cached = await asyncio.to_thread(_fetch_vtt_sync, video_id)
        if cached is None:
            return None

    segments = list(_parse_vtt(cached, video_id))
    return segments or None


def _parse_vtt(path: Path, video_id: str) -> Iterator[TranscriptSegment]:
    """Parse YouTube auto-caption WebVTT, collapsing the rolling-cue format.

    Auto-captions emit each line twice: once as a 10ms transition (e.g.
    5.110 -> 5.120) and once as the "real" cue that overlaps with the next
    line. We keep only cues with non-trivial duration, and from multi-line
    cues we take only the LAST line (the new content being appended).
    """
    seq = 0
    prev_text: str | None = None
    for cue in webvtt.read(str(path)):
        start_ms = int(cue.start_in_seconds * 1000)
        end_ms = int(cue.end_in_seconds * 1000)
        # Skip the rolling transition cues — they have ~10ms durations.
        if end_ms - start_ms < 200:
            continue
        lines = [line.strip() for line in cue.text.splitlines() if line.strip()]
        if not lines:
            continue
        text = lines[-1]
        # Dedupe consecutive identical lines from caption stickiness.
        if text == prev_text:
            continue
        prev_text = text
        yield TranscriptSegment(
            video_id=video_id,
            seq=seq,
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            source="youtube-captions",
        )
        seq += 1
