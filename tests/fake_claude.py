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


class FakeBatches:
    """Stand-in for client.messages.batches. Results come back in reverse order, like the real API may."""

    def __init__(self, client: "FakeClient"):
        self.client = client
        self.created: dict[str, list[dict]] = {}
        self.polls_before_end = 1
        self.errored: set[str] = set()  # source names whose batch item errors
        self.interrupt_on_retrieve = False

    def create(self, requests):
        batch_id = f"msgbatch_{len(self.created) + 1:03d}"
        self.created[batch_id] = list(requests)
        return SimpleNamespace(id=batch_id, processing_status="in_progress")

    def retrieve(self, batch_id):
        if self.interrupt_on_retrieve:
            raise KeyboardInterrupt  # the user pressed Ctrl+C while waiting
        self.polls_before_end -= 1
        ended = self.polls_before_end < 0
        total = len(self.created[batch_id])
        counts = SimpleNamespace(processing=0 if ended else total, succeeded=total if ended else 0, errored=0,
                                 canceled=0, expired=0)  # fmt: skip
        return SimpleNamespace(id=batch_id, processing_status="ended" if ended else "in_progress",
                               request_counts=counts)  # fmt: skip

    def results(self, batch_id):
        for request in reversed(self.created[batch_id]):
            if _source_name(request["params"]) in self.errored:
                outcome = SimpleNamespace(type="errored", error=SimpleNamespace(type="api_error"))
            else:
                outcome = SimpleNamespace(type="succeeded", message=self.client.answer(request["params"]))
            yield SimpleNamespace(custom_id=request["custom_id"], result=outcome)


def _source_name(params: dict) -> str:
    source = params["messages"][0]["content"][0]["text"]
    return source.removeprefix("Source: ").rsplit(" (", 1)[0]


@dataclass
class FakeClient:
    """Answers from RESPONSES. `fail_on` names raise; `calls` records every live request's source name."""

    fail_on: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create, stream=None))
        self.batches = FakeBatches(self)
        self.messages = SimpleNamespace(batches=self.batches)

    def answer(self, params: dict):
        assert "fallbacks" not in params  # rejected by the Batches API
        return message(json.dumps(RESPONSES[_source_name(params)]))

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
