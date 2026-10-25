"""A stand-in for the Anthropic client, so pipeline tests run offline and free.

It reads the "Source: <name>" line the loaders put at the top of every request and answers with the
answer key's truth for that document, shaped like a real Messages API response.
"""

import json
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace

from tests.conftest import ROOT

ANSWER_KEY = json.loads((ROOT / "data" / "synthetic" / "answer_key.json").read_text(encoding="utf-8"))


def _display_name(item: dict) -> str:
    folder, name = item["file"].split("/", 1)
    if item.get("attachment"):
        return f"{name} › {item['attachment']}"
    if item["format"] == "email_body":
        return f"{name} (email body)"
    return name


def truth_response(truth: dict, low_confidence=()) -> dict:
    keys = ["supplier_name", "addressed_to", "invoice_number", "invoice_date", "amounts", "currency", "description",
            "service_period"]  # fmt: skip
    number = lambda v: float(v) if v is not None else None  # noqa: E731 - JSON numbers, like the real model
    return {
        "document_type": truth.get("document_type", "invoice"),
        "supplier_name": truth.get("supplier_name"),
        "supplier_vat_number": truth.get("supplier_vat_number"),
        "addressed_to": truth.get("addressed_to"),
        "invoice_number": truth.get("invoice_number"),
        "invoice_date": truth.get("invoice_date"),
        "currency": truth.get("currency"),
        "net_amount": number(truth.get("net_amount")),
        "vat_amount": number(truth.get("vat_amount")),
        "gross_amount": number(truth.get("gross_amount")),
        "description": truth.get("description"),
        "line_items": [],
        "delivery_date": truth.get("delivery_date"),
        "service_period_start": truth.get("service_period_start"),
        "service_period_end": truth.get("service_period_end"),
        "period_basis": truth.get("period_basis", "not_determinable"),
        "period_reasoning": "Fake.",
        "suggested_category": truth.get("true_category", "Administrative expenses"),
        "category_reasoning": "Fake.",
        "multiple_invoices_detected": False,
        "field_confidence": {k: "low" if k in low_confidence else "high" for k in keys},
        "extraction_notes": None,
    }


RESPONSES = {_display_name(item): truth_response(item["truth"]) for item in ANSWER_KEY["invoices"]}
for edge in ANSWER_KEY["edge_cases"]:
    if edge["truth"]:
        RESPONSES[edge["file"].split("/", 1)[1]] = truth_response(edge["truth"], edge.get("low_confidence", ()))


def message(text: str | None, stop_reason: str = "end_turn", input_tokens: int = 3000, output_tokens: int = 800):
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=2000,
                            cache_creation_input_tokens=0)  # fmt: skip
    details = SimpleNamespace(category="cyber") if stop_reason == "refusal" else None
    return SimpleNamespace(stop_reason=stop_reason, content=content, usage=usage, stop_details=details)


@dataclass
class FakeClient:
    """Answers from RESPONSES. `fail_on` names raise; `calls` records every request's source name."""

    fail_on: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create, stream=None))

    def create(self, **params):
        source = params["messages"][0]["content"][0]["text"]
        name = source.removeprefix("Source: ").rsplit(" (", 1)[0]
        with self._lock:
            self.calls.append(name)
        assert "temperature" not in params and "top_p" not in params
        assert params["output_config"]["format"]["type"] == "json_schema"
        if name in self.fail_on:
            raise RuntimeError("simulated API failure")
        return message(json.dumps(RESPONSES[name]))
