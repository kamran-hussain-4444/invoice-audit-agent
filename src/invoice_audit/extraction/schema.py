"""JSON schema for structured outputs (PLAN 9.2). The category list is injected from categories.toml.

Every property is required and nullable values are typed as [type, "null"], so the model must answer every
field (null when it can't read it) rather than leaving fields out.
"""

import hashlib
import json

CONFIDENCE = {"type": "string", "enum": ["high", "medium", "low"]}
CONFIDENCE_KEYS = ["supplier_name", "addressed_to", "invoice_number", "invoice_date", "amounts", "currency",
                   "description", "service_period"]  # fmt: skip


def _nullable(kind: str, **extra) -> dict:
    return {"type": [kind, "null"], **extra}


def _date() -> dict:
    return {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}


def build_schema(category_names: list[str]) -> dict:
    properties = {
        "document_type": {
            "type": "string",
            "enum": ["invoice", "credit_note", "statement", "quote", "remittance", "other"],
        },
        "supplier_name": _nullable("string"),
        "supplier_vat_number": _nullable("string"),
        "addressed_to": _nullable("string"),
        "invoice_number": _nullable("string"),
        "invoice_date": _date(),
        "currency": _nullable("string"),
        "net_amount": _nullable("number"),
        "vat_amount": _nullable("number"),
        "gross_amount": _nullable("number"),
        "description": _nullable("string"),
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"description": {"type": "string"}, "amount": _nullable("number")},
                "required": ["description", "amount"],
                "additionalProperties": False,
            },
        },
        "delivery_date": _date(),
        "service_period_start": _date(),
        "service_period_end": _date(),
        "period_basis": {
            "type": "string",
            "enum": ["explicit_period", "delivery_date", "description_inference", "not_determinable"],
        },
        "period_reasoning": {"type": "string"},
        "suggested_category": {"type": "string", "enum": list(category_names)},
        "category_reasoning": {"type": "string"},
        "multiple_invoices_detected": {"type": "boolean"},
        "field_confidence": {
            "type": "object",
            "properties": {key: CONFIDENCE for key in CONFIDENCE_KEYS},
            "required": CONFIDENCE_KEYS,
            "additionalProperties": False,
        },
        "extraction_notes": _nullable("string"),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def schema_hash(schema: dict) -> str:
    """Stable fingerprint of the schema (sorted keys), used in the cache key."""
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()[:16]
