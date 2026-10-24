"""Data models shared across the pipeline (PLAN section 6).

Pydantic is used where data arrives from outside (Claude's JSON). Plain dataclasses everywhere else.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from invoice_audit.money import to_money

TestName = Literal["main", "cutoff"]
CheckStatus = Literal["pass", "exception", "review", "n/a"]
Confidence = Literal["high", "medium", "low"]
DocumentType = Literal["invoice", "credit_note", "statement", "quote", "remittance", "other"]
PeriodBasis = Literal["explicit_period", "delivery_date", "description_inference", "not_determinable"]
AMOUNT_FIELDS = ("net_amount", "vat_amount", "gross_amount")
DATE_FIELDS = ("invoice_date", "delivery_date", "service_period_start", "service_period_end")


# ---------------------------------------------------------------- extraction (what Claude returns)


class LineItem(BaseModel):
    description: str
    amount: Decimal | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _money(cls, value: object) -> Decimal | None:
        return to_money(value)


class FieldConfidence(BaseModel):
    supplier_name: Confidence
    addressed_to: Confidence
    invoice_number: Confidence
    invoice_date: Confidence
    amounts: Confidence
    currency: Confidence
    description: Confidence
    service_period: Confidence


class ExtractedInvoice(BaseModel):
    """One invoice as read by Claude. Matches the JSON schema in extraction/schema.py."""

    document_type: DocumentType
    supplier_name: str | None
    supplier_vat_number: str | None
    addressed_to: str | None
    invoice_number: str | None
    invoice_date: date | None
    currency: str | None
    net_amount: Decimal | None
    vat_amount: Decimal | None
    gross_amount: Decimal | None
    description: str | None
    line_items: list[LineItem]
    delivery_date: date | None
    service_period_start: date | None
    service_period_end: date | None
    period_basis: PeriodBasis
    period_reasoning: str
    suggested_category: str
    category_reasoning: str
    multiple_invoices_detected: bool
    field_confidence: FieldConfidence
    extraction_notes: str | None
    # Set by us, not by Claude: date fields whose text was not a real date (e.g. "2026-02-30").
    unparseable_dates: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _lenient_dates(cls, data: object) -> object:
        """An impossible date becomes None + a note, so validation flags it as Review instead of crashing."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        bad = list(data.get("unparseable_dates", []))
        for name in DATE_FIELDS:
            value = data.get(name)
            if isinstance(value, str):
                try:
                    date.fromisoformat(value)
                except ValueError:
                    data[name] = None
                    bad.append(name)
        data["unparseable_dates"] = bad
        return data

    @field_validator(*AMOUNT_FIELDS, mode="before")
    @classmethod
    def _money(cls, value: object) -> Decimal | None:
        return to_money(value)


# ---------------------------------------------------------------- documents and extraction records


@dataclass
class SourceDocument:
    """One thing to extract: a file, or one attachment inside an email."""

    doc_id: str
    test: TestName
    file_path: Path
    display_name: str
    kind: Literal["pdf", "image", "docx", "xlsx", "email_body", "other"]  # "other" = unsupported, never loaded
    content_bytes: bytes | None = None
    email_context: str | None = None


@dataclass
class ContentPayload:
    """The content blocks sent to Claude for one document."""

    blocks: list[dict]
    approx_bytes: int


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class ExtractionRecord:
    """A document after extraction and validation. `weak_fields` drive Review results downstream."""

    source: SourceDocument
    status: Literal["ok", "needs_review", "excluded", "failed"]
    reasons: list[str] = field(default_factory=list)
    weak_fields: set[str] = field(default_factory=set)
    invoice: ExtractedInvoice | None = None
    usage: TokenUsage | None = None
    from_cache: bool = False
    mode: Literal["live", "batch", "cache"] | None = None

    def is_weak(self, name: str) -> bool:
        """True if a field can't be relied on: flagged by validation, or simply not there."""
        if name in self.weak_fields:
            return True
        if self.invoice is None:
            return True
        if name == "service_period":
            return False  # a missing period is handled by the cut-off fallback, not treated as weak
        return getattr(self.invoice, name, None) is None


# ---------------------------------------------------------------- ledger


@dataclass
class LedgerLine:
    source: Literal["current", "post_ye"]
    row_number: int  # Excel row, for traceability back to the client's listing
    posting_date: date
    supplier: str
    invoice_number: str
    invoice_number_norm: str
    description: str | None
    nominal_code: str
    nominal_account: str | None
    category: str | None
    net: Decimal | None
    vat: Decimal | None
    gross: Decimal | None
    currency: str = "GBP"
    original_amount: Decimal | None = None


# ---------------------------------------------------------------- test results


@dataclass
class CheckResult:
    """One tick cell. Exceptions and reviews carry the text for their Finding (written by findings.py)."""

    status: CheckStatus
    detail: str = ""
    issue_type: str | None = None
    explanation: str | None = None
    suggested_action: str | None = None
    ai_reasoning: str | None = None
    amount_impact: Decimal | None = None
    finding_ref: str | None = None


def overall_status(checks: list[CheckResult]) -> Literal["pass", "exception", "review"]:
    statuses = {c.status for c in checks}
    if "exception" in statuses:
        return "exception"
    if "review" in statuses:
        return "review"
    return "pass"


def _na() -> CheckResult:
    return CheckResult("n/a")


@dataclass
class MainTestRow:
    """Test 1 result for one invoice. Columns A (value), D (date), E (addressee), C (classification)."""

    ref: str
    record: ExtractionRecord
    match: CheckResult = field(default_factory=lambda: CheckResult("pass", "Matched"))
    ledger_line: LedgerLine | None = None
    invoice_amount: Decimal | None = None
    ledger_amount: Decimal | None = None
    difference: Decimal | None = None
    A: CheckResult = field(default_factory=_na)
    D: CheckResult = field(default_factory=_na)
    E: CheckResult = field(default_factory=_na)
    C: CheckResult = field(default_factory=_na)
    notes: str = ""

    @property
    def checks(self) -> list[CheckResult]:
        return [self.match, self.A, self.D, self.E, self.C]

    @property
    def overall(self) -> Literal["pass", "exception", "review"]:
        return overall_status(self.checks)

    @property
    def finding_refs(self) -> list[str]:
        return list(dict.fromkeys(c.finding_ref for c in self.checks if c.finding_ref))


@dataclass
class CutoffTestRow:
    """Test 2 result for one invoice. Columns A (value) and P (period / cut-off)."""

    ref: str
    record: ExtractionRecord
    match: CheckResult = field(default_factory=lambda: CheckResult("pass", "Looked up"))
    period_basis: str = ""
    period_start: date | None = None
    period_end: date | None = None
    position: Literal["pre_ye", "post_ye", "spans"] | None = None
    recorded_in: Literal["current", "post_ye", "both", "neither"] | None = None
    ledger_line: LedgerLine | None = None
    invoice_amount: Decimal | None = None
    ledger_amount: Decimal | None = None
    difference: Decimal | None = None
    apportionment: str = ""
    suggested_adjustment: Decimal | None = None
    A: CheckResult = field(default_factory=_na)
    P: CheckResult = field(default_factory=_na)
    notes: str = ""

    @property
    def checks(self) -> list[CheckResult]:
        return [self.match, self.A, self.P]

    @property
    def overall(self) -> Literal["pass", "exception", "review"]:
        return overall_status(self.checks)

    @property
    def finding_refs(self) -> list[str]:
        return list(dict.fromkeys(c.finding_ref for c in self.checks if c.finding_ref))


@dataclass
class Finding:
    """One row on the Exceptions tab."""

    ref: str
    test: Literal["Main", "Cut-off", "Extraction"]
    test_ref: str
    status: Literal["exception", "review"]
    issue_type: str
    file: str
    supplier: str | None
    invoice_number: str | None
    explanation: str
    ai_reasoning: str | None
    suggested_action: str
    amount_impact: Decimal | None
