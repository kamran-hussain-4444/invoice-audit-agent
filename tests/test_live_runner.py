"""Live runner and full pipeline with a fake Claude client (offline, free)."""

import json

import pytest

from invoice_audit.config import load_config
from invoice_audit.discovery import discover
from invoice_audit.extraction.cache import ExtractionCache, cache_key
from invoice_audit.extraction.live import Job, run_live
from invoice_audit.extraction.requests import make_template
from invoice_audit.loaders import read_bytes
from invoice_audit.pipeline import DryRun, FatalError, run_pipeline
from tests.conftest import EXAMPLE_RUN, ROOT
from tests.fake_claude import FakeClient

ANSWER_KEY = json.loads((ROOT / "data" / "synthetic" / "answer_key.json").read_text(encoding="utf-8"))


@pytest.fixture
def run_cfg(tmp_path):
    cfg = load_config(EXAMPLE_RUN, base_dir=ROOT)
    cfg.ai.cache_path = tmp_path / "cache.sqlite"
    cfg.ai.max_workers = 4
    return cfg


def jobs_for(cfg, folder, test):
    template = make_template(cfg)
    documents = discover(folder, test).documents
    return [Job(d, cache_key(read_bytes(d), d.email_context, template)) for d in documents], template


def test_one_failure_does_not_stop_the_others(run_cfg):
    jobs, template = jobs_for(run_cfg, run_cfg.inputs.cutoff_folder, "cutoff")
    victim = jobs[3].document.display_name
    client = FakeClient(fail_on={victim})
    seen = []
    results = run_live(jobs, client, template, run_cfg, ExtractionCache(run_cfg.ai.cache_path), seen.append)
    assert len(results) == len(jobs) == len(seen)  # progress reached the total
    failed = [r for r in results if r.outcome == "failed"]
    assert [r.document.display_name for r in failed] == [victim]
    assert "simulated API failure" in failed[0].reason
    assert [r.document.doc_id for r in results] == [j.document.doc_id for j in jobs]  # original order kept


def test_failures_are_not_cached(run_cfg):
    jobs, template = jobs_for(run_cfg, run_cfg.inputs.cutoff_folder, "cutoff")
    cache = ExtractionCache(run_cfg.ai.cache_path)
    run_live(jobs[:2], FakeClient(fail_on={jobs[0].document.display_name}), template, run_cfg, cache)
    assert cache.get(jobs[0].cache_key) is None
    assert cache.get(jobs[1].cache_key) is not None


def test_full_pipeline_with_fake_claude_then_all_cache_hits(run_cfg):
    client = FakeClient()
    first = run_pipeline(run_cfg, mode="live", client=client)
    assert first.stats.live_calls == 62  # 60 invoices + statement + blurry; corrupt PDF never reaches the API
    assert first.stats.cache_hits == 0
    statuses = {r.source.display_name: r.status for r in first.records}
    assert statuses["corrupt_file.pdf"] == "failed"
    assert statuses["old_format.doc"] == "excluded"
    assert statuses["supplier_statement.pdf"] == "excluded"
    assert statuses["blurry_receipt.jpg"] == "needs_review"

    # Every planted error and clean control comes out as expected through the real pipeline.
    rows = {r.record.source.display_name: r for r in [*first.main_rows, *first.cutoff_rows]}
    for item in ANSWER_KEY["invoices"]:
        name = item["file"].split("/", 1)[1]
        name = f"{name} › {item['attachment']}" if item["attachment"] else name
        name = f"{name} (email body)" if item["format"] == "email_body" else name
        assert rows[name].overall == item["expected"]["overall"], (item["invoice_id"], item["planted_errors"])

    second_client = FakeClient()
    second = run_pipeline(run_cfg, mode="live", client=second_client)
    assert second_client.calls == []  # zero API calls
    assert second.stats.cache_hits == 62
    assert second.stats.mode == "cache only"
    assert [f.explanation for f in second.findings] == [f.explanation for f in first.findings]


def test_dry_run_makes_no_calls(run_cfg):
    client = FakeClient()
    result = run_pipeline(run_cfg, dry_run=True, client=client)
    assert isinstance(result, DryRun)
    assert client.calls == []
    assert result.new == 62  # 63 documents minus the corrupt PDF, which the dry run's loader check catches
    assert result.skipped == 2  # corrupt PDF + legacy .doc
    assert result.mode == "batch"  # 62 uncached > threshold 50


def test_missing_api_key_is_fatal_only_when_needed(run_cfg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("invoice_audit.pipeline.load_dotenv", lambda: None)
    with pytest.raises(FatalError, match="ANTHROPIC_API_KEY"):
        run_pipeline(run_cfg, mode="live", limit=1)
    assert isinstance(run_pipeline(run_cfg, dry_run=True), DryRun)  # no key needed for a dry run


def test_limit(run_cfg):
    client = FakeClient()
    result = run_pipeline(run_cfg, mode="live", limit=2, client=client)
    assert result.stats.documents == 4  # 2 per folder
