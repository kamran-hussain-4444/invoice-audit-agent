"""Every cell of the PLAN section 12 matrix, the apportionment maths and the fallback rule."""

from datetime import date
from decimal import Decimal

import pytest

from invoice_audit.procedures.cutoff import Period, day_split, run_cutoff_testing
from tests.conftest import index, make_line, make_record

YE = date(2026, 3, 31)

PERIODS = {
    "pre_ye": ("2026-03-01", "2026-03-31"),
    "post_ye": ("2026-04-01", "2026-04-30"),
    "spans": ("2026-01-01", "2026-12-31"),
}


def record_for(position: str, **changes):
    start, end = PERIODS[position]
    data = {
        "service_period_start": start,
        "service_period_end": end,
        "period_basis": "explicit_period",
        "invoice_date": "2026-03-25",
    }
    data.update(changes)
    return make_record(test="cutoff", **data)


def lines_for(recorded: str):
    current = [make_line(posting_date=date(2026, 3, 28))] if recorded in ("current", "both") else []
    post = [make_line(source="post_ye", posting_date=date(2026, 4, 10))] if recorded in ("post_ye", "both") else []
    return current, post


def run_one(cfg, record, recorded: str):
    current, post = lines_for(recorded)
    (row,) = run_cutoff_testing([record], index(*current), index(*post), cfg)
    return row


MATRIX = [
    ("pre_ye", "current", "pass", None),
    ("pre_ye", "post_ye", "exception", "Cut-off error"),
    ("pre_ye", "both", "exception", "Recorded in both periods"),
    ("pre_ye", "neither", "exception", "Possible unrecorded liability"),
    ("post_ye", "current", "exception", "Cut-off error"),
    ("post_ye", "post_ye", "pass", None),
    ("post_ye", "both", "exception", "Recorded in both periods"),
    ("post_ye", "neither", "review", "Not yet recorded"),
    ("spans", "current", "review", "Spans year end"),
    ("spans", "post_ye", "review", "Spans year end"),
    ("spans", "both", "exception", "Recorded in both periods"),
    ("spans", "neither", "exception", "Possible unrecorded liability"),
]


@pytest.mark.parametrize(("position", "recorded", "status", "issue"), MATRIX)
def test_matrix(cfg, position, recorded, status, issue):
    row = run_one(cfg, record_for(position), recorded)
    assert row.position == position
    assert row.recorded_in == recorded
    assert row.P.status == status
    assert row.P.issue_type == issue


def test_understatement_text_and_amount(cfg):
    row = run_one(cfg, record_for("pre_ye"), "post_ye")
    assert "understated by £1,000.00; an accrual is needed" in row.P.explanation
    assert "posted 10/04/2026" in row.P.explanation
    assert row.P.amount_impact == Decimal("1000.00")


def test_overstatement_text(cfg):
    row = run_one(cfg, record_for("post_ye"), "current")
    assert "overstated by £1,000.00; a prepayment/deferral is needed" in row.P.explanation


def test_unrecorded_uses_invoice_amount(cfg):
    row = run_one(cfg, record_for("pre_ye"), "neither")
    assert row.P.amount_impact == Decimal("1000.00")
    assert row.A.status == "n/a"


# ---------------------------------------------------------------- apportionment (C07, C08, C09)


@pytest.mark.parametrize(
    ("start", "end", "split"),
    [
        (date(2026, 1, 1), date(2026, 12, 31), (90, 275, 365)),  # C07 insurance
        (date(2026, 2, 1), date(2026, 5, 31), (59, 61, 120)),  # C08 maintenance
        (date(2026, 1, 1), date(2026, 4, 30), (90, 30, 120)),  # C09 cleaning
    ],
)
def test_day_counts(start, end, split):
    assert day_split(Period(start, end, "explicit period", False), YE) == split


def test_c07_prepayment(cfg):
    record = record_for("spans", net_amount=3650, vat_amount=0, gross_amount=3650)
    current = [make_line(net=Decimal("3650.00"), vat=Decimal("0"), gross=Decimal("3650.00"))]
    (row,) = run_cutoff_testing([record], index(*current), {}, cfg)
    assert row.P.status == "review"
    assert row.suggested_adjustment == Decimal("2750.00")  # 3,650 × 275/365
    assert row.apportionment == "275/365 days post-YE × £3,650.00"
    assert "Suggested prepayment £2,750.00" in row.P.explanation


def test_c08_accrual(cfg):
    record = record_for("spans", service_period_start="2026-02-01", service_period_end="2026-05-31")
    row = run_one(cfg, record, "post_ye")
    assert row.suggested_adjustment == Decimal("491.67")  # 1,000 × 59/120
    assert row.apportionment.startswith("59/120 days pre-YE")
    assert "accrual" in row.P.detail


def test_c09_prepayment(cfg):
    record = record_for("spans", service_period_start="2026-01-01", service_period_end="2026-04-30")
    row = run_one(cfg, record, "current")
    assert row.suggested_adjustment == Decimal("250.00")  # 1,000 × 30/120


def test_spans_unrecorded_is_pre_ye_portion(cfg):
    row = run_one(cfg, record_for("spans"), "neither")
    assert row.P.amount_impact == Decimal("246.58")  # 1,000 × 90/365
    assert "pre-YE portion" in row.P.explanation


# ---------------------------------------------------------------- period of activity


def test_delivery_date_basis(cfg):
    record = record_for("pre_ye", period_basis="delivery_date", delivery_date="2026-03-28",
                        service_period_start=None, service_period_end=None, invoice_date="2026-04-02")  # fmt: skip
    row = run_one(cfg, record, "post_ye")
    assert row.period_basis == "delivery date"
    assert row.period_start == row.period_end == date(2026, 3, 28)
    assert row.P.status == "exception"  # C02: goods received pre-YE, recorded post-YE


def test_fallback_never_passes(cfg):
    # C12: no period stated, invoice dated 30/03/2026, recorded in current year.
    record = record_for("pre_ye", period_basis="not_determinable", service_period_start=None,
                        service_period_end=None, invoice_date="2026-03-30")  # fmt: skip
    row = run_one(cfg, record, "current")
    assert row.period_basis == "invoice date (fallback)"
    assert row.P.status == "review"
    assert row.P.issue_type == "Service period not stated"


def test_fallback_exception_stays_exception(cfg):
    record = record_for("pre_ye", period_basis="not_determinable", service_period_start=None,
                        service_period_end=None, invoice_date="2026-03-30")  # fmt: skip
    row = run_one(cfg, record, "post_ye")
    assert row.P.status == "exception"
    assert row.P.detail.endswith("(invoice date used)")


def test_weak_service_period_is_review(cfg):
    row = run_one(cfg, record_for("pre_ye", confidence={"service_period": "low"}), "post_ye")
    assert row.P.status == "review"
    assert row.P.issue_type == "Low-confidence extraction"


def test_weak_invoice_number_is_review(cfg):
    row = run_one(cfg, record_for("pre_ye", confidence={"invoice_number": "low"}), "post_ye")
    assert row.match.status == "review"
    assert row.P.status == "review"
    assert row.recorded_in is None


def test_value_check_runs_against_found_line(cfg):
    current, _ = lines_for("current")
    current[0].net = Decimal("999.00")
    (row,) = run_cutoff_testing([record_for("pre_ye")], index(*current), {}, cfg)
    assert row.A.status == "exception"
    assert row.P.status == "pass"
    assert row.overall == "exception"
