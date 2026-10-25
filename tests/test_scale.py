"""The --scale generator keeps the planted-error ratios, and its expectations hold through the audit tests."""

import json
from collections import Counter

import pytest

from invoice_audit.config import load_config
from invoice_audit.ledger import load_ledger
from invoice_audit.matching import index_ledger
from invoice_audit.procedures.cutoff import run_cutoff_testing
from invoice_audit.procedures.main_testing import run_main_testing
from invoice_audit.synthetic.scale import generate_scale
from tests.conftest import ROOT
from tests.test_planted_errors import to_record

N = 70


@pytest.fixture(scope="module")
def scaled(tmp_path_factory):
    out = tmp_path_factory.mktemp("scale")
    return out, generate_scale(N, 7, out)


def test_counts_and_unique_numbers(scaled):
    out, key = scaled
    tests = Counter(i["test"] for i in key["invoices"])
    assert tests == {"main": 41, "cutoff": 29}
    numbers = [i["truth"]["invoice_number"] for i in key["invoices"]]
    assert len(numbers) == len(set(numbers))
    assert all((out / i["file"]).is_file() for i in key["invoices"])
    for item in key["invoices"]:  # only emails have an attachment name
        assert (item["attachment"] is not None) == item["format"].startswith("email_"), item
    assert (out / "run.toml").is_file()


def test_every_planted_error_appears(scaled):
    _, key = scaled
    planted = Counter(e for i in key["invoices"] for e in i["planted_errors"])
    assert set(planted) == {f"E{n:02d}" for n in range(1, 17)} | {f"C{n:02d}" for n in range(1, 13)}


def test_expected_results_hold_on_scaled_ledgers(scaled):
    out, key = scaled
    run_file = out / "run.toml"
    cfg = load_config(run_file, base_dir=ROOT, check_files=True)  # data paths are absolute (temp folder)
    current = index_ledger(load_ledger(cfg.inputs.current_ledger, "current", cfg))
    post_ye = index_ledger(load_ledger(cfg.inputs.post_ye_ledger, "post_ye", cfg))
    records = [to_record(item, item["invoice_id"]) for item in key["invoices"]]
    rows = run_main_testing([r for r in records if r.source.test == "main"], current, post_ye, cfg)
    rows += run_cutoff_testing([r for r in records if r.source.test == "cutoff"], current, post_ye, cfg)
    by_id = {row.record.source.doc_id: row for row in rows}
    wrong = []
    for item in key["invoices"]:
        row = by_id[item["invoice_id"]]
        if row.overall != item["expected"]["overall"]:
            wrong.append((item["invoice_id"], item["planted_errors"], row.overall, item["expected"]["overall"]))
    assert wrong == []


def test_answer_key_written(scaled):
    out, _ = scaled
    assert json.loads((out / "answer_key.json").read_text(encoding="utf-8"))["seed"] == 7
