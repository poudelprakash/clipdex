from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    youtube_api_key: str = Field(default="")
    youtube_channel_id: str = Field(default="")
    youtube_channel_handle: str = Field(default="")
    uploads_playlist_id: str = Field(default="")

    database_url: str = Field(default="postgresql+psycopg://localhost:5432/clipdex")

    cache_dir: str = Field(default=".cache")
    whisper_model: str = Field(default="base")
    max_videos_per_run: int = Field(default=0)  # 0 = unbounded

    # YouTube increasingly requires a signed-in session to serve metadata.
    # Set to "chrome" / "safari" / "firefox" to pull cookies from your local
    # browser via yt-dlp. Empty disables.
    ytdlp_cookies_from_browser: str = Field(default="")

    # Pacing & rate-limit handling. YouTube 429s any IP that pulls captions
    # too quickly; spacing requests out is the only reliable mitigation.
    ingest_per_video_delay_seconds: float = Field(default=3.0)
    # Comma-separated seconds to sleep between successive 429 retries; empty disables retry.
    ingest_429_backoff_schedule: str = Field(default="30,60,120")
    # When true, ignore latest_published cutoff and walk the full uploads playlist,
    # relying on per-video already_done dedup. Use for backfills and to retry failed rows.
    ingest_backfill_mode: bool = Field(default=False)


settings = Settings()
