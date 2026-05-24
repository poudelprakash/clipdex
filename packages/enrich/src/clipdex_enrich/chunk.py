"""Chunk a transcript into overlapping time windows."""

from dataclasses import dataclass

from clipdex_schema import TranscriptSegment


@dataclass(frozen=True)
class Chunk:
    start_ms: int
    end_ms: int
    segments: list[TranscriptSegment]

    def to_prompt_text(self) -> str:
        """Format segments for the LLM: `[seq] text` per line, so the model can cite seq numbers."""
        return "\n".join(f"[{s.seq}] {s.text.strip()}" for s in self.segments)


def chunk_segments(
    segments: list[TranscriptSegment],
    *,
    window_seconds: int = 300,
    overlap_seconds: int = 30,
) -> list[Chunk]:
    """Group segments into windows of `window_seconds` with `overlap_seconds` overlap.

    Windows are anchored to absolute timestamps. A segment whose start falls inside
    the window is included; that means borderline segments may appear in two
    adjacent chunks, which is the point of the overlap.
    """
    if not segments:
        return []

    window_ms = window_seconds * 1000
    overlap_ms = overlap_seconds * 1000
    stride_ms = window_ms - overlap_ms
    if stride_ms <= 0:
        raise ValueError("overlap must be smaller than window")

    last_end = segments[-1].end_ms
    chunks: list[Chunk] = []
    start = 0
    while start < last_end:
        end = start + window_ms
        bucket = [s for s in segments if s.start_ms < end and s.end_ms > start]
        if bucket:
            chunks.append(Chunk(start_ms=start, end_ms=end, segments=bucket))
        start += stride_ms

    return chunks
