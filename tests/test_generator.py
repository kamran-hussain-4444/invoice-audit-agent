"""The synthetic data generator is deterministic and produces the PLAN 15.2 format mix."""

import hashlib
import json
from collections import Counter

import pytest

from invoice_audit.synthetic.generate import generate
from tests.conftest import ROOT

COMMITTED = ROOT / "data" / "synthetic"


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    return out, generate(42, out)


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_seed_gives_identical_answer_key(fresh):
    out, _ = fresh
    # The committed data was generated with seed 42, so it must match a fresh run byte for byte.
    assert sha256(out / "answer_key.json") == sha256(COMMITTED / "answer_key.json")


def test_regenerated_files_are_byte_identical(fresh):
    # Same bytes = same cache key, so regenerating the data never makes the next run pay again.
    out, _ = fresh
    different = [
        path.relative_to(out).as_posix()
        for path in sorted(out.rglob("*"))
        if path.is_file()
        and path.name != "README.md"
        and path.read_bytes() != (COMMITTED / path.relative_to(out)).read_bytes()
    ]
    assert different == []


def test_format_counts(fresh):
    _, key = fresh
    formats = Counter(item["format"] for item in key["invoices"])
    assert len(key["invoices"]) == 60
    assert formats["digital_pdf"] == 17
    assert formats["scanned_pdf"] == 10
    assert formats["jpg_photo"] == 6
    assert formats["png_scan"] == 6
    assert formats["docx"] == 6
    assert formats["xlsx"] == 6
    email_invoices = [item for item in key["invoices"] if item["format"].startswith("email_")]
    assert len(email_invoices) == 9
    assert len({item["file"] for item in email_invoices}) == 8
    assert formats["email_body"] == 1


def test_split_between_tests(fresh):
    _, key = fresh
    tests = Counter(item["test"] for item in key["invoices"])
    assert tests == {"main": 35, "cutoff": 25}
    for test in ("main", "cutoff"):
        kinds = {item["format"] for item in key["invoices"] if item["test"] == test}
        assert len(kinds) >= 6, f"{test} sample should have a mix of formats"


def test_every_file_exists(fresh):
    out, key = fresh
    for item in [*key["invoices"], *key["edge_cases"]]:
        assert (out / item["file"]).is_file(), item["file"]
    assert (out / "ledger_fy2026.xlsx").is_file()
    assert (out / "ledger_post_ye.xlsx").is_file()


def test_invoice_numbers_unique(fresh):
    _, key = fresh
    numbers = [item["truth"]["invoice_number"] for item in key["invoices"]]
    assert len(numbers) == len(set(numbers))


def test_amounts_add_up(fresh):
    _, key = fresh
    from decimal import Decimal

    for item in key["invoices"]:
        t = item["truth"]
        assert Decimal(t["net_amount"]) + Decimal(t["vat_amount"]) == Decimal(t["gross_amount"]), item["invoice_id"]


def test_answer_key_is_valid_json_with_edge_cases(fresh):
    out, _ = fresh
    key = json.loads((out / "answer_key.json").read_text(encoding="utf-8"))
    statuses = {item["file"].split("/")[-1]: item["expected_status"] for item in key["edge_cases"]}
    assert statuses == {
        "corrupt_file.pdf": "failed",
        "supplier_statement.pdf": "excluded",
        "blurry_receipt.jpg": "needs_review",
        "old_format.doc": "excluded",
    }
