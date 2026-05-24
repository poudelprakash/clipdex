"""Ollama adapter — local models via the Ollama HTTP API.

Talks to the daemon over plain HTTP (default ``http://localhost:11434``). No
SDK dependency — ``httpx`` is enough.

* ``tier="cheap"`` → ``llama3.2:3b``.
* ``tier="smart"`` → ``llama3.2:70b``.
* ``schema`` triggers ``format="json"`` so the model emits valid JSON.
* ``cache_system`` is a no-op (Ollama keeps the conversation context locally
  but doesn't expose a discrete cache directive).

Env overrides:

* ``LLM_OLLAMA_CHEAP``
* ``LLM_OLLAMA_SMART``
* ``OLLAMA_HOST`` — defaults to ``http://localhost:11434``.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    from llm_client._interface import Message, Tier


class OllamaAdapter:
    name = "ollama"

    def __init__(
        self,
        *,
        cheap: str | None = None,
        smart: str | None = None,
        host: str | None = None,
    ) -> None:
        self._cheap = cheap or os.getenv("LLM_OLLAMA_CHEAP", "llama3.2:3b")
        self._smart = smart or os.getenv("LLM_OLLAMA_SMART", "llama3.2:70b")
        self._host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")

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
        _ = cache_system  # n/a on Ollama
        payload: dict = {
            "model": self._model_for(tier),
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if schema is not None:
            payload["format"] = "json"
            payload["messages"][0]["content"] += (
                "\n\nReturn a single JSON object matching this schema:\n"
                + json.dumps(schema.model_json_schema())
            )

        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{self._host}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        content = data.get("message", {}).get("content", "") or ""
        if schema is None:
            return content
        return schema.model_validate(json.loads(content))
