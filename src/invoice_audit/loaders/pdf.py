"""PDFs are sent to Claude as-is (it reads digital and scanned PDFs). pypdf only checks they are usable."""

import base64
from io import BytesIO

from pypdf import PdfReader

from invoice_audit.loaders.errors import LoaderError, NeedsReviewWithoutExtraction

MAX_PDF_BYTES = 30 * 1024 * 1024  # API request limit is 32 MB including everything else


def check_pdf(data: bytes, max_pages: int) -> int:
    """Return the page count, or raise if the PDF can't or shouldn't be sent."""
    if len(data) > MAX_PDF_BYTES:
        raise LoaderError(f"PDF is larger than 30 MB ({len(data) / 1024 / 1024:.0f} MB). Compress or split it.")
    if not data.startswith(b"%PDF") or b"%%EOF" not in data[-2048:]:
        # pypdf can "repair" a truncated file and silently read part of it; we'd rather not guess.
        raise LoaderError("Corrupt or unreadable PDF")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise LoaderError("Password-protected PDF")
        pages = len(reader.pages)
        if pages:
            reader.pages[0].mediabox  # noqa: B018 - touching the first page catches broken page trees
    except LoaderError:
        raise
    except Exception:
        raise LoaderError("Corrupt or unreadable PDF") from None
    if pages == 0:
        raise LoaderError("PDF has no pages")
    if pages > max_pages:
        raise NeedsReviewWithoutExtraction(
            f"PDF has {pages} pages (limit {max_pages}). It may contain several invoices. Split manually and re-run."
        )
    return pages


def pdf_blocks(data: bytes, max_pages: int) -> list[dict]:
    check_pdf(data, max_pages)
    return [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        }
    ]
