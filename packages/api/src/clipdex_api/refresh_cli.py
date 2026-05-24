"""`task search:refresh` — REFRESH MATERIALIZED VIEW transcript_segments_search.

Run this after a fresh ingest (or on a cron). The view is the only thing that
needs warming; the GIN index is updated as a side effect.
"""

from __future__ import annotations

import asyncio

from clipdex_api.db import session
from clipdex_api.search import refresh_search


async def _main() -> None:
    async with session() as s:
        await refresh_search(s)
    print("search: refreshed transcript_segments_search")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
