import asyncio

from app.cache import get_many, put
from app.cleaning import clean_reviews
from app.pipeline import run_pipeline
import app.prompts as prompts


def valid_result() -> dict:
    return {
        "id": "R001",
        "product": "Test",
        "rating": 5,
        "date": "2026-10-01",
        "text": "Great product.",
        "status": "ok",
        "sentiment": "positive",
        "topics": ["quality"],
        "summary": "The product is excellent.",
        "needs_reply": False,
        "from_cache": False,
    }


def cleaning_result(csv_text: str):
    return clean_reviews(csv_text.encode("utf-8"))


def test_second_run_makes_zero_llm_calls(tmp_path) -> None:
    db_path = str(tmp_path / "cache.db")
    cleaned = cleaning_result(
        "review_id,rating,review_text\n"
        "R001,5,Great product.\n"
    )
    calls = 0

    async def fake_llm(messages: list[dict]) -> dict:
        nonlocal calls
        calls += 1
        return {
            "results": [{
                "id": "R001",
                "sentiment": "positive",
                "topics": ["quality"],
                "summary": "The product is excellent.",
                "needs_reply": False,
            }],
        }

    first = asyncio.run(run_pipeline(cleaned, fake_llm, db_path=db_path))
    second = asyncio.run(run_pipeline(cleaned, fake_llm, db_path=db_path))

    assert first["metrics"]["ai_calls"] == 1
    assert second["metrics"]["ai_calls"] == 0
    assert calls == 1
    assert second["reviews"][0]["from_cache"] is True


def test_failed_results_are_not_cached(tmp_path) -> None:
    db_path = str(tmp_path / "cache.db")

    assert put("hash-1", {
        "status": "analysis_failed",
        "sentiment": None,
    }, db_path) is False
    assert get_many(["hash-1"], db_path) == {}


def test_changing_prompt_version_misses_cache(tmp_path) -> None:
    db_path = str(tmp_path / "cache.db")
    original_version = prompts.PROMPT_VERSION

    put("hash-2", valid_result(), db_path)
    assert "hash-2" in get_many(["hash-2"], db_path)

    prompts.PROMPT_VERSION = "v2"
    try:
        assert get_many(["hash-2"], db_path) == {}
    finally:
        prompts.PROMPT_VERSION = original_version
