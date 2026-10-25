"""Batch mode with a fake Batches API (offline, free)."""

import json

import pytest

from invoice_audit.config import load_config
from invoice_audit.discovery import discover
from invoice_audit.extraction.batch import PendingBatches, _Item, chunk, pending_path, run_batch
from invoice_audit.extraction.cache import ExtractionCache, cache_key
from invoice_audit.extraction.cost import usage_cost
from invoice_audit.extraction.live import Job
from invoice_audit.extraction.requests import make_template
from invoice_audit.loaders import read_bytes
from invoice_audit.pipeline import run_pipeline
from tests.conftest import EXAMPLE_RUN, ROOT
from tests.e2e_checks import score
from tests.fake_claude import FakeClient

ANSWER_KEY = json.loads((ROOT / "data" / "synthetic" / "answer_key.json").read_text(encoding="utf-8"))
NO_SLEEP = lambda seconds: None  # noqa: E731


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Batch polling waits 15 s between checks; the fake API needs no waiting."""
    monkeypatch.setattr("invoice_audit.extraction.batch.time.sleep", NO_SLEEP)


@pytest.fixture
def run_cfg(tmp_path):
    cfg = load_config(EXAMPLE_RUN, base_dir=ROOT)
    cfg.ai.cache_path = tmp_path / "cache.sqlite"
    return cfg


def cutoff_jobs(cfg):
    template = make_template(cfg)
    documents = discover(cfg.inputs.cutoff_folder, "cutoff").documents
    return [Job(d, cache_key(read_bytes(d), d.email_context, template)) for d in documents], template


def item(size: int) -> _Item:
    return _Item(job=None, params={}, size=size)


def test_chunking_by_bytes_and_count():
    assert [len(c) for c in chunk([item(40)] * 5, max_bytes=100, max_requests=10)] == [2, 2, 1]
    assert [len(c) for c in chunk([item(1)] * 7, max_bytes=100, max_requests=3)] == [3, 3, 1]
    assert [len(c) for c in chunk([item(500)], max_bytes=100, max_requests=3)] == [1]  # oversized item alone
    assert chunk([]) == []


def test_results_matched_by_custom_id_not_order(run_cfg):
    jobs, template = cutoff_jobs(run_cfg)
    client = FakeClient()
    results = run_batch(jobs, client, template, run_cfg, ExtractionCache(run_cfg.ai.cache_path), sleep=NO_SLEEP)
    assert len(client.batches.created) == 1
    assert client.calls == []  # nothing went to the live endpoint
    for job, result in zip(jobs, results, strict=True):
        assert result.document.doc_id == job.document.doc_id
        assert result.outcome == "extracted"
        assert result.mode == "batch"
    # The fake returns results in reverse order; check one invoice landed on the right document.
    by_name = {r.document.display_name: r for r in results}
    truth = next(i for i in ANSWER_KEY["invoices"] if i["file"] == "cutoff_sample/doc_101.docx")["truth"]
    assert by_name["doc_101.docx"].invoice.invoice_number == truth["invoice_number"]


def test_errored_items_retried_live(run_cfg):
    jobs, template = cutoff_jobs(run_cfg)
    client = FakeClient()
    client.batches.errored = {"doc_101.docx"}
    results = run_batch(jobs, client, template, run_cfg, ExtractionCache(run_cfg.ai.cache_path), sleep=NO_SLEEP)
    assert client.calls == ["doc_101.docx"]
    retried = next(r for r in results if r.document.display_name == "doc_101.docx")
    assert retried.outcome == "extracted" and retried.mode == "live"


def test_errored_then_live_failure_is_failed(run_cfg):
    jobs, template = cutoff_jobs(run_cfg)
    client = FakeClient(fail_on={"doc_101.docx"})
    client.batches.errored = {"doc_101.docx"}
    results = run_batch(jobs, client, template, run_cfg, ExtractionCache(run_cfg.ai.cache_path), sleep=NO_SLEEP)
    failed = [r for r in results if r.outcome == "failed"]
    assert [r.document.display_name for r in failed] == ["doc_101.docx"]


def test_pending_file_written_before_waiting_and_resumed_without_resubmitting(run_cfg):
    client = FakeClient()
    client.batches.interrupt_on_retrieve = True
    run_cfg.tests.run = ["cutoff"]
    with pytest.raises(KeyboardInterrupt):
        run_pipeline(run_cfg, mode="batch", client=client)
    pending = PendingBatches(pending_path(run_cfg)).load()
    assert [p["batch_id"] for p in pending] == ["msgbatch_001"]
    assert len(pending[0]["docs"]) == 25

    # Next run: the batch has finished in the meantime. It must be collected, not paid for again.
    client.batches.interrupt_on_retrieve = False
    result = run_pipeline(run_cfg, mode="batch", client=client)
    assert len(client.batches.created) == 1  # no second submission
    assert client.calls == []
    assert result.stats.batch_calls == 25
    assert PendingBatches(pending_path(run_cfg)).load() == []


def test_full_pipeline_in_batch_mode(run_cfg):
    client = FakeClient()
    result = run_pipeline(run_cfg, mode="auto", client=client)  # 62 uncached > 50 → batch
    assert result.stats.batch_calls == 62
    assert result.stats.live_calls == 0
    assert result.stats.mode == "batch"
    # Batch pricing: exactly half of the live price for the same tokens.
    assert result.stats.cost_usd == usage_cost(result.stats.tokens, run_cfg.ai.pricing) / 2
    overall = {r.record.source.display_name: r.overall for r in [*result.main_rows, *result.cutoff_rows]}
    assert overall["blurry_receipt.jpg"] == "review"
    exceptions = sum(1 for r in [*result.main_rows, *result.cutoff_rows] if r.overall == "exception")
    expected = sum(1 for i in ANSWER_KEY["invoices"] if i["expected"]["overall"] == "exception")
    assert exceptions == expected
    # The scorer used by the recorded/live end-to-end tests gives a perfect run a clean bill.
    assert score(result) == {"missed": [], "wrong_kind": [], "unexpected_clean": []}
