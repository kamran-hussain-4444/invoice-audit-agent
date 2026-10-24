from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from invoice_audit.ledger import LedgerError, load_ledger

HEADERS = [
    "Posting Date", "Supplier", "Invoice No", "Description", "Nominal Code",
    "Nominal Account", "Net", "VAT", "Gross", "Currency", "Original Amount",
]  # fmt: skip


def write_xlsx(path: Path, headers: list[str], rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def write_csv(path: Path, headers: list[str], rows: list[list]) -> Path:
    lines = [",".join(headers)] + [",".join(f'"{v}"' for v in row) for row in rows]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_xlsx_ledger_loads(tmp_path, cfg):
    path = write_xlsx(
        tmp_path / "ledger.xlsx",
        HEADERS,
        [
            [datetime(2025, 11, 10), "Lumen Print", "INV-1001", "Brochures", 6100, "Marketing", 1000, 200, 1200, None,
             None],
            [datetime(2025, 12, 1), "Bauer Komponenten GmbH", "BK 77", "Parts", 5000, "Purchases", 2750.4, 0, 2750.4,
             "eur", 3200],
            [None, None, None, None, None, None, None, None, None, None, None],  # blank row skipped
            [None, "TOTAL", None, None, None, None, 3750.4, None, None, None, None],  # total row skipped
            [datetime(2026, 1, 5), "Atlas", "AT-9", "Lathe", 30, "Plant", 18500, 3700, 22200, None, None],
        ],
    )  # fmt: skip
    lines = load_ledger(path, "current", cfg)
    assert len(lines) == 3
    first, fx, asset = lines
    assert first.posting_date == date(2025, 11, 10)
    assert first.net == Decimal("1000.00")
    assert first.currency == "GBP"  # blank defaults to GBP
    assert first.category == "Marketing"
    assert first.row_number == 2
    assert fx.currency == "EUR"
    assert fx.original_amount == Decimal("3200.00")
    assert fx.net == Decimal("2750.40")
    assert fx.invoice_number_norm == "BK77"
    assert asset.nominal_code == "0030"
    assert asset.category == "Fixed assets (capital)"
    assert asset.row_number == 6


def test_csv_ledger_with_uk_dates_and_text_amounts(tmp_path, cfg):
    path = write_csv(
        tmp_path / "ledger.csv",
        HEADERS,
        [["03/04/2026", "Lumen Print", "inv 2231", "Brochures", "6100", "Marketing", "1,234.50", "246.90",
          "1,481.40", "", ""]],
    )  # fmt: skip
    (line,) = load_ledger(path, "post_ye", cfg)
    assert line.posting_date == date(2026, 4, 3)  # day first
    assert line.net == Decimal("1234.50")
    assert line.source == "post_ye"
    assert line.invoice_number == "inv 2231"
    assert line.invoice_number_norm == "INV2231"


def test_renamed_headers_via_config(tmp_path, cfg):
    cfg.ledger.columns.posting_date = "Date"
    cfg.ledger.columns.invoice_number = "Ref"
    cfg.ledger.columns.net = "Amount (net)"
    headers = ["date", "Supplier", " REF ", "Nominal Code", "Amount  (net)"]  # case and spaces ignored
    path = write_xlsx(tmp_path / "l.xlsx", headers, [[datetime(2025, 5, 1), "S", "X1", "6800", 10]])
    (line,) = load_ledger(path, "current", cfg)
    assert line.invoice_number == "X1"
    assert line.net == Decimal("10.00")
    assert line.vat is None  # optional column missing is fine
    assert line.description is None


def test_missing_required_column_lists_found_headers(tmp_path, cfg):
    path = write_xlsx(tmp_path / "l.xlsx", ["Posting Date", "Supplier", "Invoice Number", "Nominal Code", "Net"], [])
    with pytest.raises(LedgerError) as excinfo:
        load_ledger(path, "current", cfg)
    message = str(excinfo.value)
    assert "'Invoice No'" in message
    assert "Columns found: Posting Date, Supplier, Invoice Number, Nominal Code, Net" in message


def test_ap_listing_requires_gross_column(tmp_path, cfg):
    cfg.inputs.ledger_type = "ap_listing"
    path = write_xlsx(tmp_path / "l.xlsx", ["Posting Date", "Supplier", "Invoice No", "Nominal Code", "Net"], [])
    with pytest.raises(LedgerError, match="'Gross'"):
        load_ledger(path, "current", cfg)


def test_bad_date_reports_row_and_column(tmp_path, cfg):
    path = write_xlsx(tmp_path / "l.xlsx", HEADERS, [["not a date", "S", "X1", "", "6800", "", 10, 2, 12, "", ""]])
    with pytest.raises(LedgerError, match=r"row 2, column 'Posting Date'"):
        load_ledger(path, "current", cfg)


def test_bad_amount_reports_row_and_column(tmp_path, cfg):
    path = write_xlsx(
        tmp_path / "l.xlsx", HEADERS, [[datetime(2025, 5, 1), "S", "X1", "", "6800", "", "ten", 2, 12, "", ""]]
    )
    with pytest.raises(LedgerError, match=r"row 2, column 'Net'"):
        load_ledger(path, "current", cfg)


def test_blank_basis_amount_is_an_error(tmp_path, cfg):
    path = write_xlsx(
        tmp_path / "l.xlsx", HEADERS, [[datetime(2025, 5, 1), "S", "X1", "", "6800", "", None, 2, 12, "", ""]]
    )
    with pytest.raises(LedgerError, match="net amount is blank"):
        load_ledger(path, "current", cfg)


def test_missing_file(tmp_path, cfg):
    with pytest.raises(LedgerError, match="not found"):
        load_ledger(tmp_path / "nope.xlsx", "current", cfg)


def test_unknown_sheet(tmp_path, cfg):
    cfg.inputs.ledger_sheet = "Ledger 2026"
    path = write_xlsx(tmp_path / "l.xlsx", HEADERS, [])
    with pytest.raises(LedgerError, match="Could not read ledger"):
        load_ledger(path, "current", cfg)
