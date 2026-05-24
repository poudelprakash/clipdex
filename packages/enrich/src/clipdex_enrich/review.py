"""`task guests:review` — tiny CLI for human y/n on low-confidence merges.

Queue rows live in ``guest_merge_review`` (populated by ``resolution.resolve_all``
when the LLM is uncertain about a 70–89 fuzzy candidate).

Flow per row:

  candidate "Bibhusan B." (from video xyz)  ~85
    vs canonical "Bibhusan Bista"
    > y/n/s (skip)/u (unmerge later)/q (quit)

Approved → alias attached to the canonical guest, marked ``manual``.
Rejected → new canonical guest, decision cached so we don't re-ask the LLM.
Skip    → leaves the row in the queue.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from clipdex_enrich.resolution import (
    RawGuest,
    _attach_alias,
    _create_canonical,
    _save_llm_decision,
    normalize_name,
)
from clipdex_enrich.run import _engine_url


async def _pending(session: AsyncSession) -> list[dict]:
    r = await session.execute(
        text(
            """
            SELECT r.id AS review_id,
                   r.guest_id::text AS guest_id,
                   r.candidate_name,
                   r.canonical_name,
                   r.score,
                   gr.id AS raw_id,
                   gr.video_id,
                   gr.role,
                   gr.company,
                   gr.confidence
            FROM guest_merge_review r
            JOIN guests_raw gr ON gr.id = r.raw_id
            WHERE r.status = 'pending'
            ORDER BY r.score DESC, r.id
            """
        )
    )
    return [dict(row._mapping) for row in r]


async def _quotes_for(session: AsyncSession, video_id: str, limit: int = 2) -> list[str]:
    r = await session.execute(
        text(
            """
            SELECT text FROM quotes_raw
            WHERE video_id = :v
            ORDER BY quotability_score DESC
            LIMIT :n
            """
        ),
        {"v": video_id, "n": limit},
    )
    return [row.text for row in r]


async def _approve(session: AsyncSession, row: dict) -> None:
    raw = RawGuest(
        raw_id=row["raw_id"],
        video_id=row["video_id"],
        name=row["candidate_name"],
        role=row["role"],
        company=row["company"],
        confidence=float(row["confidence"]),
    )
    normalized = normalize_name(raw.name)
    await _attach_alias(
        session,
        guest_id=row["guest_id"],
        raw=raw,
        normalized_alias=normalized,
        confidence=float(row["score"]) / 100.0,
        decided_by="manual",
    )
    await session.execute(
        text(
            """
            UPDATE guest_merge_review
               SET status = 'approved', decided_at = now()
             WHERE id = :rid
            """
        ),
        {"rid": row["review_id"]},
    )
    # Get the canonical's normalized form so the decision cache key is right.
    rc = await session.execute(
        text(
            "SELECT normalized_name AS n FROM guests WHERE id = CAST(:gid AS uuid)"
        ),
        {"gid": row["guest_id"]},
    )
    canon = rc.first()
    if canon is not None:
        await _save_llm_decision(
            session,
            norm_a=normalized,
            norm_b=canon.n,
            decision="yes",
            rationale="approved via guests:review",
            decided_by="manual",
        )


async def _reject(session: AsyncSession, row: dict) -> None:
    raw = RawGuest(
        raw_id=row["raw_id"],
        video_id=row["video_id"],
        name=row["candidate_name"],
        role=row["role"],
        company=row["company"],
        confidence=float(row["confidence"]),
    )
    normalized = normalize_name(raw.name)
    await _create_canonical(session, raw, normalized)
    await session.execute(
        text(
            """
            UPDATE guest_merge_review
               SET status = 'rejected', decided_at = now()
             WHERE id = :rid
            """
        ),
        {"rid": row["review_id"]},
    )
    rc = await session.execute(
        text("SELECT normalized_name AS n FROM guests WHERE id = CAST(:gid AS uuid)"),
        {"gid": row["guest_id"]},
    )
    canon = rc.first()
    if canon is not None:
        await _save_llm_decision(
            session,
            norm_a=normalized,
            norm_b=canon.n,
            decision="no",
            rationale="rejected via guests:review",
            decided_by="manual",
        )


def _prompt(row: dict, quotes: list[str]) -> str:
    role_co = " / ".join(p for p in [row["role"] or "", row["company"] or ""] if p)
    head = f"{row['candidate_name']}"
    if role_co:
        head += f" ({role_co})"
    body = [
        f"\nCandidate:  {head}",
        f"            video {row['video_id']}",
    ]
    if quotes:
        for q in quotes:
            body.append(f"            > {q[:120]}")
    body.append(f"Canonical:  {row['canonical_name']}  (score {row['score']:.0f})")
    return "\n".join(body)


async def _run() -> int:
    engine = create_async_engine(_engine_url())
    decided = 0
    async with AsyncSession(engine) as session:
        pending = await _pending(session)
        if not pending:
            print("No pending merges. \U0001f44d")
            await engine.dispose()
            return 0
        print(f"{len(pending)} pending merge(s).")
        try:
            for row in pending:
                quotes = await _quotes_for(session, row["video_id"])
                print(_prompt(row, quotes))
                while True:
                    sys.stdout.write("merge? [y/n/s/q] ")
                    sys.stdout.flush()
                    choice = sys.stdin.readline().strip().lower()
                    if choice in ("y", "n", "s", "q", ""):
                        break
                    print(" -> y=yes, n=no, s=skip, q=quit")
                if choice == "q":
                    print("Stopped early.")
                    break
                if choice == "s" or choice == "":
                    continue
                if choice == "y":
                    await _approve(session, row)
                    print("  approved.")
                else:
                    await _reject(session, row)
                    print("  rejected.")
                await session.commit()
                decided += 1
        finally:
            await session.commit()
    await engine.dispose()
    print(f"Decided {decided} merge(s).")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
