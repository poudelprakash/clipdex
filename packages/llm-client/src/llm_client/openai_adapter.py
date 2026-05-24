"""OpenAI adapter — Chat Completions via ``openai.AsyncOpenAI``.

* ``tier="cheap"`` → ``gpt-4o-mini``.
* ``tier="smart"`` → ``gpt-4o``.
* ``schema`` is delivered via ``response_format = {"type": "json_schema", ...}``.
* ``cache_system`` is a no-op on OpenAI today (their server-side prompt cache
  is automatic; we don't need to opt in).

Env overrides:

* ``LLM_OPENAI_CHEAP``
* ``LLM_OPENAI_SMART``
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from llm_client._interface import Message, Tier


class OpenAIAdapter:
    name = "openai"

    def __init__(
        self,
        *,
        cheap: str | None = None,
        smart: str | None = None,
        api_key: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self._cheap = cheap or os.getenv("LLM_OPENAI_CHEAP", "gpt-4o-mini")
        self._smart = smart or os.getenv("LLM_OPENAI_SMART", "gpt-4o")
        self._client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

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
        _ = cache_system  # automatic on OpenAI; flag accepted for parity.
        oa_messages = [{"role": "system", "content": system}, *messages]
        kwargs: dict = {
            "model": self._model_for(tier),
            "messages": oa_messages,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            }
        response = await self._client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        if schema is None:
            return text
        return schema.model_validate(json.loads(text))
