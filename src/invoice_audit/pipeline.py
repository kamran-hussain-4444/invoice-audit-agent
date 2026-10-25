"""Runs everything in order (PLAN section 7) and returns a RunResult.

ledgers (fail fast, before any API spend) → discover → cache lookup → extract the rest (live/batch)
→ validate → Test 1 / Test 2 → findings.
"""

import logging
import os
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from invoice_audit.config import RunConfig
from invoice_audit.discovery import discover
from invoice_audit.extraction.cache import ExtractionCache, cache_key
from invoice_audit.extraction.cost import estimate_cost, usage_cost
from invoice_audit.extraction.live import DocResult, Job, run_live
from invoice_audit.extraction.requests import ExtractionError, make_template, parse_invoice
from invoice_audit.findings import build_findings
from invoice_audit.ledger import load_ledger
from invoice_audit.loaders import LoaderError, NeedsReviewWithoutExtraction, load, read_bytes
from invoice_audit.matching import index_ledger
from invoice_audit.models import (
    CutoffTestRow,
    ExtractionRecord,
    Finding,
    MainTestRow,
    RunStats,
    SourceDocument,
    TokenUsage,
)
from invoice_audit.procedures.cutoff import run_cutoff_testing
from invoice_audit.procedures.main_testing import run_main_testing
from invoice_audit.validation import ALL_FIELDS, validate_extraction

log = logging.getLogger(__name__)


class FatalError(Exception):
    """Stops the whole run (exit code 1): missing API key, unusable mode, and so on."""


@dataclass
class DryRun:
    by_kind: Counter
    cached: int
    new: int
    skipped: int
    mode: str
    estimated_cost_usd: Decimal


@dataclass
class RunResult:
    cfg: RunConfig
    started_at: datetime
    records: list[ExtractionRecord]
    main_rows: list[MainTestRow]
    cutoff_rows: list[CutoffTestRow]
    findings: list[Finding]
    stats: RunStats
    log_path: Path | None = None
    workpaper_path: Path | None = None
    ledger_lines: dict[str, int] = field(default_factory=dict)

    @property
    def failed(self) -> list[ExtractionRecord]:
        return [r for r in self.records if r.status == "failed"]


def make_client():
    """The Anthropic client. Only created when there is something to extract (so dry runs need no key)."""
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise FatalError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and paste your key after "
            "ANTHROPIC_API_KEY= (get one at console.anthropic.com)."
        )
    import anthropic

    return anthropic.Anthropic(max_retries=4, timeout=120)  # SDK retries 429/5xx/connection errors


def record_from_invoice(document: SourceDocument, invoice, usage, from_cache: bool, mode) -> ExtractionRecord:
    outcome = validate_extraction(invoice)
    return ExtractionRecord(document, outcome.status, outcome.reasons, outcome.weak_fields, invoice, usage,
                            from_cache, mode)  # fmt: skip


def record_from_result(result: DocResult) -> ExtractionRecord:
    if result.outcome == "extracted":
        return record_from_invoice(result.document, result.invoice, result.usage, False, result.mode)
    if result.outcome == "needs_review":
        return ExtractionRecord(result.document, "needs_review", [result.reason], set(ALL_FIELDS))
    return ExtractionRecord(result.document, "failed", [result.reason or "Unknown error"])


def choose_mode(requested: str, uncached: int, threshold: int) -> str:
    if requested != "auto":
        return requested
    return "batch" if uncached > threshold else "live"


def run_pipeline(
    cfg: RunConfig,
    mode: str | None = None,
    use_cache: bool = True,
    limit: int | None = None,
    dry_run: bool = False,
    client=None,
    on_progress: Callable[[DocResult], None] | None = None,
    on_start: Callable[[int, str], None] | None = None,
) -> RunResult | DryRun:
    started = datetime.now()
    clock = time.monotonic()
    requested_mode = mode or cfg.ai.mode

    # 1. Ledgers first: a wrong ledger is fatal, and finding out costs nothing.
    current_lines = load_ledger(cfg.inputs.current_ledger, "current", cfg)
    post_ye_lines = load_ledger(cfg.inputs.post_ye_ledger, "post_ye", cfg) if cfg.inputs.post_ye_ledger else []
    current, post_ye = index_ledger(current_lines), index_ledger(post_ye_lines)

    # 2. Discover documents.
    folders = {"main": cfg.inputs.main_folder, "cutoff": cfg.inputs.cutoff_folder}
    documents: list[SourceDocument] = []
    records: dict[str, ExtractionRecord] = {}
    order: list[str] = []
    stats = RunStats()
    for test in cfg.tests.run:
        found = discover(folders[test], test, limit)
        stats.files_found += found.files_found
        for skipped in found.skipped:
            records[skipped.source.doc_id + test] = skipped
            order.append(skipped.source.doc_id + test)
        for document in found.documents:
            if document.doc_id in order:  # same file in both sample folders: ids must stay unique
                document.doc_id = f"{document.doc_id}-{test}"
            documents.append(document)
            order.append(document.doc_id)

    # 3. Cache lookup.
    template = make_template(cfg)
    cache = ExtractionCache(cfg.ai.cache_path)
    jobs: list[Job] = []
    for document in documents:
        try:
            key = cache_key(read_bytes(document), document.email_context, template)
        except LoaderError as e:
            records[document.doc_id] = ExtractionRecord(document, "failed", [str(e)])
            continue
        hit = cache.get(key) if use_cache else None
        if hit is not None:
            try:
                invoice = parse_invoice(hit.response_json)
            except ExtractionError:
                hit = None  # stale/odd cache entry: extract again
            else:
                records[document.doc_id] = record_from_invoice(document, invoice, None, True, "cache")
                stats.cache_hits += 1
                continue
        jobs.append(Job(document, key))

    if dry_run:
        # Also run the loaders, so unreadable files show up before any money is spent.
        unreadable = 0
        for job in list(jobs):
            try:
                load(job.document, cfg)
            except (LoaderError, NeedsReviewWithoutExtraction):
                unreadable += 1
                jobs.remove(job)
        chosen = choose_mode(requested_mode, len(jobs), cfg.ai.batch_threshold)
        return DryRun(
            by_kind=Counter(d.kind for d in documents),
            cached=stats.cache_hits,
            new=len(jobs),
            skipped=unreadable + sum(1 for r in records.values() if r.status in ("excluded", "failed")),
            mode=chosen if jobs else "none (all cached)",
            estimated_cost_usd=estimate_cost(len(jobs), cfg.ai.pricing, batch=chosen == "batch"),
        )
    chosen = choose_mode(requested_mode, len(jobs), cfg.ai.batch_threshold)

    # 4. Extract what isn't cached.
    if jobs:
        if chosen == "batch":
            raise FatalError("Batch mode is not available yet (milestone M6). Use --mode live.")
        client = client or make_client()
        if on_start:
            on_start(len(jobs), chosen)
        results = run_live(jobs, client, template, cfg, cache, on_progress)
        for result in results:
            records[result.document.doc_id] = record_from_result(result)
            if result.usage is not None:
                stats.live_calls += 1
                _add_usage(stats.tokens, result.usage)
                stats.cost_usd += usage_cost(result.usage, cfg.ai.pricing, batch=result.mode == "batch")

    ordered = [records[key] for key in order if key in records]
    stats.documents = len(documents)

    # 5. Audit tests (pure Python) and findings.
    main_rows = run_main_testing([r for r in ordered if r.source.test == "main"], current, post_ye, cfg)
    cutoff_rows = run_cutoff_testing([r for r in ordered if r.source.test == "cutoff"], current, post_ye, cfg)
    findings = build_findings(main_rows, cutoff_rows, ordered)
    stats.duration_seconds = time.monotonic() - clock
    return RunResult(cfg, started, ordered, main_rows, cutoff_rows, findings, stats,
                     ledger_lines={"current": len(current_lines), "post_ye": len(post_ye_lines)})  # fmt: skip


def _add_usage(total: TokenUsage, usage: TokenUsage) -> None:
    total.input_tokens += usage.input_tokens
    total.output_tokens += usage.output_tokens
    total.cache_read_tokens += usage.cache_read_tokens
    total.cache_creation_tokens += usage.cache_creation_tokens
