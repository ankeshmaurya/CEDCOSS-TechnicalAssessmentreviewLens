ALLOWED_SENTIMENTS = {"positive", "neutral", "negative"}
ALLOWED_TOPICS = {
    "quality",
    "delivery",
    "price",
    "packaging",
    "support",
    "size_fit",
    "other",
}


def validate_analysis(obj: object) -> tuple[bool, dict | None, str | None]:
    if not isinstance(obj, dict):
        return False, None, "analysis must be an object"

    sentiment = obj.get("sentiment")
    if type(sentiment) is not str or sentiment not in ALLOWED_SENTIMENTS:
        return False, None, "invalid sentiment"

    topics = obj.get("topics")
    if not isinstance(topics, list) or not topics:
        return False, None, "invalid topics"
    if any(type(topic) is not str or topic not in ALLOWED_TOPICS for topic in topics):
        return False, None, "invalid topics"

    summary = obj.get("summary")
    if type(summary) is not str or not summary.strip():
        return False, None, "invalid summary"

    needs_reply = obj.get("needs_reply")
    if type(needs_reply) is not bool:
        return False, None, "invalid needs_reply"

    cleaned = {
        "sentiment": sentiment,
        "topics": list(topics),
        "summary": summary.strip(),
        "needs_reply": needs_reply,
    }
    return True, cleaned, None
