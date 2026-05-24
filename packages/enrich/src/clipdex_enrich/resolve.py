"""`task resolve` — sweep guests_raw → canonical guests + aliases.

Idempotent. Re-runs only touch raw rows that aren't already attached.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from clipdex_enrich.resolution import resolve_all
from clipdex_enrich.run import _engine_url

log = logging.getLogger("clipdex.resolve")


async def _main(use_llm: bool) -> None:
    engine = create_async_engine(_engine_url())
    async with AsyncSession(engine) as session:
        counts = await resolve_all(session, use_llm=use_llm)
    await engine.dispose()
    log.info("resolve: %s", counts)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    use_llm = os.getenv("CLIPDEX_RESOLVE_USE_LLM", "1") not in ("0", "false", "no")
    if "--no-llm" in sys.argv[1:]:
        use_llm = False
    asyncio.run(_main(use_llm))


if __name__ == "__main__":
    main()
