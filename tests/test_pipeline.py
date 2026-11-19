import asyncio
import json

from app.llm import RateLimitError
from app.pipeline import analyse_batch, call_with_backoff, chunk_reviews


def valid_response(review_id: str) -> dict:
    return {
        "results": [{
            "id": review_id,
            "sentiment": "negative",
            "topics": ["quality"],
            "summary": "The product stopped working.",
            "needs_reply": True,
        }],
    }


def test_retry_on_invalid_json_then_success() -> None:
    calls = 0

    async def fake_llm(messages: list[dict]) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"choices": [{"message": {"content": "not json"}}]}
        return valid_response("R012")

    async def run() -> tuple[list[dict], dict]:
        return await analyse_batch([{
            "review_id": "R012",
            "product": "Earbuds",
            "rating": 1,
            "date": "2026-10-03",
            "review_text": "The left earbud stopped working.",
        }], fake_llm)

    results, metrics = asyncio.run(run())

    assert calls == 2
    assert results[0]["status"] == "ok"
    assert metrics["retries"] == 1


def test_analysis_failed_after_two_bad_responses() -> None:
    async def fake_llm(messages: list[dict]) -> dict:
        return {"choices": [{"message": {"content": "not json"}}]}

    async def run() -> tuple[list[dict], dict]:
        return await analyse_batch([{
            "review_id": "R001",
            "product": "Test",
            "rating": 3,
            "date": "2026-10-01",
            "review_text": "It is okay.",
        }], fake_llm)

    results, _ = asyncio.run(run())

    assert results[0]["status"] == "analysis_failed"


def test_backoff_on_429_then_success() -> None:
    calls = 0
    sleeps = []

    async def fake_llm(messages: list[dict]) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RateLimitError("2")
        return valid_response("R001")

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def run() -> dict:
        return await call_with_backoff(
            [{"role": "user", "content": "test"}],
            fake_llm,
            fake_sleep,
            jitter_func=lambda low, high: 0.0,
        )

    response = asyncio.run(run())

    assert calls == 2
    assert sleeps == [2.0]
    assert response["results"][0]["id"] == "R001"


def test_batches_are_size_5(monkeypatch) -> None:
    reviews = [{"review_id": f"R{number}"} for number in range(1, 12)]

    batches = chunk_reviews(reviews)

    assert [len(batch) for batch in batches] == [5, 5, 1]
