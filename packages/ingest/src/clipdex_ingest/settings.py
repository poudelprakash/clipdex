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


settings = Settings()
