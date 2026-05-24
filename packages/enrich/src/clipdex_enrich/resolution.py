"""Guest entity resolution.

Three stages, in order of cost:

1. **Exact** — normalize (lowercase, strip, collapse whitespace, fold accents)
   then exact-match the normalized name against existing guests / aliases.
2. **Fuzzy** — rapidfuzz token-set ratio against candidate normalized names.
   ≥ ``auto_merge_threshold`` → attach as an alias automatically.
   between ``review_threshold`` and ``auto_merge_threshold`` → punt to LLM or review.
3. **LLM** — for ambiguous pairs we send the two names plus their episode contexts
   to Claude and ask yes/no/uncertain. Cached in ``guest_merge_decisions`` so
   we never ask twice. ``yes`` → attach alias; ``no`` → new canonical guest;
   ``uncertain`` → queue for human review.

The output of one ``resolve_all()`` run: every row in ``guests_raw`` is either
attached to a row in ``guests`` (via ``guest_aliases``) or queued in
``guest_merge_review`` for a human. Nothing is dropped.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("clipdex.resolution")


# --- Tunable thresholds ---------------------------------------------------

AUTO_MERGE_THRESHOLD = 90  # token_set_ratio ≥ this → auto-attach as alias
REVIEW_THRESHOLD = 70  # below this → treat as a new guest, no review needed


# --- Normalization --------------------------------------------------------


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace.

    Two strings normalize to the same value when the canonical-form match is
    safe enough that we skip fuzzy. Examples:

        "Bibhusan Bista" -> "bibhusan bista"
        "Bibhusan B."    -> "bibhusan b"
        "Bíbhuśan Bistá" -> "bibhusan bista"
    """
    # NFKD then drop combining marks (accents).
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    # Replace any non-alphanumeric with a space; collapse runs.
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


# --- Data shapes ----------------------------------------------------------


@dataclass(frozen=True)
class RawGuest:
    raw_id: int
    video_id: str
    name: str
    role: str | None
    company: str | None
    confidence: float


@dataclass(frozen=True)
class CanonicalGuest:
    id: str  # UUID as str
    canonical_name: str
    normalized_name: str


@dataclass
class ResolutionCounts:
    seen: int = 0
    skipped_already_attached: int = 0
    exact_match: int = 0
    fuzzy_auto_merge: int = 0
    llm_yes: int = 0
    llm_no: int = 0
    llm_uncertain: int = 0
    new_canonical: int = 0
    queued_for_review: int = 0


# --- DB helpers -----------------------------------------------------------


async def _load_all_raw(session: AsyncSession) -> list[RawGuest]:
    r = await session.execute(
        text(
            """
            SELECT gr.id, gr.video_id, gr.name, gr.role, gr.company, gr.confidence
            FROM guests_raw gr
            ORDER BY gr.id
            """
        )
    )
    return [
        RawGuest(
            raw_id=row.id,
            video_id=row.video_id,
            name=row.name,
            role=row.role,
            company=row.company,
            confidence=row.confidence,
        )
        for row in r
    ]


async def _load_canonical(session: AsyncSession) -> list[CanonicalGuest]:
    r = await session.execute(
        text("SELECT id::text AS id, canonical_name, normalized_name FROM guests")
    )
    return [
        CanonicalGuest(
            id=row.id,
            canonical_name=row.canonical_name,
            normalized_name=row.normalized_name,
        )
        for row in r
    ]


async def _alias_exists(
    session: AsyncSession, guest_id: str, normalized_alias: str
) -> bool:
    r = await session.execute(
        text(
            """
            SELECT 1 FROM guest_aliases
            WHERE guest_id = CAST(:gid AS uuid) AND normalized_alias = :n
            """
        ),
        {"gid": guest_id, "n": normalized_alias},
    )
    return r.first() is not None


async def _attach_alias(
    session: AsyncSession,
    *,
    guest_id: str,
    raw: RawGuest,
    normalized_alias: str,
    confidence: float,
    decided_by: str,
) -> bool:
    if await _alias_exists(session, guest_id, normalized_alias):
        return False
    await session.execute(
        text(
            """
            INSERT INTO guest_aliases
              (guest_id, alias_name, normalized_alias, source_video_id, confidence, decided_by)
            VALUES
              (CAST(:gid AS uuid), :alias, :norm, :vid, :conf, :decided_by)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "gid": guest_id,
            "alias": raw.name,
            "norm": normalized_alias,
            "vid": raw.video_id,
            "conf": float(confidence),
            "decided_by": decided_by,
        },
    )
    return True


async def _create_canonical(
    session: AsyncSession, raw: RawGuest, normalized: str
) -> str:
    """Insert a new canonical guest + its first (exact) alias.

    Returns the new guest id (UUID as string).
    """
    r = await session.execute(
        text(
            """
            INSERT INTO guests (canonical_name, normalized_name)
            VALUES (:c, :n)
            ON CONFLICT (normalized_name) DO UPDATE
              SET canonical_name = EXCLUDED.canonical_name
            RETURNING id::text AS id
            """
        ),
        {"c": raw.name, "n": normalized},
    )
    row = r.first()
    assert row is not None
    guest_id: str = row.id
    await _attach_alias(
        session,
        guest_id=guest_id,
        raw=raw,
        normalized_alias=normalized,
        confidence=raw.confidence,
        decided_by="exact",
    )
    return guest_id


async def _queue_for_review(
    session: AsyncSession,
    *,
    guest_id: str,
    raw: RawGuest,
    canonical_name: str,
    score: float,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO guest_merge_review
              (guest_id, raw_id, candidate_name, canonical_name, score)
            VALUES
              (CAST(:gid AS uuid), :raw_id, :cand, :canon, :score)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "gid": guest_id,
            "raw_id": raw.raw_id,
            "cand": raw.name,
            "canon": canonical_name,
            "score": float(score),
        },
    )


async def _cached_llm_decision(
    session: AsyncSession, norm_a: str, norm_b: str
) -> str | None:
    a, b = sorted([norm_a, norm_b])
    r = await session.execute(
        text(
            """
            SELECT decision FROM guest_merge_decisions
            WHERE norm_a = :a AND norm_b = :b
            """
        ),
        {"a": a, "b": b},
    )
    row = r.first()
    return row.decision if row else None


async def _save_llm_decision(
    session: AsyncSession,
    *,
    norm_a: str,
    norm_b: str,
    decision: str,
    rationale: str | None,
    decided_by: str = "llm",
) -> None:
    a, b = sorted([norm_a, norm_b])
    await session.execute(
        text(
            """
            INSERT INTO guest_merge_decisions (norm_a, norm_b, decision, rationale, decided_by)
            VALUES (:a, :b, :d, :r, :by)
            ON CONFLICT (norm_a, norm_b) DO UPDATE
              SET decision = EXCLUDED.decision,
                  rationale = EXCLUDED.rationale,
                  decided_by = EXCLUDED.decided_by,
                  decided_at = now()
            """
        ),
        {"a": a, "b": b, "d": decision, "r": rationale, "by": decided_by},
    )


async def _context_for_raw(session: AsyncSession, raw: RawGuest) -> str:
    """A few quotes / topics from this guest's source video as LLM context."""
    r = await session.execute(
        text(
            """
            SELECT text FROM quotes_raw
            WHERE video_id = :v
            ORDER BY quotability_score DESC
            LIMIT 3
            """
        ),
        {"v": raw.video_id},
    )
    quotes = [row.text for row in r]
    role_co = " / ".join(p for p in [raw.role or "", raw.company or ""] if p)
    head = f"{raw.name} ({role_co})" if role_co else raw.name
    if quotes:
        joined = " | ".join(q[:140] for q in quotes)
        return f"{head} — quoted: {joined}"
    return head


async def _context_for_canonical(
    session: AsyncSession, canon: CanonicalGuest
) -> str:
    """Pull a sample alias + one quote from one of the canonical guest's source
    videos for LLM context."""
    r = await session.execute(
        text(
            """
            SELECT ga.alias_name, ga.source_video_id
            FROM guest_aliases ga
            WHERE ga.guest_id = CAST(:gid AS uuid)
            ORDER BY ga.created_at
            LIMIT 1
            """
        ),
        {"gid": canon.id},
    )
    row = r.first()
    if not row or not row.source_video_id:
        return canon.canonical_name
    rq = await session.execute(
        text(
            """
            SELECT text FROM quotes_raw
            WHERE video_id = :v
            ORDER BY quotability_score DESC
            LIMIT 2
            """
        ),
        {"v": row.source_video_id},
    )
    quotes = [r2.text for r2 in rq]
    if quotes:
        return f"{canon.canonical_name} — quoted: {' | '.join(q[:140] for q in quotes)}"
    return canon.canonical_name


# --- LLM disambiguation ---------------------------------------------------

LLM_SYSTEM = """\
You decide whether two podcast guest mentions refer to the same person.

You will be given two candidate names with a snippet of context for each
(role, company, or a quote from the episode they appeared on). Reply with a
single JSON object, no preamble:

  {"decision": "yes" | "no" | "uncertain", "rationale": "<one short sentence>"}

Be conservative. "yes" only if the evidence clearly aligns (matching role,
company, distinctive quote style, or near-identical name with no conflicting
signals). "uncertain" is fine and preferred over a wrong "yes".
"""


async def _ask_llm(
    *,
    name_a: str,
    context_a: str,
    name_b: str,
    context_b: str,
) -> tuple[str, str]:
    """Ask the active LLM whether two guest mentions are the same person.

    Returns ``(decision, rationale)``. Decision is one of ``yes`` / ``no`` /
    ``uncertain``. Anything we can't parse falls back to ``uncertain``.
    """
    import json

    from llm_client import complete

    user = (
        f"Candidate A: {name_a}\n"
        f"Context A: {context_a}\n\n"
        f"Candidate B: {name_b}\n"
        f"Context B: {context_b}\n"
    )
    text_raw = await complete(
        system=LLM_SYSTEM,
        messages=[{"role": "user", "content": user}],
        tier="cheap",
        cache_system=True,
        max_tokens=200,
    )
    text_out = text_raw if isinstance(text_raw, str) else str(text_raw)
    start = text_out.find("{")
    end = text_out.rfind("}")
    if start == -1 or end == -1 or end < start:
        return "uncertain", f"unparseable LLM reply: {text_out[:120]}"
    try:
        obj = json.loads(text_out[start : end + 1])
    except json.JSONDecodeError:
        return "uncertain", f"invalid JSON: {text_out[start : end + 1][:120]}"
    decision = str(obj.get("decision", "uncertain")).lower()
    if decision not in ("yes", "no", "uncertain"):
        decision = "uncertain"
    rationale = str(obj.get("rationale", ""))[:280]
    return decision, rationale


# --- Main entry points ----------------------------------------------------


async def resolve_all(
    session: AsyncSession,
    *,
    use_llm: bool = True,
    auto_merge_threshold: int = AUTO_MERGE_THRESHOLD,
    review_threshold: int = REVIEW_THRESHOLD,
) -> ResolutionCounts:
    """Resolve every `guests_raw` row.

    Idempotent: if a raw row is already attached as an alias (by normalized
    name match), it's skipped.
    """
    counts = ResolutionCounts()
    raws = await _load_all_raw(session)
    canonicals = await _load_canonical(session)
    canon_by_norm: dict[str, CanonicalGuest] = {
        c.normalized_name: c for c in canonicals
    }
    # All known aliases (any decided_by) for the exact-match step.
    r = await session.execute(
        text("SELECT normalized_alias, guest_id::text AS guest_id FROM guest_aliases")
    )
    alias_to_guest: dict[str, str] = {row.normalized_alias: row.guest_id for row in r}

    for raw in raws:
        counts.seen += 1
        normalized = normalize_name(raw.name)
        if not normalized:
            continue

        # Stage 1: exact match against alias or canonical.
        existing = alias_to_guest.get(normalized) or (
            canon_by_norm[normalized].id if normalized in canon_by_norm else None
        )
        if existing:
            attached = await _attach_alias(
                session,
                guest_id=existing,
                raw=raw,
                normalized_alias=normalized,
                confidence=max(raw.confidence, 0.99),
                decided_by="exact",
            )
            if attached:
                counts.exact_match += 1
                alias_to_guest[normalized] = existing
            else:
                counts.skipped_already_attached += 1
            continue

        # Stage 2: fuzzy match against canonical normalized names.
        candidate_id, score = _best_fuzzy(normalized, canon_by_norm)
        if candidate_id is None or score < review_threshold:
            # No reasonable candidate — create a new canonical guest.
            new_id = await _create_canonical(session, raw, normalized)
            counts.new_canonical += 1
            canon_by_norm[normalized] = CanonicalGuest(
                id=new_id, canonical_name=raw.name, normalized_name=normalized
            )
            alias_to_guest[normalized] = new_id
            continue

        if score >= auto_merge_threshold:
            await _attach_alias(
                session,
                guest_id=candidate_id,
                raw=raw,
                normalized_alias=normalized,
                confidence=score / 100.0,
                decided_by="fuzzy",
            )
            counts.fuzzy_auto_merge += 1
            alias_to_guest[normalized] = candidate_id
            continue

        # Stage 3: LLM disambiguation (70 ≤ score < 90).
        candidate_canon = next(
            c for c in canon_by_norm.values() if c.id == candidate_id
        )
        decision = await _llm_decide(
            session,
            raw=raw,
            normalized=normalized,
            candidate=candidate_canon,
            use_llm=use_llm,
        )
        if decision == "yes":
            await _attach_alias(
                session,
                guest_id=candidate_id,
                raw=raw,
                normalized_alias=normalized,
                confidence=score / 100.0,
                decided_by="llm",
            )
            alias_to_guest[normalized] = candidate_id
            counts.llm_yes += 1
        elif decision == "no":
            new_id = await _create_canonical(session, raw, normalized)
            canon_by_norm[normalized] = CanonicalGuest(
                id=new_id, canonical_name=raw.name, normalized_name=normalized
            )
            alias_to_guest[normalized] = new_id
            counts.llm_no += 1
        else:  # uncertain
            await _queue_for_review(
                session,
                guest_id=candidate_id,
                raw=raw,
                canonical_name=candidate_canon.canonical_name,
                score=score,
            )
            counts.queued_for_review += 1
            counts.llm_uncertain += 1

    await session.commit()
    return counts


def _best_fuzzy(
    normalized: str, canonicals: dict[str, CanonicalGuest]
) -> tuple[str | None, float]:
    if not canonicals:
        return None, 0.0
    choices = list(canonicals.keys())
    match = process.extractOne(
        normalized, choices, scorer=fuzz.token_set_ratio
    )
    if match is None:
        return None, 0.0
    matched_norm, score, _ = match
    return canonicals[matched_norm].id, float(score)


async def _llm_decide(
    session: AsyncSession,
    *,
    raw: RawGuest,
    normalized: str,
    candidate: CanonicalGuest,
    use_llm: bool,
) -> str:
    """Return 'yes' | 'no' | 'uncertain'. Cached in guest_merge_decisions."""
    cached = await _cached_llm_decision(session, normalized, candidate.normalized_name)
    if cached is not None:
        return cached

    if not use_llm:
        return "uncertain"

    ctx_a = await _context_for_raw(session, raw)
    ctx_b = await _context_for_canonical(session, candidate)
    decision, rationale = await _ask_llm(
        name_a=raw.name,
        context_a=ctx_a,
        name_b=candidate.canonical_name,
        context_b=ctx_b,
    )
    await _save_llm_decision(
        session,
        norm_a=normalized,
        norm_b=candidate.normalized_name,
        decision=decision,
        rationale=rationale,
    )
    return decision


async def unmerge(
    session: AsyncSession, *, guest_id: str, alias_id: int
) -> str:
    """Split a guest by promoting one alias into its own canonical row.

    Returns the new canonical guest's id. Raises if the alias doesn't belong
    to the named guest or is the only alias (in which case there's nothing
    to split).
    """
    r = await session.execute(
        text(
            """
            SELECT id, alias_name, normalized_alias, source_video_id, confidence
            FROM guest_aliases
            WHERE id = :aid AND guest_id = CAST(:gid AS uuid)
            """
        ),
        {"aid": alias_id, "gid": guest_id},
    )
    alias = r.first()
    if not alias:
        raise ValueError(f"alias {alias_id} not found on guest {guest_id}")

    r2 = await session.execute(
        text(
            "SELECT count(*) AS n FROM guest_aliases WHERE guest_id = CAST(:gid AS uuid)"
        ),
        {"gid": guest_id},
    )
    n = r2.first().n  # type: ignore[union-attr]
    if n <= 1:
        raise ValueError("cannot unmerge: guest has only one alias")

    # Make sure the promoted alias' normalized name doesn't already collide.
    r3 = await session.execute(
        text("SELECT id::text AS id FROM guests WHERE normalized_name = :n"),
        {"n": alias.normalized_alias},
    )
    collide = r3.first()
    if collide:
        # Already a separate canonical — just move the alias.
        new_id = collide.id
    else:
        r4 = await session.execute(
            text(
                """
                INSERT INTO guests (canonical_name, normalized_name)
                VALUES (:c, :n)
                RETURNING id::text AS id
                """
            ),
            {"c": alias.alias_name, "n": alias.normalized_alias},
        )
        new_id = r4.first().id  # type: ignore[union-attr]

    await session.execute(
        text("UPDATE guest_aliases SET guest_id = CAST(:new AS uuid) WHERE id = :aid"),
        {"new": new_id, "aid": alias_id},
    )
    r5 = await session.execute(
        text("SELECT normalized_name AS n FROM guests WHERE id = CAST(:gid AS uuid)"),
        {"gid": guest_id},
    )
    src_row = r5.first()
    if src_row is not None:
        await _save_llm_decision(
            session,
            norm_a=alias.normalized_alias,
            norm_b=src_row.n,
            decision="no",
            rationale="manual unmerge",
            decided_by="manual",
        )
    await session.commit()
    return new_id


__all__ = [
    "AUTO_MERGE_THRESHOLD",
    "REVIEW_THRESHOLD",
    "ResolutionCounts",
    "normalize_name",
    "resolve_all",
    "unmerge",
]
