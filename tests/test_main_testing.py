from datetime import date
from decimal import Decimal

import pytest

from invoice_audit.procedures.main_testing import run_main_testing, value_tested
from tests.conftest import index, make_line, make_record


def run_one(cfg, record, current_lines=None, post_ye_lines=()):
    current_lines = [make_line()] if current_lines is None else current_lines
    (row,) = run_main_testing([record], index(*current_lines), index(*post_ye_lines), cfg)
    return row


def test_clean_invoice_passes_everything(cfg):
    row = run_one(cfg, make_record())
    assert [c.status for c in (row.A, row.D, row.E, row.C)] == ["pass"] * 4
    assert row.overall == "pass"
    assert row.ledger_line.row_number == 2
    assert row.difference == Decimal("0.00")


# ---------------------------------------------------------------- A: value


def test_penny_difference_is_exception(cfg):
    row = run_one(cfg, make_record(net_amount=612.35, vat_amount=122.47, gross_amount=734.82),
                  [make_line(net=Decimal("612.34"))])  # fmt: skip
    assert row.A.status == "exception"
    assert row.difference == Decimal("0.01")
    assert row.overall == "exception"


def test_tolerance_is_configurable(cfg):
    cfg.matching.value_tolerance = Decimal("0.05")
    row = run_one(cfg, make_record(), [make_line(net=Decimal("999.97"))])
    assert row.A.status == "pass"


def test_gross_posted_in_net_column(cfg):
    row = run_one(cfg, make_record(), [make_line(net=Decimal("1200.00"))])
    assert row.A.status == "exception"
    assert row.A.amount_impact == Decimal("200.00")


def test_ap_listing_compares_gross(cfg):
    cfg.inputs.ledger_type = "ap_listing"
    row = run_one(cfg, make_record(), [make_line(net=Decimal("1.00"), gross=Decimal("1200.00"))])
    assert row.A.status == "pass"
    assert row.ledger_amount == Decimal("1200.00")


def test_fx_agrees_on_original_amount(cfg):
    record = make_record(currency="USD", net_amount=500, vat_amount=0, gross_amount=500)
    line = make_line(currency="USD", net=Decimal("395.10"), original_amount=Decimal("500.00"))
    row = run_one(cfg, record, [line])
    assert row.A.status == "pass"


def test_fx_disagrees(cfg):
    record = make_record(currency="EUR", net_amount=3200, vat_amount=0, gross_amount=3200)
    line = make_line(currency="EUR", net=Decimal("2600.00"), original_amount=Decimal("3020.00"))
    row = run_one(cfg, record, [line])
    assert row.A.status == "exception"
    assert "€3,200.00" in row.A.explanation and "€3,020.00" in row.A.explanation
    assert row.A.amount_impact is None  # not a sterling amount


def test_fx_missing_original_amount_is_review(cfg):
    record = make_record(currency="EUR", net_amount=3200, vat_amount=0, gross_amount=3200)
    row = run_one(cfg, record, [make_line(currency="EUR", original_amount=None)])
    assert row.A.status == "review"
    assert row.A.detail == "FX: auditor to agree"


def test_currency_mismatch_is_exception(cfg):
    record = make_record(currency="EUR", net_amount=3200, vat_amount=0, gross_amount=3200)
    row = run_one(cfg, record, [make_line(currency="GBP")])
    assert row.A.status == "exception"


def test_weak_amounts_give_review_not_exception(cfg):
    record = make_record(confidence={"amounts": "low"})
    row = run_one(cfg, record, [make_line(net=Decimal("5.00"))])  # would be an exception if trusted
    assert row.A.status == "review"
    assert row.A.issue_type == "Low-confidence extraction"


# ---------------------------------------------------------------- D: date in FY


@pytest.mark.parametrize(
    ("invoice_date", "status"),
    [
        ("2025-04-01", "pass"),  # first day of FY
        ("2026-03-31", "pass"),  # last day of FY
        ("2025-03-31", "exception"),  # one day before
        ("2026-04-01", "exception"),  # one day after
        ("2025-02-15", "exception"),
    ],
)
def test_date_boundaries(cfg, invoice_date, status):
    row = run_one(cfg, make_record(invoice_date=invoice_date))
    assert row.D.status == status


def test_date_explanations_say_which_side(cfg):
    before = run_one(cfg, make_record(invoice_date="2025-02-15")).D
    assert before.explanation == "Invoice dated 15/02/2025 is before the financial year starting 01/04/2025."
    after = run_one(cfg, make_record(invoice_date="2026-05-12")).D
    assert "after the financial year ending 31/03/2026" in after.explanation


def test_weak_date_is_review(cfg):
    row = run_one(cfg, make_record(invoice_date="2025-02-15", confidence={"invoice_date": "low"}))
    assert row.D.status == "review"
    assert row.D.explanation == "Could not reliably read invoice date (low confidence). Date test not performed."


# ---------------------------------------------------------------- E: addressee


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("BRACKENFIELD ENGINEERING LIMITED", "pass"),
        ("Brackenfield Engineering Ltd.", "pass"),
        ("Brackenfield Precision", "pass"),
        ("Brackenfeild Engineering Ltd", "pass"),
        ("Brackenfield Holdings Ltd", "exception"),
        ("Calder Mill Catering Ltd", "exception"),
        ("Mr J Brackenfield", "exception"),
        ("Brackenfield Engineering Group", "review"),
    ],
)
def test_addressee(cfg, name, status):
    assert run_one(cfg, make_record(addressed_to=name)).E.status == status


def test_group_company_text(cfg):
    e = run_one(cfg, make_record(addressed_to="Brackenfield Holdings Ltd")).E
    assert e.explanation == (
        "Invoice is addressed to Brackenfield Holdings Ltd (group company), not Brackenfield Engineering Ltd."
    )


def test_missing_addressee_is_review(cfg):
    assert run_one(cfg, make_record(addressed_to=None)).E.status == "review"


# ---------------------------------------------------------------- C: classification


def test_misclassification(cfg):
    record = make_record(description="Exhibition stand hire and brochures", suggested_category="Marketing")
    line = make_line(nominal_code="6800", nominal_account="Administrative expenses", category="Administrative expenses")
    row = run_one(cfg, record, [line])
    assert row.C.status == "exception"
    assert row.C.explanation == (
        "Posted to 6800 Administrative expenses, but the description ('Exhibition stand hire and brochures') "
        "suggests Marketing."
    )
    assert row.C.ai_reasoning == "Printed marketing material."


def test_unmapped_code_is_review(cfg):
    row = run_one(cfg, make_record(), [make_line(nominal_code="7777", category=None)])
    assert row.C.status == "review"


def test_weak_description_is_review(cfg):
    row = run_one(cfg, make_record(suggested_category="Utilities", confidence={"description": "low"}))
    assert row.C.status == "review"


def test_medium_description_still_tested(cfg):
    row = run_one(cfg, make_record(suggested_category="Utilities", confidence={"description": "medium"}))
    assert row.C.status == "exception"


# ---------------------------------------------------------------- ledger match


def test_no_match_is_exception_and_checks_na(cfg):
    row = run_one(cfg, make_record(invoice_number="INV-9999"))
    assert row.match.status == "exception"
    assert [c.status for c in (row.A, row.D, row.E, row.C)] == ["n/a"] * 4
    assert row.overall == "exception"
    assert row.match.explanation == "No ledger entry found for invoice number INV-9999."


def test_no_match_mentions_post_ye_ledger(cfg):
    later = make_line(invoice_number="INV-9999", source="post_ye", posting_date=date(2026, 4, 14))
    row = run_one(cfg, make_record(invoice_number="INV-9999"), post_ye_lines=[later])
    assert "(found in post-year-end ledger, posted 14/04/2026)" in row.match.explanation


def test_spacing_and_case_still_match(cfg):
    row = run_one(cfg, make_record(invoice_number="INV2231"), [make_line(invoice_number="inv 2231")])
    assert row.match.status == "pass"
    assert row.overall == "pass"


def test_multiple_matches_is_review(cfg):
    row = run_one(cfg, make_record(), [make_line(), make_line(row_number=3)])
    assert row.match.status == "review"
    assert "appears 2 times" in row.match.explanation
    assert row.overall == "review"


def test_weak_invoice_number_reviews_ledger_checks_only(cfg):
    row = run_one(cfg, make_record(invoice_date="2025-02-15", confidence={"invoice_number": "low"}))
    assert row.match.status == "review"
    assert row.A.status == "review" and row.C.status == "review"
    assert row.D.status == "exception"  # date doesn't need the ledger, so still tested
    assert row.E.status == "pass"


def test_excluded_and_failed_records_are_not_tested(cfg):
    excluded = make_record(document_type="statement")
    rows = run_main_testing([excluded, make_record()], index(make_line()), {}, cfg)
    assert len(rows) == 1
    assert rows[0].ref == "MT-001"


def test_value_tested_sums_matched_ledger_amounts(cfg):
    records = [make_record(), make_record(invoice_number="INV-2"), make_record(invoice_number="NOPE")]
    lines = [make_line(), make_line(invoice_number="INV-2", net=Decimal("50.00"))]
    rows = run_main_testing(records, index(*lines), {}, cfg)
    assert value_tested(rows, cfg) == Decimal("1050.00")
