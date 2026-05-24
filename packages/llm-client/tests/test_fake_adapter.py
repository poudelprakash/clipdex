"""End-to-end behavior tests using the fake adapter — no network."""

import pytest
from pydantic import BaseModel

import llm_client
from llm_client.fake_adapter import calls, set_responses


@pytest.fixture(autouse=True)
def _use_fake():
    llm_client.set_provider("fake")
    yield


@pytest.mark.asyncio
async def test_text_response():
    set_responses(["yes"])
    out = await llm_client.complete(
        system="reply yes/no",
        messages=[{"role": "user", "content": "ok?"}],
        tier="cheap",
    )
    assert out == "yes"


class Sentiment(BaseModel):
    label: str
    score: float


@pytest.mark.asyncio
async def test_schema_response_from_dict():
    set_responses([{"label": "positive", "score": 0.9}])
    out = await llm_client.complete(
        system="classify",
        messages=[{"role": "user", "content": "great!"}],
        schema=Sentiment,
        tier="smart",
    )
    assert isinstance(out, Sentiment)
    assert out.label == "positive"
    assert out.score == 0.9


@pytest.mark.asyncio
async def test_schema_response_from_model():
    set_responses([Sentiment(label="neg", score=0.1)])
    out = await llm_client.complete(
        system="classify",
        messages=[{"role": "user", "content": "bad"}],
        schema=Sentiment,
    )
    assert isinstance(out, Sentiment)
    assert out.label == "neg"


@pytest.mark.asyncio
async def test_call_recording():
    set_responses(["a", "b"])
    await llm_client.complete(system="s", messages=[{"role": "user", "content": "1"}])
    await llm_client.complete(system="s", messages=[{"role": "user", "content": "2"}])
    recorded = calls()
    assert len(recorded) == 2
    assert recorded[0]["messages"][0]["content"] == "1"
    assert recorded[1]["messages"][0]["content"] == "2"


@pytest.mark.asyncio
async def test_empty_queue_raises():
    set_responses([])
    with pytest.raises(AssertionError, match="queue empty"):
        await llm_client.complete(
            system="s", messages=[{"role": "user", "content": "hi"}]
        )
