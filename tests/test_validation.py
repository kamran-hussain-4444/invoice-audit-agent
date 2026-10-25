from datetime import date

import pytest

from invoice_audit.validation import ALL_FIELDS, validate_extraction
from tests.conftest import make_invoice

TODAY = date(2026, 10, 1)


def check(**changes):
    return validate_extraction(make_invoice(**changes), today=TODAY)


def test_clean_invoice_is_ok():
    outcome = check()
    assert outcome.status == "ok"
    assert outcome.reasons == []
    assert outcome.weak_fields == set()


@pytest.mark.parametrize("doc_type", ["statement", "credit_note", "quote", "remittance", "other"])
def test_non_invoice_is_excluded(doc_type):
    outcome = check(document_type=doc_type)
    assert outcome.status == "excluded"
    assert outcome.reasons == [f"Document is a {doc_type.replace('_', ' ')}, not an invoice"]


def test_multiple_invoices_makes_everything_weak():
    outcome = check(multiple_invoices_detected=True)
    assert outcome.status == "needs_review"
    assert outcome.weak_fields == ALL_FIELDS
    assert "Split and re-run" in outcome.reasons[0]


@pytest.mark.parametrize("name", ["supplier_name", "invoice_number", "invoice_date", "gross_amount"])
def test_missing_key_field(name):
    outcome = check(**{name: None})
    assert outcome.status == "needs_review"
    assert name in outcome.weak_fields


def test_missing_gross_does_not_trip_arithmetic_check():
    outcome = check(gross_amount=None)
    assert outcome.weak_fields == {"gross_amount"}


@pytest.mark.parametrize(
    ("key", "fields"),
    [
        ("invoice_date", {"invoice_date"}),
        ("amounts", {"net_amount", "vat_amount", "gross_amount"}),
        ("addressed_to", {"addressed_to"}),
    ],
)
def test_low_confidence_marks_fields_weak(key, fields):
    outcome = check(confidence={key: "low"})
    assert outcome.status == "needs_review"
    assert outcome.weak_fields == fields


def test_low_period_confidence_ignored_when_no_period_stated():
    # Claude often marks "no period found" as low confidence; the cut-off fallback already handles it.
    outcome = check(period_basis="not_determinable", confidence={"service_period": "low"})
    assert outcome.status == "ok"
    explicit = check(period_basis="explicit_period", service_period_start="2026-03-01",
                     service_period_end="2026-03-31", confidence={"service_period": "low"})  # fmt: skip
    assert explicit.weak_fields == {"service_period"}


def test_medium_confidence_alone_is_fine():
    assert check(confidence={"amounts": "medium", "description": "medium"}).status == "ok"


def test_net_plus_vat_not_gross():
    outcome = check(net_amount=1000.00, vat_amount=200.00, gross_amount=1200.40)
    assert outcome.status == "needs_review"
    assert "Net + VAT ≠ gross (difference £0.40)" in outcome.reasons
    assert {"net_amount", "vat_amount", "gross_amount"} <= outcome.weak_fields


def test_one_penny_rounding_is_tolerated():
    assert check(net_amount=10.03, vat_amount=2.01, gross_amount=12.05).status == "ok"


@pytest.mark.parametrize(("net", "vat"), [(1000, 0), (1000, 50), (1000, 200), (1000, 203)])
def test_standard_vat_rates_ok(net, vat):
    assert check(net_amount=net, vat_amount=vat, gross_amount=net + vat).status == "ok"


def test_unusual_vat_rate():
    outcome = check(net_amount=1000, vat_amount=175, gross_amount=1175)
    assert "Unusual VAT rate 17.5%" in outcome.reasons


def test_vat_rate_not_checked_for_foreign_currency():
    assert check(currency="EUR", net_amount=1000, vat_amount=190, gross_amount=1190).status == "ok"


def test_impossible_date_is_review_not_crash():
    outcome = check(invoice_date="2026-02-30")
    assert outcome.status == "needs_review"
    assert "invoice_date" in outcome.weak_fields
    assert "Invoice date is not a valid date" in outcome.reasons
    assert "Invoice date not found" not in outcome.reasons


def test_future_date():
    outcome = check(invoice_date="2026-12-01")
    assert "invoice_date" in outcome.weak_fields


def test_implausibly_old_date():
    outcome = check(invoice_date="2009-01-01")
    assert "invoice_date" in outcome.weak_fields


@pytest.mark.parametrize("currency", ["£", "GB", "gbp", None])
def test_bad_currency(currency):
    outcome = check(currency=currency)
    assert "currency" in outcome.weak_fields


def test_period_end_before_start():
    outcome = check(service_period_start="2026-03-31", service_period_end="2026-03-01", period_basis="explicit_period")
    assert outcome.weak_fields == {"service_period"}
