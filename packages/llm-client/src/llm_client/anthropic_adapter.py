"""Anthropic adapter — Claude via ``anthropic.AsyncAnthropic``.

* ``tier="cheap"`` → ``claude-haiku-4-5``.
* ``tier="smart"`` → ``claude-opus-4-7``.
* ``cache_system=True`` wraps the system block in ``cache_control: ephemeral``.
* ``schema`` is delivered via a single ``record`` tool whose ``input_schema``
  is the model's JSON schema; ``tool_choice`` forces the call.

Override the concrete model IDs by passing them to the constructor or via env:

* ``LLM_ANTHROPIC_CHEAP``
* ``LLM_ANTHROPIC_SMART``
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from llm_client._interface import Message, Tier


_TOOL_NAME = "record"


class AnthropicAdapter:
    name = "anthropic"

    def __init__(
        self,
        *,
        cheap: str | None = None,
        smart: str | None = None,
        api_key: str | None = None,
    ) -> None:
        from anthropic import AsyncAnthropic

        self._cheap = cheap or os.getenv("LLM_ANTHROPIC_CHEAP", "claude-haiku-4-5")
        self._smart = smart or os.getenv("LLM_ANTHROPIC_SMART", "claude-opus-4-7")
        self._client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    def _model_for(self, tier: "Tier") -> str:
        return self._cheap if tier == "cheap" else self._smart

    async def complete(
        self,
        *,
        system: str,
        messages: list["Message"],
        schema: type[BaseModel] | None,
        tier: "Tier",
        cache_system: bool,
        max_tokens: int,
    ) -> BaseModel | str:
        system_block: list[dict] = [{"type": "text", "text": system}]
        if cache_system:
            system_block[0]["cache_control"] = {"type": "ephemeral"}

        if schema is None:
            response = await self._client.messages.create(
                model=self._model_for(tier),
                max_tokens=max_tokens,
                system=system_block,
                messages=messages,
            )
            return _extract_text(response)

        tool = {
            "name": _TOOL_NAME,
            "description": "Record the structured response.",
            "input_schema": schema.model_json_schema(),
        }
        # First attempt.
        response = await self._client.messages.create(
            model=self._model_for(tier),
            max_tokens=max_tokens,
            system=system_block,
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=messages,
        )
        tool_input = _first_tool_input(response)
        try:
            return schema.model_validate(tool_input)
        except ValidationError as err:
            retry_user = (
                f"Your previous tool call failed Pydantic validation:\n\n{err}\n\n"
                "Re-emit the response with the schema fixed."
            )
            retry_messages: list[Message] = list(messages) + [  # type: ignore[name-defined]
                {"role": "user", "content": retry_user},
            ]
            response = await self._client.messages.create(
                model=self._model_for(tier),
                max_tokens=max_tokens,
                system=system_block,
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=retry_messages,
            )
            tool_input = _first_tool_input(response)
            return schema.model_validate(tool_input)


def _extract_text(response) -> str:
    out: list[str] = []
    for block in response.content:
        if getattr(block, "type", "") == "text":
            out.append(block.text)
    return "".join(out)


def _first_tool_input(response) -> dict:
    for block in response.content:
        if getattr(block, "type", "") == "tool_use" and block.name == _TOOL_NAME:
            inp = block.input
            return inp if isinstance(inp, dict) else json.loads(inp)
    raise RuntimeError(
        f"model did not call {_TOOL_NAME}; stop_reason={response.stop_reason!r}, "
        f"blocks={[getattr(b, 'type', '?') for b in response.content]}"
    )
