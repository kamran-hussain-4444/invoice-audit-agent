"""Emails (.eml) carrying invoices as attachments, or written in the body (PLAN 15.2)."""

from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from io import BytesIO

from PIL import Image, ImageDraw

from invoice_audit.synthetic.entities import COMPANY


def tiny_logo_png(colour: tuple[int, int, int]) -> bytes:
    """A small signature logo (< 20 KB) that discovery must skip, not treat as an invoice."""
    image = Image.new("RGB", (120, 40), colour)
    ImageDraw.Draw(image).rectangle((8, 8, 32, 32), fill=(255, 255, 255))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def build_email(
    sender_name: str,
    sender_email: str,
    subject: str,
    body: str,
    sent: datetime,
    attachments: list[tuple[str, bytes, str]],
    message_id: str,
    logo: bytes | None = None,
) -> bytes:
    """attachments = [(filename, data, mime type like "application/pdf")]."""
    message = EmailMessage()
    message["From"] = f"{sender_name} <{sender_email}>"
    message["To"] = "Accounts Payable <ap@brackenfield-eng.example>"
    message["Subject"] = subject
    message["Date"] = format_datetime(sent.replace(tzinfo=UTC))
    message["Message-ID"] = f"<{message_id}@synthetic.example>"
    message.set_content(body)
    if logo is not None:
        message.add_attachment(logo, maintype="image", subtype="png", filename="logo.png", disposition="inline")
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    # Fixed boundary so the same seed gives byte-identical files.
    message.set_boundary(f"=====boundary-{message_id}=====")
    return message.as_bytes()


def covering_note(supplier_name: str, invoice_numbers: list[str]) -> str:
    plural = "invoices" if len(invoice_numbers) > 1 else "invoice"
    return (
        f"Dear {COMPANY} accounts team,\n\n"
        f"Please find attached {plural} {', '.join(invoice_numbers)}.\n\n"
        "Kind regards,\n"
        f"Credit Control\n{supplier_name}\n"
    )
