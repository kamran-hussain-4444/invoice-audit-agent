"""Rule checks on every successful extraction (PLAN section 10).

Claude can be over-confident, so Python double-checks what it read. Any problem marks the document
"needs_review" and lists the affected fields in `weak_fields`; tests that depend on a weak field give
Review, never Pass or Exception. We never guess.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from invoice_audit.models import AMOUNT_FIELDS, ExtractedInvoice
from invoice_audit.money import format_money

# field_confidence key → the field names it covers
CONFIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "supplier_name": ("supplier_name",),
    "addressed_to": ("addressed_to",),
    "invoice_number": ("invoice_number",),
    "invoice_date": ("invoice_date",),
    "amounts": AMOUNT_FIELDS,
    "currency": ("currency",),
    "description": ("description",),
    "service_period": ("service_period",),
}
ALL_FIELDS = {name for names in CONFIDENCE_FIELDS.values() for name in names}
REQUIRED_FIELDS = {
    "supplier_name": "Supplier name",
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "gross_amount": "Gross amount",
}
UK_VAT_RATES = (Decimal("0"), Decimal("5"), Decimal("20"))
VAT_RATE_SLACK = Decimal("0.5")  # percentage points, allows for rounding on small invoices
EARLIEST_PLAUSIBLE_DATE = date(2015, 1, 1)


@dataclass
class ValidationOutcome:
    status: Literal["ok", "needs_review", "excluded"]
    reasons: list[str] = field(default_factory=list)
    weak_fields: set[str] = field(default_factory=set)


def validate_extraction(invoice: ExtractedInvoice, today: date | None = None) -> ValidationOutcome:
    today = today or date.today()

    if invoice.document_type != "invoice":
        kind = invoice.document_type.replace("_", " ")
        return ValidationOutcome("excluded", [f"Document is a {kind}, not an invoice"], set(ALL_FIELDS))

    reasons: list[str] = []
    weak: set[str] = set()

    def flag(reason: str, *fields: str) -> None:
        reasons.append(reason)
        weak.update(fields)

    if invoice.multiple_invoices_detected:
        flag("File contains more than one invoice. Split and re-run.", *ALL_FIELDS)

    for name, label in REQUIRED_FIELDS.items():
        if getattr(invoice, name) is None and name not in invoice.unparseable_dates:
            flag(f"{label} not found", name)

    for key, fields in CONFIDENCE_FIELDS.items():
        if getattr(invoice.field_confidence, key) == "low":
            flag(f"Low confidence: {key.replace('_', ' ')}", *fields)

    net, vat, gross = invoice.net_amount, invoice.vat_amount, invoice.gross_amount
    if net is not None and vat is not None and gross is not None:
        difference = net + vat - gross
        if abs(difference) > Decimal("0.01"):
            flag(f"Net + VAT ≠ gross (difference {format_money(abs(difference), invoice.currency)})", *AMOUNT_FIELDS)

    if invoice.currency == "GBP" and net and vat is not None:
        rate = vat / net * 100
        if not any(abs(rate - standard) <= VAT_RATE_SLACK for standard in UK_VAT_RATES):
            flag(f"Unusual VAT rate {rate:.1f}%", *AMOUNT_FIELDS)

    if "invoice_date" in invoice.unparseable_dates:
        flag("Invoice date is not a valid date", "invoice_date")
    elif invoice.invoice_date is not None:
        if invoice.invoice_date > today:
            flag(f"Invoice date {invoice.invoice_date:%d/%m/%Y} is in the future", "invoice_date")
        elif invoice.invoice_date < EARLIEST_PLAUSIBLE_DATE:
            flag(f"Invoice date {invoice.invoice_date:%d/%m/%Y} is implausibly old", "invoice_date")

    if invoice.currency is None or not re.fullmatch(r"[A-Z]{3}", invoice.currency):
        flag(f"Currency '{invoice.currency}' is not a 3-letter ISO code", "currency")

    period_dates_bad = {"service_period_start", "service_period_end"} & set(invoice.unparseable_dates)
    if period_dates_bad:
        flag("Service period date is not a valid date", "service_period")
    start, end = invoice.service_period_start, invoice.service_period_end
    if start is not None and end is not None and end < start:
        flag("Service period ends before it starts", "service_period")

    return ValidationOutcome("needs_review" if reasons else "ok", reasons, weak)
