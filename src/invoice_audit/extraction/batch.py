"""Batch mode (PLAN 9.5): the Message Batches API, half price, for big runs.

1. Build one request per uncached document (custom_id = doc_id, same params as live mode).
2. Split into chunks well under the API limits.
3. Submit each chunk and write its batch id to .cache/pending_batches.json straight away, so an interrupted
   run (Ctrl+C, laptop asleep) picks the batch up again next time instead of paying twice.
4. Poll every 15 s until it ends.
5. Collect results by custom_id (they come back in any order); cache successes; retry anything that
   errored, expired or was cancelled once in live mode.
6. Remove the batch from the pending file.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from invoice_audit.config import RunConfig
from invoice_audit.extraction.cache import ExtractionCache
from invoice_audit.extraction.live import DocResult, Job, run_live
from invoice_audit.extraction.prompt import PROMPT_VERSION
from invoice_audit.extraction.requests import (
    ExtractionError,
    RequestTemplate,
    build_params,
    parse_invoice,
    read_message,
)
from invoice_audit.loaders import LoaderError, NeedsReviewWithoutExtraction, load

log = logging.getLogger(__name__)

MAX_BATCH_BYTES = 150 * 1024 * 1024  # API limit is 256 MB
MAX_BATCH_REQUESTS = 5000  # API limit is 100,000
POLL_SECONDS = 15


def config_fingerprint(template: RequestTemplate) -> str:
    return f"{template.model}|{template.effort}|v{PROMPT_VERSION}|{template.schema_hash}"


def pending_path(cfg: RunConfig) -> Path:
    return cfg.ai.cache_path.parent / "pending_batches.json"


class PendingBatches:
    """The pending_batches.json file: batches submitted but not yet collected."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Could not read %s; ignoring it", self.path)
            return []

    def _save(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        temporary.replace(self.path)  # atomic, so a crash mid-write can't corrupt the file

    def add(self, entry: dict) -> None:
        self._save([*self.load(), entry])

    def remove(self, batch_id: str) -> None:
        self._save([e for e in self.load() if e["batch_id"] != batch_id])


@dataclass
class _Item:
    job: Job
    params: dict
    size: int


def chunk(items: list[_Item], max_bytes: int = MAX_BATCH_BYTES, max_requests: int = MAX_BATCH_REQUESTS) -> list[list]:
    chunks: list[list[_Item]] = []
    current: list[_Item] = []
    size = 0
    for item in items:
        if current and (size + item.size > max_bytes or len(current) >= max_requests):
            chunks.append(current)
            current, size = [], 0
        current.append(item)
        size += item.size
    if current:
        chunks.append(current)
    return chunks


def _wait(client, batch_ids: list[str], on_poll, sleep) -> None:
    remaining = set(batch_ids)
    while remaining:
        done = 0
        for batch_id in sorted(remaining):
            batch = client.messages.batches.retrieve(batch_id)
            counts = batch.request_counts
            done += counts.succeeded + counts.errored + counts.canceled + counts.expired
            if batch.processing_status == "ended":
                remaining.discard(batch_id)
        if on_poll:
            on_poll(done)
        if remaining:
            (sleep or time.sleep)(POLL_SECONDS)  # looked up at call time, so tests can patch it


def _collect(client, entry: dict, cache: ExtractionCache, template: RequestTemplate) -> tuple[dict, list[str]]:
    """Results of one ended batch: {doc_id: DocResult-ish tuple}, plus doc_ids that need a live retry."""
    docs = entry["docs"]  # custom_id → {"cache_key", "name"}
    collected: dict[str, tuple] = {}
    retry: list[str] = []
    for result in client.messages.batches.results(entry["batch_id"]):
        custom_id = result.custom_id
        if custom_id not in docs:
            continue
        if result.result.type != "succeeded":
            log.warning("Batch item %s %s", docs[custom_id]["name"], result.result.type)
            retry.append(custom_id)
            continue
        try:
            text, usage = read_message(result.result.message)
            invoice = parse_invoice(text)
        except ExtractionError as e:
            log.warning("Batch item %s unusable: %s", docs[custom_id]["name"], e)
            retry.append(custom_id)
            continue
        cache.put(docs[custom_id]["cache_key"], docs[custom_id]["name"], template.model, text, usage, "batch")
        collected[custom_id] = (invoice, usage)
    missing = [c for c in docs if c not in collected and c not in retry]
    return collected, retry + missing


def collect_pending(client, template: RequestTemplate, cfg: RunConfig, cache: ExtractionCache,
                    on_poll: Callable[[int], None] | None = None, sleep=None) -> dict[str, tuple]:  # fmt: skip
    """Finish batches left over from an interrupted run. Returns {cache_key: (invoice, usage)}.

    Everything collected is cached too, so documents no longer in this run still aren't paid for twice.
    """
    store = PendingBatches(pending_path(cfg))
    entries = [e for e in store.load() if e.get("config_fingerprint") == config_fingerprint(template)]
    if not entries:
        return {}
    log.info("Resuming %d pending batch(es)", len(entries))
    _wait(client, [e["batch_id"] for e in entries], on_poll, sleep)
    collected: dict[str, tuple] = {}
    for entry in entries:
        results, _ = _collect(client, entry, cache, template)
        for custom_id, value in results.items():
            collected[entry["docs"][custom_id]["cache_key"]] = value
        store.remove(entry["batch_id"])
    return collected


def run_batch(
    jobs: list[Job],
    client,
    template: RequestTemplate,
    cfg: RunConfig,
    cache: ExtractionCache,
    on_progress: Callable[[DocResult], None] | None = None,
    on_poll: Callable[[int], None] | None = None,
    sleep=None,
) -> list[DocResult]:
    results: dict[str, DocResult] = {}
    items: list[_Item] = []
    for job in jobs:
        try:
            payload = load(job.document, cfg)
        except NeedsReviewWithoutExtraction as e:
            results[job.document.doc_id] = DocResult(job.document, "needs_review", reason=str(e), mode="batch")
            continue
        except LoaderError as e:
            results[job.document.doc_id] = DocResult(job.document, "failed", reason=str(e), mode="batch")
            continue
        items.append(_Item(job, build_params(template, payload), payload.approx_bytes))

    store = PendingBatches(pending_path(cfg))
    by_id = {item.job.document.doc_id: item.job for item in items}
    entries = []
    for group in chunk(items):
        batch = client.messages.batches.create(
            requests=[{"custom_id": item.job.document.doc_id, "params": item.params} for item in group]
        )
        entry = {
            "batch_id": batch.id,
            "submitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "config_fingerprint": config_fingerprint(template),
            "docs": {item.job.document.doc_id: {"cache_key": item.job.cache_key, "name": item.job.document.display_name}
                     for item in group},
        }  # fmt: skip
        store.add(entry)  # persist BEFORE waiting: an interrupted run resumes this batch instead of resubmitting
        entries.append(entry)
        log.info("Submitted batch %s with %d request(s)", batch.id, len(group))

    # Documents that failed to load never reach the API but still count towards the progress total.
    already_done = len(results)
    progress = (lambda done: on_poll(done + already_done)) if on_poll else None
    _wait(client, [e["batch_id"] for e in entries], progress, sleep)

    retry_ids: list[str] = []
    for entry in entries:
        collected, retry = _collect(client, entry, cache, template)
        for doc_id, (invoice, usage) in collected.items():
            result = DocResult(by_id[doc_id].document, "extracted", invoice, usage, mode="batch")
            results[doc_id] = result
            if on_progress:
                on_progress(result)
        retry_ids += retry
        store.remove(entry["batch_id"])

    if retry_ids:
        log.info("Retrying %d document(s) in live mode", len(retry_ids))
        for result in run_live([by_id[i] for i in retry_ids], client, template, cfg, cache, on_progress):
            results[result.document.doc_id] = result

    return [results[job.document.doc_id] for job in jobs if job.document.doc_id in results]
