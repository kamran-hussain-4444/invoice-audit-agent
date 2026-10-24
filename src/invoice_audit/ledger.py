"""Load a ledger listing (Excel or CSV) into `LedgerLine`s using the run file's column mapping.

Any problem here is fatal for the run (a wrong ledger would make every result wrong), so errors say
exactly which file, row and column to fix.
"""

import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pandas as pd

from invoice_audit.config import RunConfig, normalise_nominal_code
from invoice_audit.matching import normalise_invoice_number
from invoice_audit.models import LedgerLine
from invoice_audit.money import to_money


class LedgerError(Exception):
    """The ledger can't be used. The message is shown to the user as-is."""


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y-%m-%d %H:%M:%S")


def _clean_header(header: object) -> str:
    return " ".join(str(header).split()).casefold()


def _text(value: object) -> str:
    """Cell value as text. Excel numbers like 6800.0 become "6800"; empty cells become ""."""
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value).strip()


def _parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a date (expected DD/MM/YYYY)")


def _parse_amount(value: object) -> Decimal | None:
    if isinstance(value, float) and math.isnan(value):
        return None
    return to_money(value if isinstance(value, (int, float, Decimal)) else _text(value))


def _read_table(path: Path, sheet: str) -> pd.DataFrame:
    if not path.is_file():
        raise LedgerError(f"Ledger file not found: {path}")
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        if suffix in (".xlsx", ".xlsm"):
            return pd.read_excel(path, sheet_name=sheet or 0, dtype=object, engine="openpyxl")
    except ValueError as e:  # e.g. sheet name not found
        raise LedgerError(f"Could not read ledger {path.name}: {e}") from None
    except Exception as e:
        raise LedgerError(f"Could not open ledger {path.name}: {e}") from None
    raise LedgerError(f"Ledger {path.name}: unsupported file type {suffix}. Use .xlsx or .csv.")


def _map_columns(headers: list[object], cfg: RunConfig, path: Path) -> dict[str, object]:
    """Field name → the actual header in the file (matched ignoring case and extra spaces)."""
    by_clean = {_clean_header(h): h for h in headers}
    wanted = cfg.ledger.columns.model_dump()
    required = ["posting_date", "supplier", "invoice_number", "nominal_code", cfg.amount_basis]
    mapping: dict[str, object] = {}
    for field_name, header in wanted.items():
        actual = by_clean.get(_clean_header(header))
        if actual is not None:
            mapping[field_name] = actual
        elif field_name in required:
            found = ", ".join(str(h) for h in headers)
            raise LedgerError(
                f"Ledger {path.name}: required column '{header}' ({field_name}) not found.\n"
                f"Columns found: {found}\n"
                f'Rename the column, or set [ledger.columns] {field_name} = "<your header>" in the run file.'
            )
    return mapping


def load_ledger(path: Path, source: Literal["current", "post_ye"], cfg: RunConfig) -> list[LedgerLine]:
    table = _read_table(path, cfg.inputs.ledger_sheet)
    columns = _map_columns(list(table.columns), cfg, path)
    basis = cfg.amount_basis
    lines: list[LedgerLine] = []

    for position, row in enumerate(table.to_dict("records")):
        row_number = position + 2  # header is row 1 in Excel

        def cell(field_name: str, row: dict = row) -> object:
            return row[columns[field_name]] if field_name in columns else None

        invoice_number = _text(cell("invoice_number"))
        if not invoice_number:
            continue  # blank, subtotal or total rows have no invoice number

        def fail(column: str, problem: str, row_number: int = row_number) -> LedgerError:
            return LedgerError(f"Ledger {path.name}, row {row_number}, column '{column}': {problem}")

        try:
            posting_date = _parse_date(cell("posting_date"))
        except ValueError as e:
            raise fail(cfg.ledger.columns.posting_date, str(e)) from None

        amounts: dict[str, Decimal | None] = {}
        for name in ("net", "vat", "gross", "original_amount"):
            try:
                amounts[name] = _parse_amount(cell(name))
            except ValueError as e:
                raise fail(getattr(cfg.ledger.columns, name), str(e)) from None
        if amounts[basis] is None:
            raise fail(getattr(cfg.ledger.columns, basis), f"{basis} amount is blank")

        supplier = _text(cell("supplier"))
        if not supplier:
            raise fail(cfg.ledger.columns.supplier, "supplier is blank")
        nominal_code = normalise_nominal_code(_text(cell("nominal_code")))
        if not nominal_code:
            raise fail(cfg.ledger.columns.nominal_code, "nominal code is blank")

        lines.append(
            LedgerLine(
                source=source,
                row_number=row_number,
                posting_date=posting_date,
                supplier=supplier,
                invoice_number=invoice_number,
                invoice_number_norm=normalise_invoice_number(invoice_number),
                description=_text(cell("description")) or None,
                nominal_code=nominal_code,
                nominal_account=_text(cell("nominal_account")) or None,
                category=cfg.category_for_code(nominal_code),
                net=amounts["net"],
                vat=amounts["vat"],
                gross=amounts["gross"],
                currency=(_text(cell("currency")) or "GBP").upper(),
                original_amount=amounts["original_amount"],
            )
        )
    return lines
