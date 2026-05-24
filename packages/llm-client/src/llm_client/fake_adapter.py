"""Fake adapter for tests.

Pre-canned responses are pushed in via ``set_responses``. Each ``complete()``
call pops the next one off the queue.

A pre-canned response can be:

* a ``str`` — returned as-is when ``schema is None``.
* a ``dict`` or ``BaseModel`` — validated against the call's ``schema`` and
  returned as a model instance.
* a callable ``(request) -> response`` for tests that want to assert on the
  call shape.

The fake intentionally fails loudly when the queue is empty — tests should
say exactly what the model would have returned.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from llm_client._interface import Message, Tier


Canned = str | dict | BaseModel | Callable[[dict], Any]
_responses: list[Canned] = []
_calls: list[dict] = []


def set_responses(responses: list[Canned]) -> None:
    """Replace the queue. Use at the start of each test."""
    _responses.clear()
    _responses.extend(responses)
    _calls.clear()


def calls() -> list[dict]:
    """Return the recorded call requests, oldest first."""
    return list(_calls)


class FakeAdapter:
    name = "fake"

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
        request = {
            "system": system,
            "messages": list(messages),
            "schema": schema.__name__ if schema is not None else None,
            "tier": tier,
            "cache_system": cache_system,
            "max_tokens": max_tokens,
        }
        _calls.append(request)
        if not _responses:
            raise AssertionError(
                "fake_adapter queue empty — call set_responses([...]) in your test"
            )
        raw = _responses.pop(0)
        if callable(raw) and not isinstance(raw, BaseModel):
            raw = raw(request)
        if schema is None:
            if isinstance(raw, str):
                return raw
            raise AssertionError(
                f"fake_adapter: schema is None but canned response is {type(raw)!r}"
            )
        if isinstance(raw, BaseModel):
            return raw
        if isinstance(raw, dict):
            return schema.model_validate(raw)
        raise AssertionError(
            f"fake_adapter: unsupported canned response type {type(raw)!r}"
        )
