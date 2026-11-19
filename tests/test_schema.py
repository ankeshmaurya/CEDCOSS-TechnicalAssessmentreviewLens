from app.schema import validate_analysis


def test_valid_analysis() -> None:
    ok, cleaned, error = validate_analysis({
        "sentiment": "positive",
        "topics": ["quality", "price"],
        "summary": "The product is comfortable and reasonably priced.",
        "needs_reply": False,
    })

    assert ok is True
    assert error is None
    assert cleaned is not None


def test_bad_sentiment() -> None:
    ok, cleaned, error = validate_analysis({
        "sentiment": "happy",
        "topics": ["quality"],
        "summary": "Good quality.",
        "needs_reply": False,
    })

    assert (ok, cleaned, error) == (False, None, "invalid sentiment")


def test_empty_topics() -> None:
    ok, cleaned, error = validate_analysis({
        "sentiment": "neutral",
        "topics": [],
        "summary": "No clear opinion.",
        "needs_reply": False,
    })

    assert (ok, cleaned, error) == (False, None, "invalid topics")


def test_unknown_topic() -> None:
    ok, cleaned, error = validate_analysis({
        "sentiment": "negative",
        "topics": ["quality", "warranty"],
        "summary": "The warranty is missing.",
        "needs_reply": True,
    })

    assert (ok, cleaned, error) == (False, None, "invalid topics")


def test_non_boolean_needs_reply() -> None:
    ok, cleaned, error = validate_analysis({
        "sentiment": "negative",
        "topics": ["support"],
        "summary": "Support has not replied.",
        "needs_reply": "true",
    })

    assert (ok, cleaned, error) == (False, None, "invalid needs_reply")


def test_missing_summary() -> None:
    ok, cleaned, error = validate_analysis({
        "sentiment": "negative",
        "topics": ["quality"],
        "needs_reply": True,
    })

    assert (ok, cleaned, error) == (False, None, "invalid summary")
