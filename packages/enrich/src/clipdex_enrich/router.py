"""Tiered routing: Haiku for cheap classification, Sonnet for extraction.

This is a thin layer over the Anthropic SDK. Post 5 replaces it with the
provider-switching `llm-client` package; until then we call Anthropic directly.
"""

from anthropic import AsyncAnthropic

from clipdex_enrich.settings import settings

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set; add it to .env.")
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def is_substantive(chunk_text: str) -> bool:
    """Haiku-class binary classifier: is this chunk worth extracting from?

    Cheap pre-filter. Filler — sponsor reads, banter, intros without content,
    repeated outros — is `no`. A guest intro, substantive topic, or quotable
    statement is `yes`. Saves Sonnet calls on chunks that wouldn't produce
    anything anyway.
    """
    client = get_client()
    response = await client.messages.create(
        model=settings.model_cheap,
        max_tokens=8,
        system=(
            "Reply with exactly 'yes' or 'no'. "
            "Default to 'yes' unless the chunk is clearly worthless. "
            "Only answer 'no' when the entire chunk is sponsor reads, intro/outro music "
            "stings, or pure filler with no real content. Any real conversation — even "
            "short — is 'yes'."
        ),
        messages=[{"role": "user", "content": chunk_text}],
    )
    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text
    return text.strip().lower().startswith("y")
