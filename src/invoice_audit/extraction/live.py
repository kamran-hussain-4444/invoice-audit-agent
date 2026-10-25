"""Live mode (PLAN 9.4): parallel Messages API calls with a progress bar.

Each document runs in its own future and any error becomes a failed result for that document only.
Results are cached the moment they arrive, so a crash halfway through loses nothing.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal

from invoice_audit.config import RunConfig
from invoice_audit.extraction.cache import ExtractionCache
from invoice_audit.extraction.requests import (
    RETRY_MAX_TOKENS,
    ExtractionError,
    OutputTooLong,
    RequestTemplate,
    build_params,
    parse_invoice,
    read_message,
)
from invoice_audit.loaders import LoaderError, NeedsReviewWithoutExtraction, load
from invoice_audit.models import ExtractedInvoice, SourceDocument, TokenUsage

log = logging.getLogger(__name__)

# Server-side refusal fallback (claude-api skill default for this model family; Claude API only, not Batches).
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Job:
    document: SourceDocument
    cache_key: str


@dataclass
class DocResult:
    document: SourceDocument
    outcome: Literal["extracted", "failed", "needs_review"]
    invoice: ExtractedInvoice | None = None
    usage: TokenUsage | None = None
    reason: str | None = None
    mode: Literal["live", "batch"] = "live"


def call_claude(client, template: RequestTemplate, payload) -> tuple[str, TokenUsage]:
    """One request; if the answer was cut off, retry once (streamed, bigger limit)."""
    extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    message = client.beta.messages.create(**build_params(template, payload), **extra)
    try:
        return read_message(message)
    except OutputTooLong:
        log.info("Retrying with max_tokens=%s", RETRY_MAX_TOKENS)
    with client.beta.messages.stream(**build_params(template, payload, RETRY_MAX_TOKENS), **extra) as stream:
        message = stream.get_final_message()
    try:
        return read_message(message)
    except OutputTooLong:
        raise ExtractionError("Model output was too long even with a larger limit") from None


def extract_document(client, job: Job, template: RequestTemplate, cfg: RunConfig, cache: ExtractionCache) -> DocResult:
    document = job.document
    try:
        payload = load(document, cfg)
    except NeedsReviewWithoutExtraction as e:
        return DocResult(document, "needs_review", reason=str(e))
    except LoaderError as e:
        return DocResult(document, "failed", reason=str(e))
    text, usage = call_claude(client, template, payload)
    invoice = parse_invoice(text)
    cache.put(job.cache_key, document.display_name, template.model, text, usage, "live")
    return DocResult(document, "extracted", invoice, usage)


def run_live(
    jobs: list[Job],
    client,
    template: RequestTemplate,
    cfg: RunConfig,
    cache: ExtractionCache,
    on_progress: Callable[[DocResult], None] | None = None,
) -> list[DocResult]:
    """Extract every job in parallel. Never raises for a single document's failure."""
    results: list[DocResult] = []
    with ThreadPoolExecutor(max_workers=cfg.ai.max_workers) as pool:
        futures = {pool.submit(extract_document, client, job, template, cfg, cache): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                result = future.result()
            except ExtractionError as e:
                log.warning("%s: %s", job.document.display_name, e)
                result = DocResult(job.document, "failed", reason=str(e))
            except Exception as e:  # API errors after the SDK's own retries, network, anything else
                log.exception("Extraction failed for %s", job.document.display_name)
                result = DocResult(job.document, "failed", reason=f"{type(e).__name__}: {e}")
            results.append(result)
            if on_progress:
                on_progress(result)
    order = {job.document.doc_id: i for i, job in enumerate(jobs)}
    return sorted(results, key=lambda r: order[r.document.doc_id])
