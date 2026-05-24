"""Unit tests for the deterministic stages of guest resolution.

We don't need a DB for these — the normalization + fuzzy threshold logic
is pure. The DB-backed integration check is in `scripts/demo_resolution.py`.
"""

from rapidfuzz import fuzz

from clipdex_enrich.resolution import (
    AUTO_MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    normalize_name,
)


def test_normalize_basic():
    assert normalize_name("Bibhusan Bista") == "bibhusan bista"
    assert normalize_name("BIBHUSAN  BISTA  ") == "bibhusan bista"
    assert normalize_name("Bibhusan B.") == "bibhusan b"


def test_normalize_strips_accents():
    assert normalize_name("Bíbhuśan Bistá") == "bibhusan bista"


def test_normalize_drops_punctuation():
    assert normalize_name("Dr. Bibhusan-Bista, PhD") == "dr bibhusan bista phd"


def test_fuzzy_initials_below_auto_merge():
    # "Bibhusan B." vs "Bibhusan Bista" — token_set_ratio is high but the
    # initial vs full surname keeps it under 90 in practice, so it should
    # land in the LLM/review band.
    s = fuzz.token_set_ratio(
        normalize_name("Bibhusan B."), normalize_name("Bibhusan Bista")
    )
    assert s >= REVIEW_THRESHOLD


def test_fuzzy_typo_auto_merge():
    s = fuzz.token_set_ratio(
        normalize_name("Bibhusan Bista"), normalize_name("Bibhushan Bista")
    )
    assert s >= AUTO_MERGE_THRESHOLD


def test_fuzzy_unrelated_below_review():
    s = fuzz.token_set_ratio(
        normalize_name("Bibhusan Bista"), normalize_name("Ramesh Khanal")
    )
    assert s < REVIEW_THRESHOLD
