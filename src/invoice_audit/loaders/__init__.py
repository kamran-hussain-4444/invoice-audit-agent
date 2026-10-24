"""Turn a SourceDocument into the content blocks sent to Claude (PLAN section 8).

PDFs and images go to Claude as they are (no local OCR). Word, Excel and email bodies are converted to
text locally. Every payload starts with a short "Source: ..." line so the model knows what it is reading.
"""

from invoice_audit.config import RunConfig
from invoice_audit.loaders.errors import LoaderError, NeedsReviewWithoutExtraction
from invoice_audit.loaders.excel import xlsx_text
from invoice_audit.loaders.image import image_blocks
from invoice_audit.loaders.pdf import pdf_blocks
from invoice_audit.loaders.word import docx_text
from invoice_audit.models import ContentPayload, SourceDocument

__all__ = ["LoaderError", "NeedsReviewWithoutExtraction", "load", "read_bytes"]

KIND_LABELS = {"pdf": "PDF", "image": "image", "docx": "Word document", "xlsx": "Excel workbook",
               "email_body": "email body"}  # fmt: skip


def read_bytes(source: SourceDocument) -> bytes:
    if source.content_bytes is not None:
        return source.content_bytes
    try:
        return source.file_path.read_bytes()
    except OSError as e:
        raise LoaderError(f"Could not open file: {e.strerror or e}") from None


def _approx_bytes(blocks: list[dict]) -> int:
    total = 0
    for block in blocks:
        total += len(block.get("text", "")) + len(block.get("source", {}).get("data", ""))
    return total


def load(source: SourceDocument, cfg: RunConfig) -> ContentPayload:
    """Raises LoaderError (→ failed) or NeedsReviewWithoutExtraction (→ needs review, no API call)."""
    data = read_bytes(source)
    if source.kind == "pdf":
        content = pdf_blocks(data, cfg.ai.max_pdf_pages)
    elif source.kind == "image":
        content = image_blocks(data, cfg.ai.image_max_edge)
    elif source.kind == "docx":
        content = [{"type": "text", "text": docx_text(data)}]
    elif source.kind == "xlsx":
        content = [{"type": "text", "text": xlsx_text(data)}]
    elif source.kind == "email_body":
        text = data.decode("utf-8", "replace").strip()
        if not text:
            raise LoaderError("Email has no attachment and an empty body")
        content = [{"type": "text", "text": text}]
    else:
        raise LoaderError(f"No loader for {source.kind}")

    blocks = [{"type": "text", "text": f"Source: {source.display_name} ({KIND_LABELS[source.kind]})"}]
    if source.email_context and source.kind != "email_body":
        blocks.append({"type": "text", "text": f"Email context:\n{source.email_context}"})
    blocks += content
    return ContentPayload(blocks=blocks, approx_bytes=_approx_bytes(blocks))
