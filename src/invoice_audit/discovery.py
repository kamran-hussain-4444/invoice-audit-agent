"""Walk the sample folders and list every document to extract (PLAN section 7, discovery rules).

Emails are opened here: each supported attachment becomes its own document. Anything that can't be
used becomes an excluded/failed record for the Processing Log, so nothing silently disappears.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from invoice_audit.loaders.email import ParsedEmail, parse_email
from invoice_audit.loaders.errors import LoaderError
from invoice_audit.models import ExtractionRecord, SourceDocument, TestName

KINDS = {".pdf": "pdf", ".jpg": "image", ".jpeg": "image", ".png": "image", ".tif": "image", ".tiff": "image",
         ".webp": "image", ".docx": "docx", ".xlsx": "xlsx"}  # fmt: skip
EMAIL_SUFFIXES = {".eml", ".msg"}
IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
SMALL_IMAGE_BYTES = 20_000  # logos and signature images, not invoices
ADVICE = {".doc": "Save as .docx or PDF and re-run.", ".xls": "Save as .xlsx or PDF and re-run.",
          ".heic": "Save as JPG and re-run.", ".zip": "Unzip it into the folder and re-run."}  # fmt: skip


@dataclass
class Discovery:
    documents: list[SourceDocument] = field(default_factory=list)
    skipped: list[ExtractionRecord] = field(default_factory=list)  # excluded or failed before extraction
    files_found: int = 0


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _ignored(path: Path) -> bool:
    name = path.name
    return name.startswith((".", "~$")) or name.lower() in IGNORED_NAMES


def _skip(result: Discovery, test: TestName, path: Path, display: str, status: str, reason: str) -> None:
    source = SourceDocument(doc_id=f"skip-{len(result.skipped) + 1}", test=test, file_path=path,
                            display_name=display, kind="other")  # fmt: skip
    result.skipped.append(ExtractionRecord(source=source, status=status, reasons=[reason]))


def _unsupported(suffix: str) -> str:
    return f"Unsupported file type {suffix or '(none)'}. {ADVICE.get(suffix, 'Save as PDF and re-run.')}"


def _add_email(result: Discovery, test: TestName, path: Path, display: str, data: bytes, depth: int) -> None:
    try:
        parsed: ParsedEmail = parse_email(data, Path(display).suffix)
    except LoaderError as e:
        _skip(result, test, path, display, "failed", str(e))
        return

    email_hash = _hash(data)
    used = 0
    for index, attachment in enumerate(parsed.attachments, start=1):
        name = attachment.filename
        suffix = Path(name).suffix.lower()
        child = f"{display} › {name}"
        if suffix in EMAIL_SUFFIXES and depth == 0:
            _add_email(result, test, path, child, attachment.data, depth + 1)  # attached email, one level deep
            used += 1
        elif suffix in KINDS:
            if KINDS[suffix] == "image" and len(attachment.data) < SMALL_IMAGE_BYTES:
                continue  # inline logo or signature image
            result.documents.append(
                SourceDocument(
                    doc_id=f"{_hash(attachment.data)}-a{index}",
                    test=test,
                    file_path=path,
                    display_name=child,
                    kind=KINDS[suffix],
                    content_bytes=attachment.data,
                    email_context=parsed.context(),
                )
            )
            used += 1
        else:
            _skip(result, test, path, child, "excluded", _unsupported(suffix))

    if used == 0:
        # No usable attachment: the invoice may be written in the email itself.
        body = f"Subject: {parsed.subject}\nFrom: {parsed.sender}\n\n{parsed.body}"
        result.documents.append(
            SourceDocument(
                doc_id=f"{email_hash}-body",
                test=test,
                file_path=path,
                display_name=f"{display} (email body)",
                kind="email_body",
                content_bytes=body.encode("utf-8"),
            )
        )


def discover(folder: Path, test: TestName, limit: int | None = None) -> Discovery:
    """Every document in `folder` (recursively, sorted by path). `limit` keeps the first N documents."""
    result = Discovery()
    files = sorted((p for p in folder.rglob("*") if p.is_file()), key=lambda p: p.relative_to(folder).as_posix())
    for path in files:
        relative = path.relative_to(folder)
        if any(_ignored(Path(part)) for part in relative.parts):
            continue
        result.files_found += 1
        display = relative.as_posix()
        suffix = path.suffix.lower()
        if suffix not in KINDS and suffix not in EMAIL_SUFFIXES:
            _skip(result, test, path, display, "excluded", _unsupported(suffix))
            continue
        try:
            data = path.read_bytes()
        except OSError as e:
            _skip(result, test, path, display, "failed", f"Could not open file: {e.strerror or e}")
            continue
        if suffix in EMAIL_SUFFIXES:
            _add_email(result, test, path, display, data, depth=0)
        else:
            result.documents.append(
                SourceDocument(doc_id=_hash(data), test=test, file_path=path, display_name=display, kind=KINDS[suffix])
            )

    # The same file twice (e.g. a copy) must still get unique ids: they double as Batches API custom_ids.
    seen: dict[str, int] = {}
    for document in result.documents:
        count = seen.get(document.doc_id, 0)
        seen[document.doc_id] = count + 1
        if count:
            document.doc_id = f"{document.doc_id}-{count + 1}"

    if limit is not None:
        result.documents = result.documents[:limit]
    return result
