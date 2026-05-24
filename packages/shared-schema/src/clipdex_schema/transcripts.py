from typing import Literal

from pydantic import BaseModel

CaptionSource = Literal["youtube-captions", "whisper-fallback"]


class TranscriptSegment(BaseModel):
    video_id: str
    seq: int
    start_ms: int
    end_ms: int
    text: str
    source: CaptionSource
