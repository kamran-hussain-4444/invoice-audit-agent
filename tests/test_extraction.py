"""Prompt, schema, request building, response reading, cache and cost. All offline."""

import json
from decimal import Decimal

import pytest

from invoice_audit.extraction import prompt as prompt_module
from invoice_audit.extraction.cache import ExtractionCache, cache_key
from invoice_audit.extraction.cost import estimate_cost, usage_cost
from invoice_audit.extraction.requests import (
    ExtractionError,
    OutputTooLong,
    build_params,
    make_template,
    parse_invoice,
    read_message,
)
from invoice_audit.extraction.schema import build_schema
from invoice_audit.models import ContentPayload, TokenUsage
from tests.fake_claude import message, truth_response


def test_schema_has_every_field_required_and_closed(cfg):
    schema = build_schema(cfg.category_names)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["suggested_category"]["enum"] == cfg.category_names
    assert schema["properties"]["invoice_number"]["type"] == ["string", "null"]
    item = schema["properties"]["line_items"]["items"]
    assert item["additionalProperties"] is False


def test_system_prompt_lists_categories_with_hints(cfg):
    template = make_template(cfg)
    assert "Never guess" in template.system_prompt
    assert "- Marketing: Advertising, trade shows" in template.system_prompt
    assert "{categories}" not in template.system_prompt


def test_params(cfg):
    template = make_template(cfg)
    payload = ContentPayload(blocks=[{"type": "text", "text": "Source: a.pdf (PDF)"}], approx_bytes=10)
    params = build_params(template, payload)
    assert params["model"] == "claude-sonnet-5-5"
    assert params["max_tokens"] == 16000
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["output_config"]["effort"] == "medium"
    assert params["output_config"]["format"]["schema"] == template.schema
    content = params["messages"][0]["content"]
    assert content[0]["text"] == "Source: a.pdf (PDF)"
    assert content[-1]["text"] == "Extract the invoice data as specified."
    for banned in ("temperature", "top_p", "top_k", "thinking"):
        assert banned not in params


def test_read_message_skips_thinking_blocks():
    text, usage = read_message(message('{"a": 1}', input_tokens=10, output_tokens=5))
    assert text == '{"a": 1}'
    assert usage == TokenUsage(10, 5, 2000, 0)


def test_refusal_is_an_error():
    with pytest.raises(ExtractionError, match=r"declined to process this document \(cyber\)"):
        read_message(message(None, stop_reason="refusal"))


def test_max_tokens_is_retryable():
    with pytest.raises(OutputTooLong):
        read_message(message('{"partial', stop_reason="max_tokens"))


def test_parse_invoice_converts_amounts_exactly():
    data = truth_response({"invoice_number": "X1", "net_amount": "1243.50", "vat_amount": "248.70",
                           "gross_amount": "1492.20", "invoice_date": "2025-11-03"})  # fmt: skip
    data["line_items"] = [{"description": f"line {i}", "amount": 1.1} for i in range(30)]
    invoice = parse_invoice(json.dumps(data))
    assert invoice.net_amount == Decimal("1243.50")
    assert invoice.line_items[0].amount == Decimal("1.10")
    assert len(invoice.line_items) == 20


def test_parse_invoice_rejects_garbage():
    with pytest.raises(ExtractionError, match="Could not parse"):
        parse_invoice('{"document_type": "invoice"}')


# ---------------------------------------------------------------- cache


def test_cache_miss_store_hit(tmp_path, cfg):
    template = make_template(cfg)
    cache = ExtractionCache(tmp_path / "c.sqlite")
    key = cache_key(b"pdf bytes", None, template)
    assert cache.get(key) is None
    cache.put(key, "a.pdf", template.model, '{"x": 1}', TokenUsage(100, 20, 5), "live")
    hit = cache.get(key)
    assert hit.response_json == '{"x": 1}'
    assert hit.usage.input_tokens == 100
    assert cache.stats()["entries"] == 1
    assert cache.clear() == 1
    assert cache.get(key) is None


def test_cache_key_changes_with_model_prompt_and_context(cfg, monkeypatch):
    template = make_template(cfg)
    base = cache_key(b"pdf", None, template)
    assert cache_key(b"pdf", None, template) == base
    assert cache_key(b"pdf2", None, template) != base
    assert cache_key(b"pdf", "Subject: x", template) != base
    cfg.ai.model = "claude-opus-5-5"
    assert cache_key(b"pdf", None, make_template(cfg)) != base
    monkeypatch.setattr("invoice_audit.extraction.cache.PROMPT_VERSION", "999")
    assert cache_key(b"pdf", None, template) != base


def test_prompt_version_is_set():
    assert prompt_module.PROMPT_VERSION


# ---------------------------------------------------------------- cost


def test_usage_cost_and_batch_discount(cfg):
    pricing = cfg.ai.pricing  # $2 in, $10 out, $0.20 cache read per million
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=1_000_000)
    assert usage_cost(usage, pricing) == Decimal("3.20")
    assert usage_cost(usage, pricing, batch=True) == Decimal("1.60")


def test_estimate(cfg):
    # 10 docs × (3,000 in × $2 + 1,000 out × $10) / 1M = $0.16
    assert estimate_cost(10, cfg.ai.pricing, batch=False) == Decimal("0.16")
    assert estimate_cost(10, cfg.ai.pricing, batch=True) == Decimal("0.08")
