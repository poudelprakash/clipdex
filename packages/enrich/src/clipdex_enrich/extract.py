"""Schema-first extraction over the provider-switching ``llm_client``.

Each transcript chunk → one ``Extraction`` (Pydantic). The client converts
``schema=Extraction`` into whatever the active provider needs (Anthropic
``tool_use``, OpenAI ``response_format=json_schema``, Ollama JSON mode) and
returns a validated instance.

Validation retry, prompt caching of the system block, and tier routing all
live inside the client, so this file stays narrative — just the prompt and
the call.
"""

from llm_client import complete

from clipdex_schema import Extraction

SYSTEM_PROMPT = """\
You extract structured podcast metadata from raw transcript chunks.

Each input line has the form `[N] text`, where N is the segment sequence number.
Use those Ns when reporting `segment_id` / `segment_ids`.

Extract three things:

1. **GuestMention** — people *introduced as guests* (not the host, not third
   parties merely mentioned). Set confidence high (>0.7) only when the line
   clearly introduces them. Skip ambiguous third-party mentions.
2. **Topic** — substantive topics discussed. 3–6 word labels. Cite the seq
   numbers where the topic actually appears, not just where the word appears.
3. **Quote** — standalone, quotable lines from the guest. Skip filler, skip
   the host's questions. `quotability_score` = how well it stands alone.

Return your answer by filling in the structured response. If a category has
no entries, return an empty list for it. Never invent data — if the chunk has
no clear guest intro, return an empty `guests` list.
"""


async def extract_chunk(chunk_text: str) -> Extraction:
    """One extraction pass per chunk. Smart tier; system block is cacheable."""
    result = await complete(
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": chunk_text}],
        schema=Extraction,
        tier="smart",
        cache_system=True,
        max_tokens=4096,
    )
    assert isinstance(result, Extraction)
    return result
