"""Test 1: main testing, tests of detail on the auditor's sample (PLAN section 11).

Each invoice is agreed to the current-year ledger on invoice number, then four checks run:
A value agrees, D date in financial year, E addressed to the audited entity, C classification.
"""

from dataclasses import dataclass
from decimal import Decimal

from invoice_audit import findings as F
from invoice_audit.config import RunConfig
from invoice_audit.matching import match_addressee, normalise_invoice_number
from invoice_audit.models import CheckResult, ExtractionRecord, LedgerLine, MainTestRow


@dataclass
class ValueOutcome:
    check: CheckResult
    invoice_amount: Decimal | None = None
    ledger_amount: Decimal | None = None
    difference: Decimal | None = None


def value_check(record: ExtractionRecord, line: LedgerLine, cfg: RunConfig) -> ValueOutcome:
    """Column A. Compares on the ledger's basis (net or gross) and in the invoice's own currency (PLAN D8, D16)."""
    basis = cfg.amount_basis
    amount_field = f"{basis}_amount"
    invoice = record.invoice
    if record.is_weak(amount_field) or record.is_weak("currency"):
        return ValueOutcome(F.low_confidence("amounts", "Value test"))

    invoice_amount = getattr(invoice, amount_field)
    currency = invoice.currency
    if currency == "GBP":
        if line.currency != "GBP":
            return ValueOutcome(F.currency_mismatch(currency, line.currency), invoice_amount)
        ledger_amount = line.net if basis == "net" else line.gross
    else:
        if line.currency != currency:
            return ValueOutcome(F.currency_mismatch(currency, line.currency), invoice_amount)
        if line.original_amount is None:
            return ValueOutcome(F.fx_no_original_amount(currency), invoice_amount)
        ledger_amount = line.original_amount

    if ledger_amount is None:
        return ValueOutcome(F.low_confidence(f"ledger {basis} amount", "Value test"), invoice_amount)
    difference = invoice_amount - ledger_amount
    if abs(difference) <= cfg.matching.value_tolerance:
        return ValueOutcome(F.passed("Agrees"), invoice_amount, ledger_amount, difference)
    check = F.value_mismatch(basis, invoice_amount, ledger_amount, currency)
    return ValueOutcome(check, invoice_amount, ledger_amount, difference)


def date_check(record: ExtractionRecord, cfg: RunConfig) -> CheckResult:
    """Column D. Boundaries are inclusive: 1 April and 31 March both pass."""
    if record.is_weak("invoice_date"):
        return F.low_confidence("invoice date", "Date test")
    invoice_date = record.invoice.invoice_date
    if invoice_date < cfg.engagement.fy_start:
        return F.date_before_fy(invoice_date, cfg.engagement.fy_start)
    if invoice_date > cfg.engagement.fy_end:
        return F.date_after_fy(invoice_date, cfg.engagement.fy_end)
    return F.passed("In FY")


def addressee_check(record: ExtractionRecord, cfg: RunConfig) -> CheckResult:
    """Column E. Invoices must be addressed to the audited entity (or a known trading name)."""
    if record.is_weak("addressed_to"):
        return F.low_confidence("addressee", "Addressee test")
    addressed_to = record.invoice.addressed_to
    company = cfg.engagement.company_name
    result = match_addressee(addressed_to, cfg)
    if result.outcome == "exact":
        return F.passed("Agrees")
    if result.outcome == "close":
        return F.passed(f"Close match, score {result.score:.0f}")
    if result.outcome == "group":
        return F.addressed_to_group(addressed_to, company)
    if result.outcome == "borderline":
        return F.addressee_borderline(addressed_to, company, result.score)
    return F.addressed_to_other(addressed_to, company)


def classification_check(record: ExtractionRecord, line: LedgerLine) -> CheckResult:
    """Column C. The ledger's nominal code category vs the category Claude suggests from the description."""
    if line.category is None:
        return F.unmapped_code(line.nominal_code)
    if record.is_weak("description"):
        return F.low_confidence("description", "Classification test")
    invoice = record.invoice
    if invoice.suggested_category == line.category:
        return F.passed("Agrees")
    account = line.nominal_account or line.category
    return F.misclassified(
        line.nominal_code, account, invoice.description, invoice.suggested_category, invoice.category_reasoning
    )


def _test_one(
    ref: str,
    record: ExtractionRecord,
    current: dict[str, list[LedgerLine]],
    post_ye: dict[str, list[LedgerLine]],
    cfg: RunConfig,
) -> MainTestRow:
    row = MainTestRow(ref=ref, record=record)

    if record.is_weak("invoice_number"):
        # Can't find the ledger line, so the ledger-dependent checks can't run; D and E still can.
        row.match = F.low_confidence("invoice number", "Ledger agreement")
        row.A = F.covered_elsewhere("Not tested: invoice no. unreadable")
        row.C = F.covered_elsewhere("Not tested: invoice no. unreadable")
        row.D = date_check(record, cfg)
        row.E = addressee_check(record, cfg)
        return row

    number = record.invoice.invoice_number
    matches = current.get(normalise_invoice_number(number), [])
    if not matches:
        found_later = post_ye.get(normalise_invoice_number(number), [])
        row.match = F.no_ledger_match(number, found_later[0].posting_date if found_later else None)
        return row
    if len(matches) > 1:
        row.match = F.multiple_ledger_matches(number, len(matches), "current-year ledger")
        return row

    line = matches[0]
    row.ledger_line = line
    value = value_check(record, line, cfg)
    row.A = value.check
    row.invoice_amount, row.ledger_amount, row.difference = value.invoice_amount, value.ledger_amount, value.difference
    row.D = date_check(record, cfg)
    row.E = addressee_check(record, cfg)
    row.C = classification_check(record, line)
    return row


def run_main_testing(
    records: list[ExtractionRecord],
    current: dict[str, list[LedgerLine]],
    post_ye: dict[str, list[LedgerLine]],
    cfg: RunConfig,
) -> list[MainTestRow]:
    """Run Test 1 on every readable main-sample invoice. Excluded/failed documents go to the Processing Log only."""
    rows: list[MainTestRow] = []
    for record in records:
        if record.status not in ("ok", "needs_review") or record.invoice is None:
            continue
        rows.append(_test_one(f"MT-{len(rows) + 1:03d}", record, current, post_ye, cfg))
    return rows


def value_tested(rows: list[MainTestRow], cfg: RunConfig) -> Decimal:
    """Total ledger basis amount (GBP) of the invoices agreed to a ledger line."""
    total = Decimal("0.00")
    for row in rows:
        if row.ledger_line is not None:
            amount = row.ledger_line.net if cfg.amount_basis == "net" else row.ledger_line.gross
            total += amount or Decimal("0.00")
    return total
