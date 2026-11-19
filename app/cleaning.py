import csv
import hashlib
import html
import io
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass
class CleaningResult:
    valid: list[dict]
    skipped: list[dict]
    duplicates: list[dict]
    stats: dict


def _clean_whitespace(text: str) -> str:
    return " ".join(text.split())


def _strip_html(text: str) -> str:
    parser = _HTMLTextParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        text = html.unescape(text)
        return text
    return html.unescape(" ".join(parser.parts))


def _parse_rating(value: object) -> int | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        rating = int(text)
    except (TypeError, ValueError):
        return None

    if 1 <= rating <= 5:
        return rating
    return None


def _text_hash(text: str) -> str:
    normalised = unicodedata.normalize("NFC", text)
    normalised = _clean_whitespace(normalised).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _review_id(row: dict, row_number: int) -> str:
    value = row.get("review_id")
    if value is None:
        return f"row_{row_number}"
    review_id = str(value).strip()
    return review_id if review_id else f"row_{row_number}"


def clean_reviews(csv_bytes: bytes) -> CleaningResult:
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text, newline=""))

    valid: list[dict] = []
    skipped: list[dict] = []
    duplicates: list[dict] = []
    seen_hashes: dict[str, str] = {}
    total_rows = 0

    for row_number, row in enumerate(reader, start=2):
        if not isinstance(row, dict):
            continue

        total_rows += 1
        review_id = _review_id(row, row_number)

        if None in row:
            skipped.append({
                "review_id": review_id,
                "reason": "malformed_row",
            })
            continue

        raw_text = row.get("review_text")
        if raw_text is None:
            skipped.append({
                "review_id": review_id,
                "reason": "empty_text",
            })
            continue

        review_text = _strip_html(str(raw_text))
        review_text = _clean_whitespace(review_text)

        if not review_text:
            skipped.append({
                "review_id": review_id,
                "reason": "empty_text",
            })
            continue

        text_hash = _text_hash(review_text)
        duplicate_of = seen_hashes.get(text_hash)
        if duplicate_of is not None:
            duplicates.append({
                "review_id": review_id,
                "duplicate_of": duplicate_of,
            })
            continue

        seen_hashes[text_hash] = review_id
        valid.append({
            "review_id": review_id,
            "product": _clean_whitespace(str(row.get("product") or "")),
            "rating": _parse_rating(row.get("rating")),
            "date": _clean_whitespace(str(row.get("date") or "")),
            "review_text": review_text,
            "text_hash": text_hash,
        })

    stats = {
        "total": total_rows,
        "valid": len(valid),
        "skipped": len(skipped),
        "duplicates": len(duplicates),
    }
    return CleaningResult(
        valid=valid,
        skipped=skipped,
        duplicates=duplicates,
        stats=stats,
    )
