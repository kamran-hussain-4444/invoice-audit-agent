"""Build the Messages API request for one document (PLAN 9.1). Shared by live and batch mode.

Notes from the claude-api skill:
- structured outputs via `output_config.format` (JSON schema); effort also lives in `output_config`
- adaptive thinking is the default on this model when `thinking` is omitted
- no temperature/top_p/top_k (rejected by the API)
- the system prompt is identical for every invoice, so it is marked for prompt caching
"""

from dataclasses import dataclass

from pydantic import ValidationError

from invoice_audit.config import RunConfig
from invoice_audit.extraction.prompt import USER_INSTRUCTION, build_system_prompt
from invoice_audit.extraction.schema import build_schema, schema_hash
from invoice_audit.models import ContentPayload, ExtractedInvoice, TokenUsage

MAX_TOKENS = 16000
RETRY_MAX_TOKENS = 32000  # second attempt after stop_reason "max_tokens" (streamed)
MAX_LINE_ITEMS = 20


class ExtractionError(Exception):
    """Claude's answer can't be used for this document (refusal, truncated, unparseable)."""


class OutputTooLong(ExtractionError):
    """stop_reason was max_tokens: worth one retry with a bigger limit."""


def read_message(message) -> tuple[str, TokenUsage]:
    """The JSON text and token usage from a Messages API response (live or batch).

    Branches on stop_reason before reading content, as the claude-api skill requires.
    """
    usage = message.usage
    tokens = TokenUsage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_creation_tokens=usage.cache_creation_input_tokens or 0,
    )
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        category = f" ({details.category})" if details is not None and details.category else ""
        raise ExtractionError(f"Model declined to process this document{category}")
    if message.stop_reason == "max_tokens":
        raise OutputTooLong("Model output was cut off (max_tokens)")
    text = next((block.text for block in message.content if block.type == "text"), None)
    if not text:
        raise ExtractionError("Model returned no JSON")
    return text, tokens


def parse_invoice(text: str) -> ExtractedInvoice:
    try:
        invoice = ExtractedInvoice.model_validate_json(text)
    except ValidationError as e:
        raise ExtractionError(f"Could not parse model output: {e.error_count()} problem(s)") from None
    invoice.line_items = invoice.line_items[:MAX_LINE_ITEMS]  # the schema can't cap array length
    return invoice


@dataclass(frozen=True)
class RequestTemplate:
    """Everything that is the same for every document in a run."""

    model: str
    effort: str
    system_prompt: str
    schema: dict
    schema_hash: str


def make_template(cfg: RunConfig) -> RequestTemplate:
    schema = build_schema(cfg.category_names)
    return RequestTemplate(
        model=cfg.ai.model,
        effort=cfg.ai.effort,
        system_prompt=build_system_prompt(cfg.category_list),
        schema=schema,
        schema_hash=schema_hash(schema),
    )


def build_params(template: RequestTemplate, payload: ContentPayload, max_tokens: int = MAX_TOKENS) -> dict:
    return {
        "model": template.model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": template.system_prompt, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [*payload.blocks, {"type": "text", "text": USER_INSTRUCTION}]}],
        "output_config": {
            "effort": template.effort,
            "format": {"type": "json_schema", "schema": template.schema},
        },
    }
