"""SQLite cache of successful extractions (PLAN 9.6), so re-running never pays twice.

The key covers only what changes Claude's answer: the document bytes, any email context, the model, effort,
prompt version and schema. Ledgers and engagement settings are not part of it, so re-testing against a
corrected ledger is free.
"""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from invoice_audit.extraction.prompt import PROMPT_VERSION
from invoice_audit.extraction.requests import RequestTemplate
from invoice_audit.models import TokenUsage

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS extractions (
    key TEXT PRIMARY KEY,
    doc_display_name TEXT,
    model TEXT,
    prompt_version TEXT,
    created_at TEXT,
    response_json TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    mode TEXT
)
"""


def cache_key(content: bytes, email_context: str | None, template: RequestTemplate) -> str:
    digest = hashlib.sha256()
    for part in (content, (email_context or "").encode("utf-8"), template.model.encode(), template.effort.encode(),
                 PROMPT_VERSION.encode(), template.schema_hash.encode()):  # fmt: skip
        digest.update(len(part).to_bytes(8, "big"))  # length prefix so parts can't run into each other
        digest.update(part)
    return digest.hexdigest()


@dataclass
class CachedExtraction:
    response_json: str
    usage: TokenUsage
    mode: str


class ExtractionCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.execute(SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection per call: safe from live mode's worker threads, and always closed
        (an open connection keeps the file locked on Windows)."""
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:  # commits on success, rolls back on error
                yield db
        finally:
            db.close()

    def get(self, key: str) -> CachedExtraction | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT response_json, input_tokens, output_tokens, cache_read_tokens, mode FROM extractions "
                "WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return CachedExtraction(row[0], TokenUsage(row[1] or 0, row[2] or 0, row[3] or 0), row[4] or "")

    def put(self, key: str, display_name: str, model: str, response_json: str, usage: TokenUsage, mode: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO extractions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, display_name, model, PROMPT_VERSION, datetime.now(UTC).isoformat(timespec="seconds"),
                 response_json, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, mode),
            )  # fmt: skip

    def stats(self) -> dict:
        with self._connect() as db:
            count, size = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(response_json)), 0) FROM extractions"
            ).fetchone()
            by_model = db.execute("SELECT model, prompt_version, COUNT(*) FROM extractions GROUP BY 1, 2").fetchall()
        return {"entries": count, "bytes": size, "by_model": by_model, "path": str(self.path)}

    def clear(self) -> int:
        with self._connect() as db:
            removed = db.execute("DELETE FROM extractions").rowcount
        return removed
