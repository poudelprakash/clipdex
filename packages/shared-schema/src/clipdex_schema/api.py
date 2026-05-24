"""Shapes the JSON API serves to the web app.

These are the models the React side will see (re-exported as TS via
``packages/codegen``). They are deliberately denormalized — one round-trip
per route.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GuestSummary(BaseModel):
    """Card on the home page."""

    id: str = Field(description="canonical guest UUID")
    canonical_name: str
    appearance_count: int = Field(ge=0)
    popularity: float = Field(default=0.0, description="appearance + recency score (post 8)")


class Appearance(BaseModel):
    video_id: str
    alias_name: str
    youtube_url: str
    first_seen_at_ms: int | None = Field(
        default=None, description="anchor start_ms inside the video, if known"
    )


class TopicMention(BaseModel):
    name: str
    count: int = Field(ge=1)


class GuestQuote(BaseModel):
    text: str
    video_id: str
    youtube_url: str
    quotability_score: float


class GuestDetail(BaseModel):
    id: str
    canonical_name: str
    appearances: list[Appearance]
    topics: list[TopicMention]
    quotes: list[GuestQuote]


class QuoteRef(BaseModel):
    text: str
    video_id: str
    youtube_url: str


class Question(BaseModel):
    text: str
    rationale: str
    grounded_in: list[QuoteRef]


class QuestionSet(BaseModel):
    guest_id: str
    generated_at: datetime
    questions: list[Question]


class ClipHit(BaseModel):
    video_id: str
    seq: int
    start_ms: int
    end_ms: int
    text: str
    youtube_url: str
    fts_rank: float
    rerank_rationale: str | None = None


class SearchResponse(BaseModel):
    query: str
    cached: bool
    results: list[ClipHit]
