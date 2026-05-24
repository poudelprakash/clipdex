"""Grounded question generation for return episodes.

For a given canonical guest:

1. Fetch the guest's topics and quotes from prior appearances.
2. Build a compact context block.
3. Send to Claude via ``llm_client.complete`` with a tiny schema:
   ``QuestionSet(guest_id, generated_at, questions[Question(text, rationale, grounded_in=[QuoteRef])])``.
4. Return the structured response. Each question references a real
   quote, so the model can't fall back to a generic "what's your origin story?"

System prompt is cacheable; user block is per-guest.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clipdex_api.db import session
from clipdex_schema import Question, QuestionSet, QuoteRef
from llm_client import complete

log = logging.getLogger("clipdex.questions")

router = APIRouter()

SYSTEM_PROMPT = """\
You generate follow-up interview questions for a podcast guest's *return*
episode. You will receive:

- The guest's canonical name.
- A list of topics they discussed in prior appearances (with counts).
- A list of memorable quotes from prior appearances, each tagged with an id.

Generate up to 10 questions. Each question must:

1. Reference at least one of the supplied quotes (by id) in ``grounded_in``.
2. Build on what the guest has already said — never a generic icebreaker.
3. Be specific enough that the answer would be different from the first
   episode's answer.

Reply by filling in the structured response. If the supplied context is too
thin to ground 10 good questions, return fewer rather than padding.
"""


# --- Internal LLM-side schema ---------------------------------------------
# The schema we send to the LLM uses ``quote_id`` (a small integer) instead of
# the full QuoteRef shape, because the LLM doesn't need to repeat the entire
# quote text or url back — we look them up by id.


class _LlmQuestion(BaseModel):
    text: str
    rationale: str
    grounded_in: list[int]


class _LlmQuestionSet(BaseModel):
    questions: list[_LlmQuestion]


@router.post("/api/guests/{guest_id}/questions", response_model=QuestionSet)
async def generate_questions(guest_id: str) -> QuestionSet:
    async with session() as s:
        ctx = await _load_context(s, guest_id=guest_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="guest not found")
    return await _generate(ctx)


# --- Implementation --------------------------------------------------------


class _GuestContext(BaseModel):
    id: str
    canonical_name: str
    topics: list[tuple[str, int]]
    quotes: list[QuoteRef]


async def _load_context(s: AsyncSession, *, guest_id: str) -> _GuestContext | None:
    r = await s.execute(
        text(
            "SELECT id::text AS id, canonical_name FROM guests "
            "WHERE id = CAST(:gid AS uuid)"
        ),
        {"gid": guest_id},
    )
    head = r.first()
    if head is None:
        return None

    rv = await s.execute(
        text(
            """
            SELECT DISTINCT source_video_id AS vid
            FROM guest_aliases
            WHERE guest_id = CAST(:gid AS uuid) AND source_video_id IS NOT NULL
            """
        ),
        {"gid": guest_id},
    )
    vids = [row.vid for row in rv]
    if not vids:
        return _GuestContext(
            id=head.id, canonical_name=head.canonical_name, topics=[], quotes=[]
        )

    rt = await s.execute(
        text(
            """
            SELECT name, COUNT(*) AS n FROM topics_raw
            WHERE video_id = ANY(:vids)
            GROUP BY name ORDER BY n DESC, name ASC LIMIT 20
            """
        ),
        {"vids": vids},
    )
    topics = [(row.name, int(row.n)) for row in rt]

    rq = await s.execute(
        text(
            """
            SELECT text, video_id FROM quotes_raw
            WHERE video_id = ANY(:vids)
            ORDER BY quotability_score DESC LIMIT 15
            """
        ),
        {"vids": vids},
    )
    quotes = [
        QuoteRef(
            text=row.text,
            video_id=row.video_id,
            youtube_url=f"https://youtu.be/{row.video_id}",
        )
        for row in rq
    ]

    return _GuestContext(
        id=head.id, canonical_name=head.canonical_name, topics=topics, quotes=quotes
    )


async def _generate(ctx: _GuestContext) -> QuestionSet:
    if not ctx.quotes:
        return QuestionSet(
            guest_id=ctx.id,
            generated_at=datetime.now(timezone.utc),
            questions=[],
        )

    topics_block = "\n".join(f"- {name} ({n})" for name, n in ctx.topics) or "(none)"
    quotes_block = "\n".join(
        f'  [{i}] "{q.text}" (from {q.video_id})'
        for i, q in enumerate(ctx.quotes)
    )
    user = (
        f"Guest: {ctx.canonical_name}\n\n"
        f"Topics discussed previously:\n{topics_block}\n\n"
        f"Quotes (each tagged with [id]):\n{quotes_block}\n\n"
        f"Generate up to 10 grounded follow-up questions. In ``grounded_in``, "
        f"list the integer quote ids you build on."
    )

    raw = await complete(
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        schema=_LlmQuestionSet,
        tier="smart",
        cache_system=True,
        max_tokens=2048,
    )
    assert isinstance(raw, _LlmQuestionSet)

    out: list[Question] = []
    for lq in raw.questions:
        grounded = [
            ctx.quotes[i] for i in lq.grounded_in if 0 <= i < len(ctx.quotes)
        ]
        out.append(
            Question(text=lq.text, rationale=lq.rationale, grounded_in=grounded)
        )

    return QuestionSet(
        guest_id=ctx.id,
        generated_at=datetime.now(timezone.utc),
        questions=out,
    )
