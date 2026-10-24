"""Word invoices: supplier details in the page header, line items in a table (PLAN 15.2)."""

from datetime import datetime
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from invoice_audit.synthetic.view import InvoiceView

FIXED_TIME = datetime(2026, 1, 1, 9, 0, 0)  # document properties, so files don't change between runs


def render_invoice_docx(view: InvoiceView) -> bytes:
    doc = Document()
    props = doc.core_properties
    props.author = view.supplier_name
    props.created = props.modified = FIXED_TIME
    props.last_modified_by = view.supplier_name
    props.revision = 1

    header = doc.sections[0].header
    first = header.paragraphs[0]
    run = first.add_run(view.supplier_name)
    run.bold = True
    run.font.size = Pt(14)
    header.add_paragraph(" · ".join(view.supplier_lines)).runs[0].font.size = Pt(8)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    title_run = title.add_run(view.title)
    title_run.bold = True
    title_run.font.size = Pt(20)

    doc.add_paragraph().add_run("Invoice to:").bold = True
    for line in view.bill_to:
        doc.add_paragraph(line).paragraph_format.space_after = Pt(0)
    doc.add_paragraph()
    for label, value in view.meta:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.add_run(f"{label}: ").bold = True
        p.add_run(value)
    if view.note:
        doc.add_paragraph().add_run(view.note).italic = True

    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    table.rows[0].cells[0].text = "Description"
    table.rows[0].cells[1].text = f"Amount ({view.currency})"
    for text, amount in view.lines:
        cells = table.add_row().cells
        cells[0].text = text
        cells[1].text = amount
        cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for label, value in view.totals:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
        cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    doc.sections[0].footer.paragraphs[0].text = view.footer
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
