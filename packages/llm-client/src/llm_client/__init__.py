"""Provider-switching LLM client.

One interface, four adapters (Anthropic / OpenAI / Ollama / fake), selected by
the ``LLM_PROVIDER`` env var. Two tiers (``cheap`` / ``smart``) map to concrete
models per adapter. Structured output is passed as a Pydantic model class;
each adapter converts it to its provider's preferred shape (Anthropic
``tool_use``, OpenAI ``response_format=json_schema``, Ollama JSON mode).

Callers see one function::

    from llm_client import complete

    text = await complete(
        system="...",
        messages=[{"role": "user", "content": "hi"}],
        tier="cheap",
    )

    obj = await complete(
        system="...",
        messages=[...],
        schema=MyPydanticModel,
        tier="smart",
        cache_system=True,
    )

Tests use the fake adapter::

    from llm_client.fake_adapter import set_responses
    set_responses(["yes"])
"""

from llm_client._interface import Message, Tier, complete, get_adapter, set_provider

__all__ = ["Message", "Tier", "complete", "get_adapter", "set_provider"]
