"""The one user-facing function plus the adapter selection."""

from __future__ import annotations

import os
from typing import Literal, Protocol, TypedDict, TypeVar

from pydantic import BaseModel

Tier = Literal["cheap", "smart"]
T = TypeVar("T", bound=BaseModel)


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class Adapter(Protocol):
    name: str

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: type[BaseModel] | None,
        tier: Tier,
        cache_system: bool,
        max_tokens: int,
    ) -> BaseModel | str: ...


# Single registry; tests can override via set_provider().
_current_name: str | None = None
_current: Adapter | None = None


def set_provider(name: str) -> None:
    """Force a specific adapter, ignoring ``LLM_PROVIDER``.

    Useful for tests; also handy when one call site wants a different provider
    than the default (rare — usually you just leave the env var alone).
    """
    global _current_name, _current
    _current_name = name
    _current = _build(name)


def get_adapter() -> Adapter:
    global _current, _current_name
    desired = _current_name or os.getenv("LLM_PROVIDER", "anthropic").lower()
    if _current is None or (_current_name is None and _current.name != desired):
        _current = _build(desired)
        _current_name = None  # follow env var on subsequent calls
    return _current


def _build(name: str) -> Adapter:
    name = name.lower()
    if name == "anthropic":
        from llm_client.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter()
    if name == "openai":
        from llm_client.openai_adapter import OpenAIAdapter

        return OpenAIAdapter()
    if name == "ollama":
        from llm_client.ollama_adapter import OllamaAdapter

        return OllamaAdapter()
    if name == "fake":
        from llm_client.fake_adapter import FakeAdapter

        return FakeAdapter()
    raise ValueError(f"unknown LLM_PROVIDER={name!r}")


async def complete(
    *,
    system: str,
    messages: list[Message],
    schema: type[BaseModel] | None = None,
    tier: Tier = "smart",
    cache_system: bool = False,
    max_tokens: int = 1024,
) -> BaseModel | str:
    """Provider-agnostic completion.

    * ``schema=None`` → returns the model's text content as ``str``.
    * ``schema=SomeModel`` → returns an instance of that Pydantic model,
      with the JSON validated against its schema.
    * ``cache_system=True`` → adapter wraps the system block in a cache
      directive when the provider supports it (Anthropic only today).
    """
    adapter = get_adapter()
    return await adapter.complete(
        system=system,
        messages=messages,
        schema=schema,
        tier=tier,
        cache_system=cache_system,
        max_tokens=max_tokens,
    )
