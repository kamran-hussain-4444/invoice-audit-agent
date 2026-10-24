"""Test 2: cut-off testing on invoices either side of the year end (PLAN section 12).

For each invoice we work out *when* the goods/services were received (the period of activity) and
*where* it is recorded (current-year ledger, post-year-end ledger, both or neither), then apply the
section 12 matrix. Invoices spanning the year end are a judgement call, so they are Review with a
day-count apportioned accrual or prepayment suggested.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from invoice_audit import findings as F
from invoice_audit.config import RunConfig
from invoice_audit.matching import normalise_invoice_number
from invoice_audit.models import CheckResult, CutoffTestRow, ExtractionRecord, LedgerLine
from invoice_audit.money import format_money, quantize
from invoice_audit.procedures.main_testing import value_check

RECORDED_LABELS = {"current": "Current", "post_ye": "Post-YE", "both": "Both", "neither": "Neither"}


@dataclass
class Period:
    start: date
    end: date
    basis: str
    fallback: bool  # True when no period was stated and the invoice date was used instead


def determine_period(record: ExtractionRecord) -> Period | None:
    """Period of activity from what Claude read. Never uses the invoice date unless nothing else is available."""
    invoice = record.invoice
    basis = invoice.period_basis
    start, end = invoice.service_period_start, invoice.service_period_end
    if basis in ("explicit_period", "description_inference") and start and end:
        return Period(start, end, basis.replace("_", " "), fallback=False)
    if basis == "delivery_date" and invoice.delivery_date:
        return Period(invoice.delivery_date, invoice.delivery_date, "delivery date", fallback=False)
    if not record.is_weak("invoice_date"):
        return Period(invoice.invoice_date, invoice.invoice_date, "invoice date (fallback)", fallback=True)
    return None


def position(period: Period, year_end: date) -> str:
    if period.end <= year_end:
        return "pre_ye"
    if period.start > year_end:
        return "post_ye"
    return "spans"


def day_split(period: Period, year_end: date) -> tuple[int, int, int]:
    """(days on or before year end, days after year end, total days), both ends inclusive."""
    days_before = (year_end - period.start).days + 1
    days_after = (period.end - year_end).days
    return days_before, days_after, days_before + days_after


def apportion(amount: Decimal, days: int, total: int) -> Decimal:
    return quantize(amount * days / total)


def _period_check(
    row: CutoffTestRow,
    period: Period,
    current: LedgerLine | None,
    post_ye: LedgerLine | None,
    amount: Decimal | None,
    amount_currency: str | None,
    cfg: RunConfig,
) -> CheckResult:
    ye = cfg.engagement.fy_end
    where = row.recorded_in
    pos = row.position
    period_text = F.fmt_period(period.start, period.end)
    amount_text = format_money(amount, amount_currency)
    reasoning = row.record.invoice.period_reasoning
    impact = amount if amount_currency == "GBP" else None

    if where == "both":
        check = F.recorded_in_both(current.posting_date, post_ye.posting_date, amount_text)
        check.amount_impact = impact
        return check

    if pos == "pre_ye":
        if where == "current":
            return F.passed("Pre-YE, in current year")
        if where == "post_ye":
            check = F.cutoff_understated(period_text, ye, post_ye.posting_date, amount_text, reasoning)
            check.amount_impact = impact
            return check
        check = F.unrecorded_liability(period_text, amount_text, "", reasoning)
        check.amount_impact = impact
        return check

    if pos == "post_ye":
        if where == "post_ye":
            return F.passed("Post-YE, in post-YE ledger")
        if where == "current":
            check = F.cutoff_overstated(period_text, ye, current.posting_date, amount_text, reasoning)
            check.amount_impact = impact
            return check
        return F.not_yet_recorded(period_text)

    # Spans the year end: suggest an apportioned adjustment, auditor decides.
    days_before, days_after, total = day_split(period, ye)
    if where == "current":
        kind, days, side = "prepayment", days_after, "post-YE"
    elif where == "post_ye":
        kind, days, side = "accrual", days_before, "pre-YE"
    else:
        kind, days, side = None, days_before, "pre-YE"
    adjustment = apportion(amount, days, total) if amount is not None else None
    row.suggested_adjustment = adjustment
    row.apportionment = f"{days}/{total} days {side} × {amount_text}"
    adjustment_text = format_money(adjustment, amount_currency)
    if kind is None:
        check = F.unrecorded_liability(
            period_text, adjustment_text, f" (pre-YE portion, {row.apportionment})", reasoning
        )
        check.amount_impact = adjustment if amount_currency == "GBP" else None
        return check
    recorded = "current-year ledger" if where == "current" else "post-year-end ledger"
    check = F.spans_year_end(period_text, recorded, kind, adjustment_text, row.apportionment, reasoning)
    check.amount_impact = adjustment if amount_currency == "GBP" else None
    return check


def _single(
    lines: list[LedgerLine], number: str, ledger_name: str, row: CutoffTestRow
) -> tuple[LedgerLine | None, bool]:
    """The one matching ledger line (or None). Returns ok=False and sets a Review if there are duplicates."""
    if len(lines) > 1:
        row.match = F.multiple_ledger_matches(number, len(lines), ledger_name)
        return None, False
    return (lines[0] if lines else None), True


def _test_one(
    ref: str,
    record: ExtractionRecord,
    current_index: dict[str, list[LedgerLine]],
    post_ye_index: dict[str, list[LedgerLine]],
    cfg: RunConfig,
) -> CutoffTestRow:
    row = CutoffTestRow(ref=ref, record=record)
    invoice = record.invoice
    ye = cfg.engagement.fy_end

    period = None if record.is_weak("service_period") else determine_period(record)
    if period is not None:
        row.period_start, row.period_end, row.period_basis = period.start, period.end, period.basis
        row.position = position(period, ye)

    if record.is_weak("invoice_number"):
        row.match = F.low_confidence("invoice number", "Ledger lookup")
        row.A = F.covered_elsewhere("Not tested: invoice no. unreadable")
        row.P = F.covered_elsewhere("Not tested: invoice no. unreadable")
        return row

    number = invoice.invoice_number
    norm = normalise_invoice_number(number)
    current, ok_current = _single(current_index.get(norm, []), number, "current-year ledger", row)
    post_ye, ok_post = _single(post_ye_index.get(norm, []), number, "post-year-end ledger", row)
    if not (ok_current and ok_post):
        return row

    if current and post_ye:
        row.recorded_in = "both"
    elif current:
        row.recorded_in = "current"
    elif post_ye:
        row.recorded_in = "post_ye"
    else:
        row.recorded_in = "neither"
    row.match = F.passed(RECORDED_LABELS[row.recorded_in])

    line = current or post_ye
    row.ledger_line = line
    if line is not None:
        value = value_check(record, line, cfg)
        row.A = value.check
        row.invoice_amount, row.ledger_amount, row.difference = (
            value.invoice_amount,
            value.ledger_amount,
            value.difference,
        )
        basis_amount = line.net if cfg.amount_basis == "net" else line.gross
        amount, amount_currency = basis_amount, "GBP"
    else:
        amount_field = f"{cfg.amount_basis}_amount"
        amount = None if record.is_weak(amount_field) else getattr(invoice, amount_field)
        amount_currency = invoice.currency

    if period is None:
        row.P = F.low_confidence("service period", "Cut-off test")
        return row

    row.P = _period_check(row, period, current, post_ye, amount, amount_currency, cfg)
    if period.fallback:
        if row.P.status == "pass":
            # A result based only on the invoice date can never be a Pass (PLAN section 12).
            row.P = F.period_not_stated(invoice.invoice_date)
        else:
            row.P.detail += " (invoice date used)"
    return row


def run_cutoff_testing(
    records: list[ExtractionRecord],
    current: dict[str, list[LedgerLine]],
    post_ye: dict[str, list[LedgerLine]],
    cfg: RunConfig,
) -> list[CutoffTestRow]:
    rows: list[CutoffTestRow] = []
    for record in records:
        if record.status not in ("ok", "needs_review") or record.invoice is None:
            continue
        rows.append(_test_one(f"CO-{len(rows) + 1:03d}", record, current, post_ye, cfg))
    return rows
