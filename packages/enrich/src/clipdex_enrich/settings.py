from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="")
    database_url: str = Field(default="postgresql+psycopg://localhost:5432/clipdex")

    # Tier → concrete model. Matches the series brief.
    model_cheap: str = Field(default="claude-haiku-4-5")
    model_smart: str = Field(default="claude-sonnet-4-6")

    # Chunking knobs.
    chunk_window_seconds: int = Field(default=300)  # 5-minute windows
    chunk_overlap_seconds: int = Field(default=30)

    # Bound concurrent extraction calls (the API can do more; we don't need to).
    max_videos_per_run: int = Field(default=0)  # 0 = unbounded


settings = Settings()
