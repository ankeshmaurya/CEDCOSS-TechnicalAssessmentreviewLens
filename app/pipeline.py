import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable

from app.config import settings
from app.cache import get_many, put
from app.llm import ApiError, RateLimitError, ServerError, call_groq
from app.prompts import build_messages
from app.schema import validate_analysis


LLMFunction = Callable[[list[dict]], Awaitable[dict]]
SleepFunction = Callable[[float], Awaitable[None]]


def chunk_reviews(reviews: list[dict]) -> list[list[dict]]:
    size = settings.batch_size
    return [reviews[index:index + size] for index in range(0, len(reviews), size)]


async def call_with_backoff(
    messages: list[dict],
    llm_func: LLMFunction = call_groq,
    sleep_func: SleepFunction = asyncio.sleep,
    jitter_func: Callable[[float, float], float] = random.uniform,
    metrics: dict | None = None,
) -> dict:
    for attempt in range(settings.max_retries + 1):
        try:
            if metrics is not None:
                metrics["ai_calls"] = metrics.get("ai_calls", 0) + 1
            return await llm_func(messages)
        except (RateLimitError, ServerError) as error:
            if attempt >= settings.max_retries:
                raise
            if metrics is not None:
                metrics["retries"] = metrics.get("retries", 0) + 1

            if isinstance(error, RateLimitError) and error.retry_after:
                try:
                    delay = float(error.retry_after)
                except ValueError:
                    delay = 1.0 * (2 ** attempt)
            else:
                delay = 1.0 * (2 ** attempt)

            delay += jitter_func(0.0, 0.25)
            await sleep_func(delay)


def _extract_content(response: dict) -> object:
    if "results" in response:
        return response

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("invalid JSON response")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("invalid JSON response")

    content = message.get("content")
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("invalid JSON response")

    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("invalid JSON response") from error


def _parse_results(response: dict) -> tuple[list[dict], str | None]:
    try:
        payload = _extract_content(response)
    except ValueError as error:
        return [], str(error)

    if not isinstance(payload, dict):
        return [], "invalid JSON response"
    results = payload.get("results")
    if not isinstance(results, list):
        return [], "missing results"
    return results, None


async def analyse_batch(
    batch: list[dict],
    llm_func: LLMFunction = call_groq,
    sleep_func: SleepFunction = asyncio.sleep,
) -> tuple[list[dict], dict]:
    messages = build_messages([
        {"id": review["review_id"], "text": review["review_text"]}
        for review in batch
    ])
    backoff_metrics = {"ai_calls": 0, "retries": 0}

    try:
        first_response = await call_with_backoff(
            messages,
            llm_func,
            sleep_func,
            metrics=backoff_metrics,
        )
    except (RateLimitError, ServerError, ApiError) as error:
        return [
            _failed_review(review, str(error))
            for review in batch
        ], backoff_metrics

    raw_results, parse_error = _parse_results(first_response)
    valid_by_id: dict[str, dict] = {}
    failure_reasons: dict[str, str] = {}
    needs_retry: list[dict] = []

    for review in batch:
        review_id = str(review["review_id"])
        matches = [
            item for item in raw_results
            if isinstance(item, dict) and str(item.get("id")) == review_id
        ]
        if parse_error or not matches:
            needs_retry.append(review)
            failure_reasons[review_id] = parse_error or "missing result"
            continue

        ok, cleaned, error = validate_analysis(matches[0])
        if ok and cleaned is not None:
            valid_by_id[review_id] = cleaned
        else:
            needs_retry.append(review)
            failure_reasons[review_id] = error or "invalid result"

    if needs_retry:
        retry_messages = build_messages([
            {"id": review["review_id"], "text": review["review_text"]}
            for review in needs_retry
        ])
        try:
            retry_response = await call_with_backoff(
                retry_messages,
                llm_func,
                sleep_func,
                metrics=backoff_metrics,
            )
        except (RateLimitError, ServerError, ApiError) as error:
            return [
                _failed_review(review, str(error))
                if str(review["review_id"]) not in valid_by_id
                else _ok_review(review, valid_by_id[str(review["review_id"])])
                for review in batch
            ], backoff_metrics

        retry_results, retry_error = _parse_results(retry_response)
        for review in needs_retry:
            review_id = str(review["review_id"])
            matches = [
                item for item in retry_results
                if isinstance(item, dict) and str(item.get("id")) == review_id
            ]
            if retry_error or not matches:
                failure_reasons[review_id] = retry_error or "missing result"
                continue
            ok, cleaned, error = validate_analysis(matches[0])
            if ok and cleaned is not None:
                valid_by_id[review_id] = cleaned
            else:
                failure_reasons[review_id] = error or "invalid result"

    output: list[dict] = []
    for review in batch:
        review_id = str(review["review_id"])
        if review_id in valid_by_id:
            output.append(_ok_review(review, valid_by_id[review_id]))
        else:
            output.append(_failed_review(
                review,
                failure_reasons.get(review_id, "analysis_failed"),
            ))
    backoff_metrics["retries"] += 1 if needs_retry else 0
    return output, backoff_metrics


def _ok_review(review: dict, analysis: dict) -> dict:
    return {
        "id": review["review_id"],
        "product": review.get("product"),
        "rating": review.get("rating"),
        "date": review.get("date"),
        "text": review["review_text"],
        "status": "ok",
        "sentiment": analysis["sentiment"],
        "topics": analysis["topics"],
        "summary": analysis["summary"],
        "needs_reply": analysis["needs_reply"],
        "from_cache": False,
    }


def _failed_review(review: dict, error: str) -> dict:
    return {
        "id": review["review_id"],
        "product": review.get("product"),
        "rating": review.get("rating"),
        "date": review.get("date"),
        "text": review["review_text"],
        "status": "analysis_failed",
        "sentiment": None,
        "topics": None,
        "summary": None,
        "needs_reply": None,
        "from_cache": False,
        "error": error,
    }


async def run_pipeline(
    cleaning_result,
    llm_func: LLMFunction = call_groq,
    sleep_func: SleepFunction = asyncio.sleep,
    db_path: str | None = None,
) -> dict:
    started = time.perf_counter()
    valid = list(cleaning_result.valid)
    duplicate_items = cleaning_result.duplicates

    duplicate_map = {
        str(item["review_id"]): str(item["duplicate_of"])
        for item in duplicate_items
    }
    results: list[dict] = []
    ai_calls = 0
    retries = 0
    cache_hits = 0
    unique_hashes = list(dict.fromkeys(
        str(review["text_hash"])
        for review in valid
    ))
    cached_by_hash = get_many(unique_hashes, db_path)

    uncached: list[dict] = []
    cached_results: dict[str, dict] = {}
    for review in valid:
        text_hash = str(review["text_hash"])
        cached = cached_by_hash.get(text_hash)
        if cached is not None:
            cached_result = _ok_review(review, {
                "sentiment": cached["sentiment"],
                "topics": cached["topics"],
                "summary": cached["summary"],
                "needs_reply": cached["needs_reply"],
            })
            cached_result["from_cache"] = True
            cached_results[text_hash] = cached_result
            continue
        uncached.append(review)

    results.extend(cached_results.values())
    cache_hits += len(cached_results)

    for batch in chunk_reviews(uncached):
        batch_results, batch_metrics = await analyse_batch(
            batch,
            llm_func,
            sleep_func,
        )
        ai_calls += batch_metrics["ai_calls"]
        retries += batch_metrics["retries"]
        for batch_result in batch_results:
            if batch_result["status"] == "ok":
                original_review = next(
                    review for review in batch
                    if str(review["review_id"]) == str(batch_result["id"])
                )
                put(str(original_review["text_hash"]), batch_result, db_path)
        results.extend(batch_results)

    results_by_id = {str(item["id"]): item for item in results}
    duplicate_details = getattr(cleaning_result, "duplicate_details", None) or []
    duplicate_details_by_id = {
        str(item["review_id"]): item
        for item in duplicate_details
    }
    for duplicate in duplicate_items:
        duplicate_id = str(duplicate["review_id"])
        original_id = duplicate_map[duplicate_id]
        original = results_by_id.get(original_id)
        if original is None:
            continue

        duplicate_review = duplicate_details_by_id.get(duplicate_id)
        if duplicate_review is None:
            duplicate_review = {
                "review_id": duplicate_id,
                "product": original["product"],
                "rating": original["rating"],
                "date": original["date"],
                "review_text": original["text"],
            }

        duplicate_result = _ok_review(duplicate_review, {
            "sentiment": original["sentiment"],
            "topics": original["topics"],
            "summary": original["summary"],
            "needs_reply": original["needs_reply"],
        })
        duplicate_result["from_cache"] = True
        duplicate_result["status"] = (
            original["status"]
            if original["status"] == "analysis_failed"
            else "ok"
        )
        if duplicate_result["status"] == "ok":
            duplicate_result["from_cache"] = True
        else:
            duplicate_result["from_cache"] = False
        results.append(duplicate_result)
        if duplicate_result["status"] == "ok":
            cache_hits += 1

    failed = sum(item["status"] == "analysis_failed" for item in results)
    return {
        "reviews": results,
        "metrics": {
            "ai_calls": ai_calls,
            "retries": retries,
            "failed": failed,
            "cache_hits": cache_hits,
            "total_seconds": round(time.perf_counter() - started, 6),
        },
    }
