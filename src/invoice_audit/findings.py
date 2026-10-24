"""Plain-English exception text and suggested actions (PLAN section 13).

Every explanation is a Python template filled with real numbers. The model never writes them, so the
wording is consistent across the file and can be reviewed like any other workpaper text.
"""

from datetime import date
from decimal import Decimal

from invoice_audit.models import CheckResult, CutoffTestRow, ExtractionRecord, Finding, MainTestRow
from invoice_audit.money import format_money

# Fixed issue-type vocabulary used on the Exceptions tab.
VALUE_MISMATCH = "Value mismatch"
CURRENCY_FX = "Currency / FX"
DATE_OUTSIDE_FY = "Date outside FY"
WRONG_ADDRESSEE = "Wrong addressee"
MISCLASSIFICATION = "Misclassification"
UNMAPPED_CODE = "Unmapped nominal code"
NO_LEDGER_MATCH = "No ledger match"
MULTIPLE_LEDGER_MATCHES = "Multiple ledger matches"
CUTOFF_ERROR = "Cut-off error"
SPANS_YEAR_END = "Spans year end"
UNRECORDED_LIABILITY = "Possible unrecorded liability"
RECORDED_IN_BOTH = "Recorded in both periods"
NOT_YET_RECORDED = "Not yet recorded"
PERIOD_NOT_STATED = "Service period not stated"
LOW_CONFIDENCE = "Low-confidence extraction"
NOT_AN_INVOICE = "Not an invoice"
MULTIPLE_INVOICES = "Multiple invoices in file"


def fmt_date(value: date | None) -> str:
    return f"{value:%d/%m/%Y}" if value else "unknown date"


def fmt_period(start: date | None, end: date | None) -> str:
    return fmt_date(start) if start == end else f"{fmt_date(start)}–{fmt_date(end)}"


def is_possible_transposition(difference: Decimal) -> bool:
    """Swapping two digits always changes a number by a multiple of 9 (in pence here)."""
    pence = abs(difference) * 100
    return pence != 0 and pence == pence.to_integral_value() and int(pence) % 9 == 0


# ---------------------------------------------------------------- templates


def passed(detail: str) -> CheckResult:
    return CheckResult("pass", detail)


def low_confidence(what: str, test_name: str) -> CheckResult:
    return CheckResult(
        "review",
        f"Unable to test: low-confidence {what}",
        issue_type=LOW_CONFIDENCE,
        explanation=f"Could not reliably read {what} (low confidence). {test_name} not performed.",
        suggested_action="Inspect the invoice manually.",
    )


def covered_elsewhere(detail: str) -> CheckResult:
    """A Review whose cause is already explained by another finding on the same row."""
    return CheckResult("review", detail)


def value_mismatch(basis: str, invoice_amount: Decimal, ledger_amount: Decimal, currency: str) -> CheckResult:
    difference = invoice_amount - ledger_amount
    text = (
        f"Invoice {basis} {format_money(invoice_amount, currency)} does not agree to ledger {basis} "
        f"{format_money(ledger_amount, currency)} (difference {format_money(abs(difference), currency)})."
    )
    if is_possible_transposition(difference):
        text += " The difference is divisible by 9, a possible transposition."
    return CheckResult(
        "exception",
        f"Diff {format_money(difference, currency)}",
        issue_type=VALUE_MISMATCH,
        explanation=text,
        suggested_action="Obtain explanation and correct posting if needed.",
        amount_impact=abs(difference) if currency == "GBP" else None,
    )


def currency_mismatch(invoice_currency: str, ledger_currency: str) -> CheckResult:
    return CheckResult(
        "exception",
        f"Currency {invoice_currency} vs {ledger_currency}",
        issue_type=CURRENCY_FX,
        explanation=f"Invoice is in {invoice_currency} but the ledger line is recorded in {ledger_currency}.",
        suggested_action="Confirm the correct currency and amount; correct the posting if needed.",
    )


def fx_no_original_amount(invoice_currency: str) -> CheckResult:
    return CheckResult(
        "review",
        "FX: auditor to agree",
        issue_type=CURRENCY_FX,
        explanation=f"Invoice is in {invoice_currency}. Ledger has no original-currency amount to agree to.",
        suggested_action="Agree to the FX rate used and the original amount.",
    )


def date_before_fy(invoice_date: date, fy_start: date) -> CheckResult:
    return CheckResult(
        "exception",
        "Prior period",
        issue_type=DATE_OUTSIDE_FY,
        explanation=(
            f"Invoice dated {fmt_date(invoice_date)} is before the financial year starting {fmt_date(fy_start)}."
        ),
        suggested_action="Confirm why a prior-period invoice is in the current-year ledger.",
    )


def date_after_fy(invoice_date: date, fy_end: date) -> CheckResult:
    return CheckResult(
        "exception",
        "Later period",
        issue_type=DATE_OUTSIDE_FY,
        explanation=f"Invoice dated {fmt_date(invoice_date)} is after the financial year ending {fmt_date(fy_end)}.",
        suggested_action=(
            "Confirm why a later-period invoice is in the current-year ledger and whether a cut-off adjustment "
            "is needed."
        ),
    )


def addressed_to_group(addressed_to: str, company: str) -> CheckResult:
    return CheckResult(
        "exception",
        "Group company",
        issue_type=WRONG_ADDRESSEE,
        explanation=f"Invoice is addressed to {addressed_to} (group company), not {company}.",
        suggested_action="Confirm the cost belongs to the audited entity. Consider a recharge.",
    )


def addressed_to_other(addressed_to: str, company: str) -> CheckResult:
    return CheckResult(
        "exception",
        "Different entity",
        issue_type=WRONG_ADDRESSEE,
        explanation=f"Invoice is addressed to {addressed_to}, a different entity, not {company}.",
        suggested_action="Confirm the cost belongs to the audited entity. Consider a recharge.",
    )


def addressee_borderline(addressed_to: str, company: str, score: float) -> CheckResult:
    return CheckResult(
        "review",
        f"Similar name (score {score:.0f})",
        issue_type=WRONG_ADDRESSEE,
        explanation=(
            f"Invoice is addressed to {addressed_to}, which is similar to but not the same as {company} "
            f"(match score {score:.0f})."
        ),
        suggested_action="Confirm the invoice is addressed to the audited entity.",
    )


def misclassified(
    code: str, account: str, description: str | None, ai_category: str, reasoning: str | None
) -> CheckResult:
    short = (description or "").strip()
    if len(short) > 80:
        short = short[:77] + "..."
    return CheckResult(
        "exception",
        f"Suggest {ai_category}",
        issue_type=MISCLASSIFICATION,
        explanation=f"Posted to {code} {account}, but the description ('{short}') suggests {ai_category}.",
        suggested_action="Consider a reclassification journal.",
        ai_reasoning=reasoning,
    )


def unmapped_code(code: str) -> CheckResult:
    return CheckResult(
        "review",
        f"Code {code} unmapped",
        issue_type=UNMAPPED_CODE,
        explanation=f"Nominal code {code} is not mapped to a category in categories.toml. Classification not tested.",
        suggested_action="Add the code to categories.toml, or agree the classification manually.",
    )


def no_ledger_match(invoice_number: str, post_ye_posting: date | None) -> CheckResult:
    text = f"No ledger entry found for invoice number {invoice_number}"
    if post_ye_posting is not None:
        text += f" (found in post-year-end ledger, posted {fmt_date(post_ye_posting)})"
    return CheckResult(
        "exception",
        "Not in ledger",
        issue_type=NO_LEDGER_MATCH,
        explanation=text + ".",
        suggested_action="Find out why the invoice is not recorded and whether a liability is missing.",
    )


def multiple_ledger_matches(invoice_number: str, count: int, ledger_name: str) -> CheckResult:
    return CheckResult(
        "review",
        f"{count} ledger matches",
        issue_type=MULTIPLE_LEDGER_MATCHES,
        explanation=f"Invoice number {invoice_number} appears {count} times in the {ledger_name}. Agree manually.",
        suggested_action="Agree the invoice to the correct posting and check for duplicate postings.",
    )


def cutoff_understated(period: str, ye: date, posted: date, amount: str, reasoning: str | None) -> CheckResult:
    return CheckResult(
        "exception",
        "Pre-YE cost recorded after YE",
        issue_type=CUTOFF_ERROR,
        explanation=(
            f"Goods/services relate to {period}, on or before the year end {fmt_date(ye)}, but the invoice is "
            f"recorded in the post-year-end ledger (posted {fmt_date(posted)}). Current-year expenses are "
            f"understated by {amount}; an accrual is needed."
        ),
        suggested_action=f"Propose an accrual of {amount}.",
        ai_reasoning=reasoning,
    )


def cutoff_overstated(period: str, ye: date, posted: date, amount: str, reasoning: str | None) -> CheckResult:
    return CheckResult(
        "exception",
        "Post-YE cost recorded in current year",
        issue_type=CUTOFF_ERROR,
        explanation=(
            f"Goods/services relate to {period}, after the year end {fmt_date(ye)}, but the invoice is recorded "
            f"in the current-year ledger (posted {fmt_date(posted)}). Current-year expenses are overstated by "
            f"{amount}; a prepayment/deferral is needed."
        ),
        suggested_action=f"Propose a prepayment/deferral of {amount}.",
        ai_reasoning=reasoning,
    )


def recorded_in_both(current_posted: date, post_ye_posted: date, amount: str) -> CheckResult:
    return CheckResult(
        "exception",
        "Recorded in both periods",
        issue_type=RECORDED_IN_BOTH,
        explanation=(
            f"Invoice is recorded in both the current-year ledger (posted {fmt_date(current_posted)}) and the "
            f"post-year-end ledger (posted {fmt_date(post_ye_posted)}). Possible double count of {amount}."
        ),
        suggested_action="Confirm which posting is correct and reverse the duplicate.",
    )


def unrecorded_liability(period: str, amount: str, portion: str, reasoning: str | None) -> CheckResult:
    return CheckResult(
        "exception",
        "Not recorded",
        issue_type=UNRECORDED_LIABILITY,
        explanation=(
            f"Goods/services for {period} are not recorded in either ledger. "
            f"Possible unrecorded liability of {amount}{portion}."
        ),
        suggested_action="Investigate and propose an accrual if the liability existed at the year end.",
        ai_reasoning=reasoning,
    )


def not_yet_recorded(period: str) -> CheckResult:
    return CheckResult(
        "review",
        "Not yet recorded",
        issue_type=NOT_YET_RECORDED,
        explanation=(
            f"Goods/services for {period} are after the year end and not yet recorded in either ledger. "
            "No current-year impact."
        ),
        suggested_action="Confirm the invoice will be recorded in the following period.",
    )


def spans_year_end(
    period: str, recorded: str, adjustment_kind: str, adjustment: str, working: str, reasoning: str | None
) -> CheckResult:
    return CheckResult(
        "review",
        f"Spans YE: {adjustment_kind} {adjustment}",
        issue_type=SPANS_YEAR_END,
        explanation=(
            f"Service period {period} spans the year end and the invoice is recorded in the {recorded}. "
            f"Suggested {adjustment_kind} {adjustment} ({working})."
        ),
        suggested_action=f"Use judgement: consider a {adjustment_kind} of {adjustment}.",
        ai_reasoning=reasoning,
    )


def period_not_stated(invoice_date: date | None) -> CheckResult:
    return CheckResult(
        "review",
        "Invoice date used",
        issue_type=PERIOD_NOT_STATED,
        explanation=(
            f"Service period not stated. Invoice date ({fmt_date(invoice_date)}) used. Confirm the period the "
            "goods/services relate to."
        ),
        suggested_action="Confirm the period from supporting documents (delivery note, contract, timesheet).",
    )


# ---------------------------------------------------------------- building the Exceptions list


def _finding(ref: str, test: str, test_ref: str, check: CheckResult, record: ExtractionRecord) -> Finding:
    invoice = record.invoice
    return Finding(
        ref=ref,
        test=test,
        test_ref=test_ref,
        status=check.status,
        issue_type=check.issue_type or "",
        file=record.source.display_name,
        supplier=invoice.supplier_name if invoice else None,
        invoice_number=invoice.invoice_number if invoice else None,
        explanation=check.explanation or "",
        ai_reasoning=check.ai_reasoning,
        suggested_action=check.suggested_action or "",
        amount_impact=check.amount_impact,
    )


def build_findings(
    main_rows: list[MainTestRow], cutoff_rows: list[CutoffTestRow], records: list[ExtractionRecord]
) -> list[Finding]:
    """Turn every Exception/Review check into a numbered Finding (Main, then Cut-off, then Extraction).

    Sets `finding_ref` on each check so the test tabs can point to the Exceptions tab. A Review with no
    explanation of its own (e.g. "not tested, invoice number unreadable") points to the row's first finding.
    """
    findings: list[Finding] = []

    def add(test: str, test_ref: str, check: CheckResult, record: ExtractionRecord) -> str:
        ref = f"EX-{len(findings) + 1:03d}"
        findings.append(_finding(ref, test, test_ref, check, record))
        return ref

    rows: list[tuple[str, MainTestRow | CutoffTestRow]] = [("Main", r) for r in main_rows]
    rows += [("Cut-off", r) for r in cutoff_rows]
    for test, row in rows:
        first_ref = None
        for check in row.checks:
            if check.status in ("exception", "review") and check.explanation:
                check.finding_ref = add(test, row.ref, check, row.record)
                first_ref = first_ref or check.finding_ref
        for check in row.checks:
            if check.status in ("exception", "review") and not check.finding_ref:
                check.finding_ref = first_ref

    for record in records:
        invoice = record.invoice
        if invoice is None:
            continue
        doc_ref = f"DOC-{record.source.doc_id[:8]}"
        if record.status == "excluded" and invoice.document_type != "invoice":
            kind = invoice.document_type.replace("_", " ")
            check = CheckResult(
                "review",
                issue_type=NOT_AN_INVOICE,
                explanation=f"Document is a {kind}, not an invoice. It was excluded from testing.",
                suggested_action="Confirm the document is not needed for testing, or replace it with the invoice.",
            )
            add("Extraction", doc_ref, check, record)
        elif invoice.multiple_invoices_detected:
            check = CheckResult(
                "review",
                issue_type=MULTIPLE_INVOICES,
                explanation="File contains more than one invoice. Only the first was read, and all tests are Review.",
                suggested_action="Split the file into one invoice per file and re-run.",
            )
            add("Extraction", doc_ref, check, record)
    return findings
