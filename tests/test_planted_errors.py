"""HEADLINE TEST: every planted error is caught and every clean invoice passes.

Builds perfect extractions from the answer key's truth, then runs the real ledger loading, Test 1,
Test 2 and findings against the committed synthetic ledgers. This proves the audit logic; the AI's
reading accuracy is tested separately (recorded and live end-to-end tests).
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_audit.config import load_config
from invoice_audit.findings import build_findings
from invoice_audit.ledger import load_ledger
from invoice_audit.matching import index_ledger
from invoice_audit.models import ExtractionRecord, SourceDocument
from invoice_audit.procedures.cutoff import run_cutoff_testing
from invoice_audit.procedures.main_testing import run_main_testing
from invoice_audit.validation import validate_extraction
from tests.conftest import EXAMPLE_RUN, ROOT, invoice_from_truth

DATA = ROOT / "data" / "synthetic"
ANSWER_KEY = json.loads((DATA / "answer_key.json").read_text(encoding="utf-8"))
INVOICES = {item["invoice_id"]: item for item in ANSWER_KEY["invoices"]}
TODAY = date(2026, 10, 1)


def to_record(item: dict, invoice_id: str, low_confidence: tuple[str, ...] = ()) -> ExtractionRecord:
    invoice = invoice_from_truth(item["truth"], low_confidence)
    outcome = validate_extraction(invoice, today=TODAY)
    name = item["file"] + (f" › {item['attachment']}" if item.get("attachment") else "")
    source = SourceDocument(
        doc_id=invoice_id, test=item.get("test", "main"), file_path=DATA / item["file"], display_name=name, kind="pdf"
    )
    return ExtractionRecord(source, outcome.status, outcome.reasons, outcome.weak_fields, invoice)


@pytest.fixture(scope="module")
def results():
    cfg = load_config(EXAMPLE_RUN, base_dir=ROOT, check_files=True)
    current = index_ledger(load_ledger(cfg.inputs.current_ledger, "current", cfg))
    post_ye = index_ledger(load_ledger(cfg.inputs.post_ye_ledger, "post_ye", cfg))
    records = {iid: to_record(item, iid) for iid, item in INVOICES.items()}
    main = run_main_testing([r for r in records.values() if r.source.test == "main"], current, post_ye, cfg)
    cutoff = run_cutoff_testing([r for r in records.values() if r.source.test == "cutoff"], current, post_ye, cfg)
    findings = build_findings(main, cutoff, list(records.values()))
    rows = {row.record.source.doc_id: row for row in [*main, *cutoff]}
    return {"rows": rows, "findings": findings, "records": records}


def test_answer_key_has_every_planted_error_once():
    planted = [e for item in INVOICES.values() for e in item["planted_errors"]]
    expected = [f"E{n:02d}" for n in range(1, 17)] + [f"C{n:02d}" for n in range(1, 13)]
    assert sorted(planted) == sorted(expected)


@pytest.mark.parametrize("invoice_id", sorted(INVOICES))
def test_invoice_gives_expected_result(results, invoice_id):
    item = INVOICES[invoice_id]
    row = results["rows"][invoice_id]
    expected = item["expected"]
    label = f"{invoice_id} {item['planted_errors'] or 'clean'} {item['file']}"
    actual_checks = {name: getattr(row, name).status for name in expected["checks"]}
    assert actual_checks == expected["checks"], label
    assert row.overall == expected["overall"], label
    if item["test"] == "cutoff":
        assert row.recorded_in == expected["recorded_in"], label
        if expected["suggested_adjustment"]:
            assert row.suggested_adjustment == Decimal(expected["suggested_adjustment"]), label


def test_clean_invoices_raise_no_findings(results):
    clean = {iid for iid, item in INVOICES.items() if not item["planted_errors"]}
    flagged = {row.record.source.doc_id for row in results["rows"].values() if row.finding_refs}
    assert clean & flagged == set()


def test_every_planted_error_has_a_finding_with_explanation(results):
    by_ref = {f.ref: f for f in results["findings"]}
    for iid, item in INVOICES.items():
        if item["planted_errors"]:
            refs = results["rows"][iid].finding_refs
            assert refs, iid
            assert all(by_ref[ref].explanation for ref in refs), iid


def test_extracted_records_are_all_ok(results):
    # Perfect extractions of real invoices must pass every validation rule (no false "needs review").
    bad = {iid: r.reasons for iid, r in results["records"].items() if r.status != "ok"}
    assert bad == {}


EDGE_CASES = {Path(item["file"]).name: item for item in ANSWER_KEY["edge_cases"]}


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
def test_edge_case_status(name):
    item = EDGE_CASES[name]
    if item["truth"] is None:
        pytest.skip("Decided by the file loaders (milestone M3), not by extracted data")
    record = to_record(item, name, tuple(item.get("low_confidence", ())))
    assert record.status == item["expected_status"]
