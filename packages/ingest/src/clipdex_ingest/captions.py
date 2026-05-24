from collections.abc import Iterator
from pathlib import Path

import httpx
import webvtt

from clipdex_schema import TranscriptSegment
from clipdex_ingest.client import YT, _raise_for_quota
from clipdex_ingest.settings import settings


def _cache_dir() -> Path:
    return Path(settings.cache_dir) / "captions"


async def pick_track(video_id: str) -> str | None:
    """Return the best English caption track id, or None if no usable track exists.

    Prefers human-authored English over ASR, falls back to any English track.
    """
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(
            f"{YT}/captions",
            params={"part": "snippet", "videoId": video_id, "key": settings.youtube_api_key},
        )
        _raise_for_quota(r)
        items = r.json().get("items", [])

    english = [
        item for item in items if item["snippet"].get("language", "").lower().startswith("en")
    ]
    if not english:
        return None
    for item in english:
        if item["snippet"].get("trackKind") != "ASR":
            return item["id"]
    return english[0]["id"]


async def download_track(track_id: str) -> str:
    """Download a caption track as WebVTT text."""
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(
            f"{YT}/captions/{track_id}",
            params={"tfmt": "vtt", "key": settings.youtube_api_key},
        )
        _raise_for_quota(r)
        return r.text


async def fetch_captions(video_id: str) -> list[TranscriptSegment] | None:
    """Return parsed segments, or None if no usable caption track exists.

    WebVTT is cached on disk so re-runs don't burn 200 quota units per video.
    """
    cached = _cache_dir() / f"{video_id}.vtt"
    if not cached.exists():
        track_id = await pick_track(video_id)
        if track_id is None:
            return None
        vtt = await download_track(track_id)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(vtt, encoding="utf-8")
    return list(_parse_vtt(cached, video_id))


def _parse_vtt(path: Path, video_id: str) -> Iterator[TranscriptSegment]:
    for i, cue in enumerate(webvtt.read(str(path))):
        yield TranscriptSegment(
            video_id=video_id,
            seq=i,
            start_ms=int(cue.start_in_seconds * 1000),
            end_ms=int(cue.end_in_seconds * 1000),
            text=cue.text.replace("\n", " ").strip(),
            source="youtube-captions",
        )
