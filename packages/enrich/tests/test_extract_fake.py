"""enrich.extract.extract_chunk via the fake adapter — no network needed."""

import pytest

import llm_client
from clipdex_enrich.extract import extract_chunk
from clipdex_enrich.router import is_substantive
from clipdex_schema import Extraction
from llm_client.fake_adapter import set_responses


@pytest.fixture(autouse=True)
def _use_fake():
    llm_client.set_provider("fake")
    yield


@pytest.mark.asyncio
async def test_extract_chunk_returns_validated_model():
    set_responses(
        [
            {
                "guests": [
                    {
                        "name": "Bibhusan Bista",
                        "role": "Co-founder",
                        "company": "Young Innovations",
                        "confidence": 0.92,
                    }
                ],
                "topics": [
                    {"name": "fundraising in Nepal", "segment_ids": [1, 2], "confidence": 0.8}
                ],
                "quotes": [],
            }
        ]
    )
    out = await extract_chunk("[1] hello\n[2] world")
    assert isinstance(out, Extraction)
    assert out.guests[0].name == "Bibhusan Bista"
    assert out.topics[0].segment_ids == [1, 2]


@pytest.mark.asyncio
async def test_is_substantive_yes():
    set_responses(["yes"])
    assert await is_substantive("real conversation") is True


@pytest.mark.asyncio
async def test_is_substantive_no():
    set_responses(["no"])
    assert await is_substantive("[sponsor read]") is False
