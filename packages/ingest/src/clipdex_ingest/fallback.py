from pathlib import Path

from clipdex_schema import TranscriptSegment
from clipdex_ingest.settings import settings


def transcribe_with_whisper(video_id: str) -> list[TranscriptSegment]:
    """Download audio with yt-dlp, transcribe with local Whisper, delete the media.

    The `fallback` extra must be installed:
        uv sync --package clipdex-ingest --extra fallback
    """
    try:
        import whisper
        import yt_dlp
    except ImportError as e:
        raise RuntimeError(
            "Whisper fallback requested but the `fallback` extra is not installed.\n"
            "Run: uv sync --package clipdex-ingest --extra fallback"
        ) from e

    audio_dir = Path(settings.cache_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"{video_id}.m4a"

    ydl_opts: dict = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(audio_path.with_suffix(".%(ext)s")),
        "quiet": True,
        "no_warnings": True,
    }
    if settings.ytdlp_cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (settings.ytdlp_cookies_from_browser,)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    model = whisper.load_model(settings.whisper_model)
    result = model.transcribe(str(audio_path), word_timestamps=False)

    audio_path.unlink(missing_ok=True)

    return [
        TranscriptSegment(
            video_id=video_id,
            seq=i,
            start_ms=int(seg["start"] * 1000),
            end_ms=int(seg["end"] * 1000),
            text=seg["text"].strip(),
            source="whisper-fallback",
        )
        for i, seg in enumerate(result["segments"])
    ]
