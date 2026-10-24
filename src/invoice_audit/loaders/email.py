"""Emails (.eml via the standard library, .msg via extract-msg) split into body text and attachments.

Discovery uses this to turn each supported attachment into its own document; an email with no usable
attachment is read from its body instead (some suppliers write the invoice in the email itself).
"""

import html
import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from pathlib import Path

from invoice_audit.loaders.errors import LoaderError


@dataclass
class Attachment:
    filename: str
    data: bytes
    content_type: str = ""


@dataclass
class ParsedEmail:
    subject: str
    sender: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)

    def context(self) -> str:
        """Short summary sent with each attachment so Claude knows where it came from."""
        return f"Subject: {self.subject}\nFrom: {self.sender}\n{self.body[:1000]}".strip()


def html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style).*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_eml(data: bytes) -> ParsedEmail:
    try:
        message = message_from_bytes(data, policy=policy.default)
        plain = message.get_body(preferencelist=("plain",))
        body = plain.get_content() if plain is not None else ""
        if not body.strip():  # some suppliers send HTML only (or an empty plain-text part)
            rich = message.get_body(preferencelist=("html",))
            body = html_to_text(rich.get_content()) if rich is not None else ""
        attachments = []
        for part in message.iter_attachments():
            payload = part.get_payload(decode=True)
            if part.get_content_type() == "message/rfc822":
                inner = part.get_payload()
                payload = inner[0].as_bytes() if isinstance(inner, list) and inner else payload
            if payload:
                name = part.get_filename() or f"attachment.{part.get_content_subtype()}"
                attachments.append(Attachment(name, payload, part.get_content_type()))
        return ParsedEmail(str(message["subject"] or ""), str(message["from"] or ""), body.strip(), attachments)
    except Exception:
        raise LoaderError("Corrupt or unreadable email (.eml)") from None


def parse_msg(data: bytes) -> ParsedEmail:
    import extract_msg  # imported lazily: it is slow to import and only needed for Outlook files

    try:
        message = extract_msg.openMsg(data)
    except Exception:
        raise LoaderError("Corrupt or unreadable Outlook email (.msg)") from None
    try:
        body = message.body or ""
        if not body.strip() and message.htmlBody:
            raw = message.htmlBody
            body = html_to_text(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        attachments = []
        for item in message.attachments:
            name = item.longFilename or item.shortFilename or item.name or "attachment"
            payload = item.data
            if hasattr(payload, "exportBytes"):  # an attached email
                try:
                    payload = payload.exportBytes()
                    name = Path(name).stem + ".msg"
                except Exception:
                    continue
            if isinstance(payload, bytes) and payload:
                attachments.append(Attachment(name, payload, item.mimetype or ""))
        return ParsedEmail(str(message.subject or ""), str(message.sender or ""), body.strip(), attachments)
    except Exception:
        raise LoaderError("Corrupt or unreadable Outlook email (.msg)") from None
    finally:
        message.close()


def parse_email(data: bytes, suffix: str) -> ParsedEmail:
    return parse_msg(data) if suffix.lower() == ".msg" else parse_eml(data)
