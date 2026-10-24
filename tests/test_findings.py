from decimal import Decimal

import pytest

from invoice_audit.findings import build_findings, is_possible_transposition, value_mismatch
from invoice_audit.procedures.cutoff import run_cutoff_testing
from invoice_audit.procedures.main_testing import run_main_testing
from tests.conftest import index, make_line, make_record


def test_value_mismatch_text_with_transposition():
    check = value_mismatch("net", Decimal("1243.50"), Decimal("1234.50"), "GBP")
    assert check.explanation == (
        "Invoice net £1,243.50 does not agree to ledger net £1,234.50 (difference £9.00). "
        "The difference is divisible by 9, a possible transposition."
    )
    assert check.suggested_action == "Obtain explanation and correct posting if needed."
    assert check.amount_impact == Decimal("9.00")


def test_value_mismatch_without_transposition():
    check = value_mismatch("net", Decimal("612.35"), Decimal("612.34"), "GBP")
    assert "transposition" not in check.explanation
    assert "(difference £0.01)" in check.explanation


@pytest.mark.parametrize(
    ("difference", "expected"),
    [("9.00", True), ("270.00", True), ("0.09", True), ("-0.18", True), ("0.01", False), ("0", False), ("10", False)],
)
def test_transposition_rule(difference, expected):
    assert is_possible_transposition(Decimal(difference)) is expected


def test_findings_are_numbered_main_then_cutoff_then_extraction(cfg):
    main_bad = make_record(invoice_date="2025-02-15", addressed_to="Calder Mill Catering Ltd")
    main_rows = run_main_testing([main_bad, make_record()], index(make_line()), {}, cfg)
    cut = make_record(test="cutoff", invoice_number="NOPE", invoice_date="2026-03-20",
                      service_period_start="2026-03-01", service_period_end="2026-03-31",
                      period_basis="explicit_period")  # fmt: skip
    cutoff_rows = run_cutoff_testing([cut], {}, {}, cfg)
    statement = make_record(document_type="statement")
    findings = build_findings(main_rows, cutoff_rows, [main_bad, statement])

    assert [f.ref for f in findings] == ["EX-001", "EX-002", "EX-003", "EX-004"]
    assert [(f.test, f.issue_type) for f in findings] == [
        ("Main", "Date outside FY"),
        ("Main", "Wrong addressee"),
        ("Cut-off", "Possible unrecorded liability"),
        ("Extraction", "Not an invoice"),
    ]
    assert findings[0].test_ref == "MT-001"
    assert findings[0].file == "doc_001.pdf"
    assert findings[0].supplier == "Lumen Print & Design Ltd"
    assert main_rows[0].finding_refs == ["EX-001", "EX-002"]
    assert main_rows[1].finding_refs == []
    assert cutoff_rows[0].P.finding_ref == "EX-003"
    assert all(f.explanation and f.suggested_action for f in findings)


def test_every_exception_or_review_check_gets_a_ref(cfg):
    record = make_record(confidence={"invoice_number": "low"})
    rows = run_main_testing([record], index(make_line()), {}, cfg)
    findings = build_findings(rows, [], [])
    assert len(findings) == 1  # one cause, one finding
    row = rows[0]
    for check in row.checks:
        if check.status in ("exception", "review"):
            assert check.finding_ref == "EX-001"


def test_multiple_invoices_extraction_finding(cfg):
    record = make_record(multiple_invoices_detected=True)
    findings = build_findings([], [], [record])
    assert findings[0].issue_type == "Multiple invoices in file"
    assert findings[0].status == "review"
