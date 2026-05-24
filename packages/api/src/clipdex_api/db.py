"""Lazy async-engine factory shared across the API."""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine


def _engine_url() -> str:
    db_url = os.getenv(
        "DATABASE_URL", "postgresql://localhost:5432/clipdex"
    )
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://") :]
    return db_url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(_engine_url())


def session() -> AsyncSession:
    return AsyncSession(get_engine())
