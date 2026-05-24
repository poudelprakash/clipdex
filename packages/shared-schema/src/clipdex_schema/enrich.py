from pydantic import BaseModel, Field


class GuestMention(BaseModel):
    name: str = Field(description="Full name of the guest as introduced.")
    role: str | None = Field(
        default=None, description="Job title or role, if mentioned."
    )
    company: str | None = Field(
        default=None, description="Company or organization, if mentioned."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence the mention is a real guest (0–1)."
    )


class Topic(BaseModel):
    name: str = Field(description="Short topic label (3–6 words).")
    segment_ids: list[int] = Field(
        description="Transcript segment `seq` numbers where the topic appears."
    )
    confidence: float = Field(ge=0.0, le=1.0)


class Quote(BaseModel):
    text: str = Field(description="The quoted text, verbatim from the transcript.")
    segment_id: int = Field(description="Transcript segment `seq` where the quote starts.")
    speaker: str | None = Field(default=None, description="Speaker name, if known.")
    quotability_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How shareable / standalone the quote is (0–1).",
    )


class Extraction(BaseModel):
    """Top-level container returned by the extractor for a single chunk."""

    guests: list[GuestMention] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    quotes: list[Quote] = Field(default_factory=list)
