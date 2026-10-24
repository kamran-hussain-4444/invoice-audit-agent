"""Shared test helpers: a loaded example config plus builders for clean invoices, records and ledger lines.

Each builder returns something that would PASS every test; individual tests change one thing to plant an error.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_audit.config import RunConfig, load_config
from invoice_audit.matching import index_ledger, normalise_invoice_number
from invoice_audit.models import ExtractedInvoice, ExtractionRecord, LedgerLine, SourceDocument
from invoice_audit.validation import validate_extraction

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_RUN = ROOT / "runs" / "example_fy2026.toml"


@pytest.fixture
def cfg() -> RunConfig:
    return load_config(EXAMPLE_RUN, base_dir=ROOT, check_files=False)


def make_invoice(**changes) -> ExtractedInvoice:
    data = {
        "document_type": "invoice",
        "supplier_name": "Lumen Print & Design Ltd",
        "supplier_vat_number": "GB123456789",
        "addressed_to": "Brackenfield Engineering Ltd",
        "invoice_number": "INV-1001",
        "invoice_date": "2025-11-03",
        "currency": "GBP",
        "net_amount": 1000.00,
        "vat_amount": 200.00,
        "gross_amount": 1200.00,
        "description": "Trade show brochures",
        "line_items": [{"description": "Brochures", "amount": 1000.00}],
        "delivery_date": None,
        "service_period_start": None,
        "service_period_end": None,
        "period_basis": "not_determinable",
        "period_reasoning": "No period stated.",
        "suggested_category": "Marketing",
        "category_reasoning": "Printed marketing material.",
        "multiple_invoices_detected": False,
        "field_confidence": {
            "supplier_name": "high",
            "addressed_to": "high",
            "invoice_number": "high",
            "invoice_date": "high",
            "amounts": "high",
            "currency": "high",
            "description": "high",
            "service_period": "high",
        },
        "extraction_notes": None,
    }
    confidence = changes.pop("confidence", {})
    data.update(changes)
    data["field_confidence"] = {**data["field_confidence"], **confidence}
    return ExtractedInvoice.model_validate(data)


def make_record(invoice: ExtractedInvoice | None = None, test: str = "main", **changes) -> ExtractionRecord:
    """A record as the pipeline would build it: the invoice plus the result of the validation rules."""
    invoice = invoice or make_invoice(**changes)
    outcome = validate_extraction(invoice, today=date(2026, 10, 1))
    source = SourceDocument(
        doc_id="abcdef0123456789",
        test=test,
        file_path=Path("doc_001.pdf"),
        display_name="doc_001.pdf",
        kind="pdf",
    )
    return ExtractionRecord(
        source=source,
        status=outcome.status,
        reasons=outcome.reasons,
        weak_fields=outcome.weak_fields,
        invoice=invoice,
    )


def make_line(**changes) -> LedgerLine:
    data = {
        "source": "current",
        "row_number": 2,
        "posting_date": date(2025, 11, 10),
        "supplier": "Lumen Print & Design Ltd",
        "invoice_number": "INV-1001",
        "description": "Brochures",
        "nominal_code": "6100",
        "nominal_account": "Marketing",
        "category": "Marketing",
        "net": Decimal("1000.00"),
        "vat": Decimal("200.00"),
        "gross": Decimal("1200.00"),
        "currency": "GBP",
        "original_amount": None,
    }
    data.update(changes)
    data["invoice_number_norm"] = normalise_invoice_number(data["invoice_number"])
    return LedgerLine(**data)


def index(*lines: LedgerLine) -> dict[str, list[LedgerLine]]:
    return index_ledger(list(lines))


def invoice_from_truth(truth: dict, low_confidence: tuple[str, ...] = ()) -> ExtractedInvoice:
    """The ExtractedInvoice a perfect reader would return for an answer-key entry."""
    fields = ["supplier_name", "supplier_vat_number", "addressed_to", "invoice_number", "invoice_date", "currency",
              "net_amount", "vat_amount", "gross_amount", "description", "delivery_date", "service_period_start",
              "service_period_end"]  # fmt: skip
    data = {name: truth.get(name) for name in fields}
    data.update(
        document_type=truth.get("document_type", "invoice"),
        line_items=[],
        period_basis=truth.get("period_basis", "not_determinable"),
        period_reasoning="From answer key.",
        suggested_category=truth.get("true_category", "Administrative expenses"),
        category_reasoning="From answer key.",
        multiple_invoices_detected=False,
        extraction_notes=None,
        field_confidence={key: ("low" if key in low_confidence else "high") for key in
                          ["supplier_name", "addressed_to", "invoice_number", "invoice_date", "amounts", "currency",
                           "description", "service_period"]},
    )  # fmt: skip
    return ExtractedInvoice.model_validate(data)
