"""Schema-first extraction using Anthropic's tool_use for guaranteed JSON shape.

Pattern:
  - System block carries the schema + instructions (prompt-cached).
  - User block carries the per-chunk transcript text.
  - We expose `record_extraction(...)` as a tool whose input_schema *is* the
    Pydantic JSON schema. `tool_choice` forces the model to call it.
  - On `pydantic.ValidationError`, retry once with the error appended.
"""

import json
import logging

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from clipdex_enrich.router import get_client
from clipdex_enrich.settings import settings
from clipdex_schema import Extraction

log = logging.getLogger("clipdex.enrich")

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

Return your answer by calling the `record_extraction` tool. If a category has
no entries, return an empty list for it. Never invent data — if the chunk has
no clear guest intro, return an empty `guests` list.
"""

_TOOL_NAME = "record_extraction"


def _tool_definition() -> dict:
    schema = Extraction.model_json_schema()
    # Anthropic's tool_use is strict about additionalProperties; Pydantic emits
    # `$defs` blocks that already constrain things, so we pass the schema through
    # as-is. If we ever flip strict mode on we'll need to walk and add
    # additionalProperties: false to each object.
    return {
        "name": _TOOL_NAME,
        "description": "Record the structured extraction for one transcript chunk.",
        "input_schema": schema,
    }


async def extract_chunk(chunk_text: str) -> Extraction:
    """Run one extraction pass against Sonnet, retrying once on validation error."""
    client: AsyncAnthropic = get_client()
    tool = _tool_definition()

    # First attempt.
    response = await client.messages.create(
        model=settings.model_smart,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[tool],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": chunk_text}],
    )

    tool_input = _first_tool_input(response)
    try:
        return Extraction.model_validate(tool_input)
    except ValidationError as e:
        log.warning("enrich: validation failed on first try, retrying once: %s", e)

    # Retry once, feeding the error back in so the model can self-correct.
    retry_user = (
        f"Your previous tool call failed Pydantic validation:\n\n{e}\n\n"
        "Re-emit the extraction with the schema fixed. Same transcript follows.\n\n"
        f"{chunk_text}"
    )
    response = await client.messages.create(
        model=settings.model_smart,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[tool],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": retry_user}],
    )
    tool_input = _first_tool_input(response)
    return Extraction.model_validate(tool_input)


def _first_tool_input(response) -> dict:
    for block in response.content:
        if block.type == "tool_use" and block.name == _TOOL_NAME:
            return block.input  # already a parsed dict per SDK
    raise RuntimeError(
        f"model did not call {_TOOL_NAME}; got stop_reason={response.stop_reason!r}, "
        f"blocks={[b.type for b in response.content]}"
    )


def usage_summary(response) -> dict:
    """Pull cache-hit stats from a response. Handy for the post 3 prose."""
    u = response.usage
    return {
        "input": u.input_tokens,
        "output": u.output_tokens,
        "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


# Re-export so callers can `from clipdex_enrich.extract import json`-stringify
# things consistently without importing json twice.
_ = json
