"""What is printed on an invoice, as text. Shared by every renderer so all formats show the same facts."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from invoice_audit.money import CURRENCY_SYMBOLS
from invoice_audit.synthetic.entities import (
    COMPANY_ADDRESS,
    DIRECTOR_ADDRESS,
    DIRECTOR_PERSONAL,
    GROUP_ADDRESS,
    GROUP_COMPANY,
    UNRELATED_ADDRESS,
    UNRELATED_COMPANY,
)
from invoice_audit.synthetic.scenarios import InvoiceSpec

_DATE_STYLES = ["%d/%m/%Y", "{day} %B %Y", "%d-%b-%Y", "%d.%m.%Y"]


def format_date(value: date, layout: int, currency: str = "GBP") -> str:
    if currency == "USD":
        return value.strftime("%b {day}, %Y").replace("{day}", str(value.day))  # unambiguous US style
    if currency == "EUR":
        return value.strftime("%d.%m.%Y")
    return value.strftime(_DATE_STYLES[layout % 4]).replace("{day}", str(value.day))


def format_amount(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def bill_to_address(addressed_to: str) -> list[str]:
    addresses = {
        GROUP_COMPANY: GROUP_ADDRESS,
        UNRELATED_COMPANY: UNRELATED_ADDRESS,
        DIRECTOR_PERSONAL: DIRECTOR_ADDRESS,
    }
    return addresses.get(addressed_to, COMPANY_ADDRESS)


@dataclass
class InvoiceView:
    supplier_name: str
    supplier_lines: list[str]  # address, VAT number, email
    title: str
    bill_to: list[str]  # first line is the addressee
    meta: list[tuple[str, str]]
    note: str | None
    lines: list[tuple[str, str]]
    totals: list[tuple[str, str]]
    symbol: str
    currency: str
    footer: str


def build_view(spec: InvoiceSpec) -> InvoiceView:
    supplier = spec.supplier
    currency = supplier.currency
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    when = format_date(spec.invoice_date, spec.layout, currency)
    due = format_date(spec.due_date, spec.layout, currency)
    vat_label = {
        "kestrel": "VAT (exempt, insurance)",
        "bauer": "VAT 0% (reverse charge)",
        "summit": "Sales tax (0%)",
    }.get(supplier.key, f"VAT @ {supplier.vat_rate:.0f}%")
    tax_id = "VAT Reg No" if currency == "GBP" else ("USt-IdNr / VAT" if currency == "EUR" else "Tax ID")
    title = "RECHNUNG / INVOICE" if currency == "EUR" else "INVOICE"
    return InvoiceView(
        supplier_name=supplier.name,
        supplier_lines=[*supplier.address, f"{tax_id}: {supplier.vat_number}", supplier.email],
        title=title,
        bill_to=[spec.addressed_to, *bill_to_address(spec.addressed_to)],
        meta=[
            ("Invoice No", spec.invoice_number),
            ("Invoice Date", when),
            ("Due Date", due),
            ("Customer Ref", "BRA001"),
        ],
        note=spec.period_note,
        lines=[(text, format_amount(amount)) for text, amount in spec.lines],
        totals=[
            ("Net", f"{symbol}{format_amount(spec.net)}"),
            (vat_label, f"{symbol}{format_amount(spec.vat)}"),
            ("Total due" if currency == "GBP" else f"Total ({currency})", f"{symbol}{format_amount(spec.gross)}"),
        ],
        symbol=symbol,
        currency=currency,
        footer=f"{supplier.name}. Payment terms 30 days. Please quote the invoice number with your payment.",
    )


def view_as_text(view: InvoiceView) -> str:
    """Plain-text invoice (used for the email-body invoice)."""
    out = [view.title, "", view.supplier_name, *view.supplier_lines, "", "Bill to:", *view.bill_to, ""]
    out += [f"{label}: {value}" for label, value in view.meta]
    if view.note:
        out += ["", view.note]
    out += ["", f"Description{' ' * 49}Amount ({view.currency})"]
    out += [f"{text:<60}{amount:>14}" for text, amount in view.lines]
    out += [""] + [f"{label:<60}{value:>14}" for label, value in view.totals]
    out += ["", view.footer]
    return "\n".join(out)
