from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.cleaning import clean_reviews
from app.insights import build_themes, generate_reply
from app.pipeline import run_pipeline


app = FastAPI(title="ReviewLens")
LATEST_RUN: dict | None = None
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(StarletteHTTPException)
async def json_http_exception_handler(
    request: Request,
    exception: StarletteHTTPException,
) -> JSONResponse:
    return await http_exception_handler(request, exception)


@app.exception_handler(Exception)
async def json_unhandled_exception_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="A CSV file is required")

    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    cleaning_result = clean_reviews(csv_bytes)
    pipeline_result = await run_pipeline(cleaning_result)

    global LATEST_RUN
    LATEST_RUN = {
        "cleaning": cleaning_result,
        "pipeline": pipeline_result,
    }

    return {
        "stats": cleaning_result.stats,
        "metrics": pipeline_result["metrics"],
        "reviews": pipeline_result["reviews"],
        "message": "Upload analysed successfully",
    }


def _expected_sentiment(rating: object) -> str | None:
    if type(rating) is not int:
        return None
    if rating in (1, 2):
        return "negative"
    if rating == 3:
        return "neutral"
    if rating in (4, 5):
        return "positive"
    return None


@app.get("/api/dashboard")
async def dashboard() -> dict:
    if LATEST_RUN is None:
        return {
            "cards": {
                "total_analysed": 0,
                "total": 0,
                "positive_percent": 0,
                "neutral_percent": 0,
                "negative_percent": 0,
                "positive_pct": 0,
                "neutral_pct": 0,
                "negative_pct": 0,
                "needs_reply": 0,
                "needs_reply_count": 0,
                "analysis_failed": 0,
                "analysis_failed_count": 0,
                "skipped": 0,
                "duplicates": 0,
            },
            "top_complaints": [],
            "top_praises": [],
            "reviews": [],
            "products": [],
            "metrics": {
                "ai_calls": 0,
                "cache_hits": 0,
                "total_seconds": 0,
                "retries": 0,
                "failed": 0,
            },
            "agreement_percentage": 0,
        }

    cleaning_result = LATEST_RUN["cleaning"]
    pipeline_result = LATEST_RUN["pipeline"]
    reviews = pipeline_result["reviews"]
    analysed = [
        review for review in reviews
        if review.get("status") == "ok"
    ]
    total = len(analysed)
    counts = {
        sentiment: sum(
            review.get("sentiment") == sentiment
            for review in analysed
        )
        for sentiment in ("positive", "neutral", "negative")
    }
    positive_pct = round(counts["positive"] * 100 / total, 1) if total else 0
    neutral_pct = round(counts["neutral"] * 100 / total, 1) if total else 0
    negative_pct = round(counts["negative"] * 100 / total, 1) if total else 0

    agreement_count = 0
    agreement_reviews = 0
    enriched_reviews = []
    for review in reviews:
        enriched = dict(review)
        expected = _expected_sentiment(review.get("rating"))
        actual = review.get("sentiment")
        if expected is None or actual is None:
            mismatch = None
        else:
            agreement_reviews += 1
            mismatch = expected != actual
            if not mismatch:
                agreement_count += 1
        enriched["rating_mismatch"] = mismatch
        enriched_reviews.append(enriched)

    agreement_percentage = (
        round(agreement_count * 100 / agreement_reviews, 1)
        if agreement_reviews else 0
    )

    top_complaints, complaints_cached = await build_themes(
        enriched_reviews,
        "negative",
        db_path=None,
    )
    top_praises, praises_cached = await build_themes(
        enriched_reviews,
        "positive",
        db_path=None,
    )

    metrics = dict(pipeline_result["metrics"])
    metrics["cache_hits"] = (
        metrics.get("cache_hits", 0)
        + int(complaints_cached)
        + int(praises_cached)
    )

    products: dict[str, int] = {}
    for review in analysed:
        product = str(review.get("product") or "Unknown")
        products[product] = products.get(product, 0) + 1
    product_list = [
        {"product": product, "count": count}
        for product, count in sorted(products.items())
    ]

    return {
        "cards": {
            "total_analysed": total,
            "total": total,
            "positive_percent": positive_pct,
            "neutral_percent": neutral_pct,
            "negative_percent": negative_pct,
            "positive_pct": positive_pct,
            "neutral_pct": neutral_pct,
            "negative_pct": negative_pct,
            "needs_reply": sum(
                review.get("needs_reply") is True
                for review in analysed
            ),
            "needs_reply_count": sum(
                review.get("needs_reply") is True
                for review in analysed
            ),
            "analysis_failed": sum(
                review.get("status") == "analysis_failed"
                for review in reviews
            ),
            "analysis_failed_count": sum(
                review.get("status") == "analysis_failed"
                for review in reviews
            ),
            "skipped": cleaning_result.stats["skipped"],
            "duplicates": cleaning_result.stats["duplicates"],
        },
        "top_complaints": top_complaints,
        "top_praises": top_praises,
        "reviews": enriched_reviews,
        "products": product_list,
        "metrics": metrics,
        "agreement_percentage": agreement_percentage,
        "agreement_pct": agreement_percentage,
    }


@app.post("/api/reviews/{review_id}/reply")
async def review_reply(review_id: str) -> dict:
    if LATEST_RUN is None:
        raise HTTPException(status_code=404, detail="Review not found")

    reviews = LATEST_RUN["pipeline"]["reviews"]
    review = next(
        (
            item for item in reviews
            if str(item["id"]) == review_id
        ),
        None,
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.get("needs_reply") is not True:
        raise HTTPException(
            status_code=400,
            detail="This review does not need a reply",
        )

    reply = await generate_reply(review)
    return {"review_id": review_id, "reply": reply}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_file)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
