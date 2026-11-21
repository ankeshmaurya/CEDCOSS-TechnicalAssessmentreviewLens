import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings


def _cache_key(text_hash: str, prompt_version: str) -> str:
    return f"{prompt_version}:{text_hash}"


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_cache (
            text_hash TEXT PRIMARY KEY,
            prompt_version TEXT,
            result_json TEXT,
            created_at TEXT
        )
        """
    )
    return connection


def get_many(hashes: list[str], db_path: str | None = None) -> dict:
    from app.prompts import PROMPT_VERSION

    if not hashes:
        return {}

    connection = _connect(db_path)
    try:
        placeholders = ",".join("?" for _ in hashes)
        keyed_hashes = [
            _cache_key(text_hash, PROMPT_VERSION)
            for text_hash in hashes
        ]
        rows = connection.execute(
            f"""
            SELECT text_hash, result_json
            FROM analysis_cache
            WHERE text_hash IN ({placeholders})
            AND prompt_version = ?
            """,
            keyed_hashes + [PROMPT_VERSION],
        ).fetchall()
    finally:
        connection.close()

    found = {}
    for stored_key, result_json in rows:
        prefix = f"{PROMPT_VERSION}:"
        original_hash = stored_key[len(prefix):]
        found[original_hash] = json.loads(result_json)
    return found


def put(text_hash: str, result: dict, db_path: str | None = None) -> bool:
    if result.get("status") != "ok":
        return False

    from app.prompts import PROMPT_VERSION

    stored_key = _cache_key(text_hash, PROMPT_VERSION)
    result_json = json.dumps(result, ensure_ascii=False)
    created_at = datetime.now(UTC).isoformat()

    connection = _connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO analysis_cache
                (text_hash, prompt_version, result_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(text_hash) DO UPDATE SET
                prompt_version = excluded.prompt_version,
                result_json = excluded.result_json,
                created_at = excluded.created_at
            """,
            (stored_key, PROMPT_VERSION, result_json, created_at),
        )
        connection.commit()
    finally:
        connection.close()
    return True


def get_cache(key: str, db_path: str | None = None) -> dict | list | str | None:
    from app.prompts import PROMPT_VERSION

    connection = _connect(db_path)
    try:
        row = connection.execute(
            """
            SELECT result_json
            FROM analysis_cache
            WHERE text_hash = ? AND prompt_version = ?
            """,
            (_cache_key(key, PROMPT_VERSION), PROMPT_VERSION),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return json.loads(row[0])


def put_cache(
    key: str,
    value: dict | list | str,
    db_path: str | None = None,
) -> bool:
    from app.prompts import PROMPT_VERSION

    stored_key = _cache_key(key, PROMPT_VERSION)
    created_at = datetime.now(UTC).isoformat()
    connection = _connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO analysis_cache
                (text_hash, prompt_version, result_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(text_hash) DO UPDATE SET
                prompt_version = excluded.prompt_version,
                result_json = excluded.result_json,
                created_at = excluded.created_at
            """,
            (
                stored_key,
                PROMPT_VERSION,
                json.dumps(value, ensure_ascii=False),
                created_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return True
