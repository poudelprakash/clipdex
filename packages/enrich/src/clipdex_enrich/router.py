"""Tiered routing helpers.

This module used to wrap ``anthropic.AsyncAnthropic`` directly. As of
series3-post5 it sits on top of the provider-switching ``llm_client`` package,
so the same triage call runs against Anthropic / OpenAI / Ollama / the fake
adapter just by flipping ``LLM_PROVIDER``.

The helper exists rather than inlining ``llm_client.complete`` at each call
site so the triage prompt stays in one place.
"""

from llm_client import complete


async def is_substantive(chunk_text: str) -> bool:
    """Cheap-tier binary classifier: is this chunk worth extracting from?

    Filler — sponsor reads, banter, intros without content, repeated outros —
    is ``no``. A guest intro, substantive topic, or quotable statement is
    ``yes``. Saves smart-tier calls on chunks that wouldn't produce anything
    anyway.
    """
    text = await complete(
        system=(
            "Reply with exactly 'yes' or 'no'. "
            "Default to 'yes' unless the chunk is clearly worthless. "
            "Only answer 'no' when the entire chunk is sponsor reads, intro/outro music "
            "stings, or pure filler with no real content. Any real conversation — even "
            "short — is 'yes'."
        ),
        messages=[{"role": "user", "content": chunk_text}],
        tier="cheap",
        max_tokens=8,
    )
    if not isinstance(text, str):
        text = str(text)
    return text.strip().lower().startswith("y")
