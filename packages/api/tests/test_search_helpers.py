"""Pure-helper tests for the search module — no DB."""

from clipdex_api.search import (
    _hash_ids,
    _hash_text,
    _prune_to_max,
    _reorder_by_ids,
    _snap_to_sentence,
)


class _Row:
    def __init__(self, start_ms: int, end_ms: int, text: str = "") -> None:
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.text = text


def test_prune_keeps_anchor_inside():
    rows = [_Row(i * 10_000, i * 10_000 + 5_000) for i in range(10)]
    anchor_start, anchor_end = 50_000, 55_000
    pruned = _prune_to_max(rows, anchor_start, anchor_end, 60_000)
    assert (pruned[-1].end_ms - pruned[0].start_ms) <= 60_000
    assert any(r.start_ms == anchor_start for r in pruned)


def test_snap_drops_leading_partial():
    s = "and then he said. This is a complete sentence here."
    out = _snap_to_sentence(s)
    assert out.startswith("This is a complete sentence")


def test_snap_keeps_trailing_terminator():
    s = "This is one. This is two."
    assert _snap_to_sentence(s) == s


def test_hash_text_is_stable():
    assert _hash_text("Nepal") == _hash_text("  nepal  ")


def test_hash_ids_order_sensitive():
    a = _hash_ids([("v1", 1), ("v2", 2)])
    b = _hash_ids([("v2", 2), ("v1", 1)])
    assert a != b


def test_reorder_by_ids():
    rows = [
        {"video_id": "a", "seq": 1, "text": ""},
        {"video_id": "b", "seq": 2, "text": ""},
        {"video_id": "c", "seq": 3, "text": ""},
    ]
    out = _reorder_by_ids(rows, [("c", 3), ("a", 1)])
    assert [r["video_id"] for r in out] == ["c", "a"]
