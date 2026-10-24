"""Digital PDF invoices via reportlab, in four visual layouts so extraction isn't trivially uniform."""

from io import BytesIO

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from invoice_audit.synthetic.view import InvoiceView

WIDTH, HEIGHT = A4
MARGIN = 48

# layout → (regular font, bold font, accent colour)
STYLES = {
    0: ("Helvetica", "Helvetica-Bold", HexColor("#1F4E79")),
    1: ("Times-Roman", "Times-Bold", HexColor("#2F3E4E")),
    2: ("Helvetica", "Helvetica-Bold", HexColor("#7A3E00")),
    3: ("Helvetica", "Helvetica-Bold", HexColor("#333333")),
}
LIGHT = Color(0.92, 0.92, 0.92)


def _canvas(buffer: BytesIO) -> Canvas:
    # invariant=1 removes timestamps/IDs so the same seed gives byte-identical files
    return Canvas(buffer, pagesize=A4, invariant=1)


def _lines(c: Canvas, x: float, y: float, lines: list[str], font: str, size: float, right: bool = False) -> float:
    c.setFont(font, size)
    for line in lines:
        (c.drawRightString if right else c.drawString)(x, y, line)
        y -= size + 3
    return y


def _table(c: Canvas, view: InvoiceView, y: float, layout: int) -> float:
    regular, bold, accent = STYLES[layout]
    left, right = MARGIN, WIDTH - MARGIN
    size = 9 if layout == 3 else 10
    header_label = "Amount" if layout == 3 else f"Amount ({view.currency})"
    if layout in (0, 2):
        c.setFillColor(LIGHT if layout == 0 else accent)
        c.rect(left, y - 5, right - left, size + 9, stroke=0, fill=1)
        c.setFillColor(white if layout == 2 else accent)
    c.setFont(bold, size)
    c.drawString(left + 6, y, "Description")
    c.drawRightString(right - 6, y, header_label)
    c.setFillColorRGB(0, 0, 0)
    y -= size + 10
    if layout == 3:
        c.setDash(2, 2)
        c.line(left, y + size + 3, right, y + size + 3)
        c.setDash()
    amount_font = "Courier" if layout == 2 else regular
    for index, (text, amount) in enumerate(view.lines):
        wrapped = simpleSplit(text, regular, size, right - left - 140)
        row_height = len(wrapped) * (size + 3) + 5
        if layout == 2 and index % 2 == 1:
            c.setFillColor(Color(0.97, 0.95, 0.92))
            c.rect(left, y - row_height + size + 1, right - left, row_height, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
        _lines(c, left + 6, y, wrapped, regular, size)
        c.setFont(amount_font, size)
        c.drawRightString(right - 6, y, amount)
        if layout == 1:
            c.setStrokeColor(LIGHT)
            c.line(left, y - row_height + size + 1, right, y - row_height + size + 1)
            c.setStrokeColorRGB(0, 0, 0)
        y -= row_height
    y -= 8
    c.line(right - 220, y + 10, right, y + 10)
    for index, (label, value) in enumerate(view.totals):
        font = bold if index == len(view.totals) - 1 else regular
        c.setFont(font, size)
        c.drawString(right - 220, y - 4, label)
        c.drawRightString(right - 6, y - 4, value)
        y -= size + 8
    return y


def _footer(c: Canvas, view: InvoiceView, layout: int) -> None:
    regular = STYLES[layout][0]
    c.setFont(regular, 7.5)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    for i, line in enumerate(simpleSplit(view.footer, regular, 7.5, WIDTH - 2 * MARGIN)):
        c.drawCentredString(WIDTH / 2, 40 - i * 10, line)
    c.setFillColorRGB(0, 0, 0)


def draw_invoice(c: Canvas, view: InvoiceView, layout: int) -> None:
    regular, bold, accent = STYLES[layout]
    top = HEIGHT - MARGIN
    meta = [f"{label}: {value}" for label, value in view.meta]

    if layout == 0:  # classic: supplier top-left, title top-right
        c.setFillColor(accent)
        c.setFont(bold, 18)
        c.drawString(MARGIN, top - 10, view.supplier_name)
        c.drawRightString(WIDTH - MARGIN, top - 10, view.title)
        c.setFillColorRGB(0, 0, 0)
        _lines(c, MARGIN, top - 30, view.supplier_lines, regular, 9)
        _lines(c, WIDTH - MARGIN, top - 30, meta, regular, 10, right=True)
        c.setFont(bold, 10)
        c.drawString(MARGIN, top - 125, "Invoice to:")
        y = _lines(c, MARGIN, top - 140, view.bill_to, regular, 10)
    elif layout == 1:  # banner across the top
        c.setFillColor(accent)
        c.rect(0, HEIGHT - 95, WIDTH, 95, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont(bold, 22)
        c.drawString(MARGIN, HEIGHT - 55, view.supplier_name)
        c.setFont(regular, 14)
        c.drawRightString(WIDTH - MARGIN, HEIGHT - 55, view.title)
        c.setFillColorRGB(0, 0, 0)
        _lines(c, WIDTH - MARGIN, HEIGHT - 115, view.supplier_lines, regular, 9, right=True)
        c.setFont(bold, 11)
        c.drawString(MARGIN, HEIGHT - 115, "Bill To")
        y = _lines(c, MARGIN, HEIGHT - 130, view.bill_to, regular, 10.5)
        y -= 10
        c.rect(MARGIN, y - 4 * 14 + 4, 260, 4 * 14 + 6, stroke=1, fill=0)
        y = _lines(c, MARGIN + 8, y - 6, meta, regular, 10.5) + 4
    elif layout == 2:  # supplier block on the right, big title on the left
        c.setFont(bold, 28)
        c.setFillColor(accent)
        c.drawString(MARGIN, top - 20, view.title.title())
        c.setFillColorRGB(0, 0, 0)
        c.setFont(bold, 12)
        c.drawRightString(WIDTH - MARGIN, top - 10, view.supplier_name)
        _lines(c, WIDTH - MARGIN, top - 26, view.supplier_lines, regular, 9, right=True)
        c.setFont(bold, 10)
        c.drawString(MARGIN, top - 120, "Customer")
        c.rect(MARGIN - 4, top - 132 - 5 * 13, 230, 5 * 13 + 8, stroke=1, fill=0)
        _lines(c, MARGIN, top - 134, view.bill_to, regular, 10)
        y = _lines(c, WIDTH - MARGIN, top - 134, meta, "Courier", 10, right=True)
        y = min(y, top - 215)
    else:  # minimal, centred
        c.setFont(bold, 16)
        c.drawCentredString(WIDTH / 2, top - 10, view.supplier_name)
        c.setFont(regular, 8.5)
        c.drawCentredString(WIDTH / 2, top - 26, " | ".join(view.supplier_lines))
        c.setFont(bold, 13)
        c.drawCentredString(WIDTH / 2, top - 60, view.title.title())
        c.setFont(regular, 9)
        c.drawCentredString(WIDTH / 2, top - 78, "    ".join(meta))
        c.setFont(bold, 9)
        c.drawString(MARGIN, top - 110, "To:")
        y = _lines(c, MARGIN + 24, top - 110, view.bill_to, regular, 9)

    y -= 18
    if view.note:
        c.setFont(bold if layout != 3 else regular, 10)
        c.drawString(MARGIN, y, view.note)
        y -= 22
    _table(c, view, y, layout)
    _footer(c, view, layout)


def render_invoice_pdf(view: InvoiceView, layout: int) -> bytes:
    buffer = BytesIO()
    c = _canvas(buffer)
    c.setTitle(f"Invoice {view.meta[0][1]}")
    draw_invoice(c, view, layout)
    c.showPage()
    c.save()
    return buffer.getvalue()


def render_statement_pdf(supplier_name: str, supplier_lines: list[str], customer: list[str],
                         rows: list[tuple[str, str, str, str]], as_at: str, balance: str) -> bytes:  # fmt: skip
    """A supplier statement of account (an edge case: it is NOT an invoice and must be excluded)."""
    buffer = BytesIO()
    c = _canvas(buffer)
    top = HEIGHT - MARGIN
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, top - 10, supplier_name)
    _lines(c, MARGIN, top - 28, supplier_lines, "Helvetica", 9)
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(WIDTH - MARGIN, top - 100, "STATEMENT OF ACCOUNT")
    _lines(c, WIDTH - MARGIN, top - 118, [f"Statement date: {as_at}", "Account: BRA001"], "Helvetica", 10, True)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top - 150, "Account holder:")
    y = _lines(c, MARGIN, top - 165, customer, "Helvetica", 10) - 20
    c.setFont("Helvetica-Bold", 10)
    for x, label in zip((MARGIN, MARGIN + 90, MARGIN + 220), ("Date", "Reference", "Details"), strict=True):
        c.drawString(x, y, label)
    c.drawRightString(WIDTH - MARGIN, y, "Amount (£)")
    y -= 18
    c.setFont("Helvetica", 10)
    for when, ref, details, amount in rows:
        c.drawString(MARGIN, y, when)
        c.drawString(MARGIN + 90, y, ref)
        c.drawString(MARGIN + 220, y, details)
        c.drawRightString(WIDTH - MARGIN, y, amount)
        y -= 16
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN + 220, y - 10, "Balance outstanding")
    c.drawRightString(WIDTH - MARGIN, y - 10, balance)
    c.setFont("Helvetica", 8)
    c.drawCentredString(WIDTH / 2, 40, "This is a statement of account, not a VAT invoice. Please pay the balance.")
    c.showPage()
    c.save()
    return buffer.getvalue()
