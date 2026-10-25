"""The Excel workpaper and run_results.json, built from a full offline run with the fake Claude."""

import json
import tomllib
from collections import Counter

import pytest
from openpyxl import load_workbook

from invoice_audit.config import RUN_TEMPLATE, RunConfig, load_config
from invoice_audit.pipeline import run_pipeline
from invoice_audit.workpaper import (
    CUTOFF_HEADERS,
    EXCEPTION_HEADERS,
    EXTRACTED_HEADERS,
    MAIN_HEADERS,
    write_results_json,
    write_workpaper,
)
from tests.conftest import EXAMPLE_RUN, ROOT
from tests.fake_claude import FakeClient


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("output")
    cfg = load_config(EXAMPLE_RUN, base_dir=ROOT)
    cfg.ai.cache_path = out / "cache.sqlite"
    result = run_pipeline(cfg, mode="live", client=FakeClient())
    result.workpaper_path = write_workpaper(result, out)
    write_results_json(result, out)
    return result, load_workbook(result.workpaper_path), out


def headers(ws) -> list:
    return [c.value for c in ws[1]]


def test_six_tabs_with_expected_headers(built):
    _, wb, _ = built
    assert wb.sheetnames == ["Summary", "Extracted Data", "Main Testing", "Cut-off Testing", "Exceptions",
                             "Processing Log"]  # fmt: skip
    assert headers(wb["Extracted Data"]) == EXTRACTED_HEADERS
    assert headers(wb["Main Testing"]) == MAIN_HEADERS
    assert headers(wb["Cut-off Testing"]) == CUTOFF_HEADERS
    assert headers(wb["Exceptions"]) == EXCEPTION_HEADERS


def test_file_name(built):
    result, _, _ = built
    assert result.workpaper_path.name.startswith("Brackenfield_Engineering_Ltd_FY2026_invoice_testing_")


def summary_value(ws, label):
    for row in ws.iter_rows(values_only=True):
        if row[0] == label:
            return row
    raise KeyError(label)


def test_summary_counts_match_run_result(built):
    result, wb, _ = built
    ws = wb["Summary"]
    statuses = Counter(r.status for r in result.records)
    assert summary_value(ws, "Files found")[1] == result.stats.files_found
    assert summary_value(ws, "Failed")[1] == statuses["failed"] == 1
    assert summary_value(ws, "Excluded")[1] == statuses["excluded"] == 2
    main = summary_value(ws, "Main")
    counts = Counter(r.overall for r in result.main_rows)
    assert main[1:5] == (len(result.main_rows), counts["pass"], counts["exception"], counts["review"])
    cutoff = summary_value(ws, "Cut-off")
    assert cutoff[1] == len(result.cutoff_rows) == 25
    assert summary_value(ws, "Prepared by") == ("Prepared by", None, "Date", None, None, None, None)
    text = " ".join(str(c) for row in ws.iter_rows(values_only=True) for c in row if c)
    assert "does not replace professional scepticism" in text
    assert "RSM" not in text


def test_every_exception_or_review_check_has_a_finding(built):
    result, wb, _ = built
    explanations = {row[0]: row[8] for row in wb["Exceptions"].iter_rows(min_row=2, values_only=True)}
    for row in [*result.main_rows, *result.cutoff_rows]:
        for check in row.checks:
            if check.status in ("exception", "review"):
                assert check.finding_ref in explanations
                assert explanations[check.finding_ref]


def test_fills_and_ticks(built):
    result, wb, _ = built
    ws = wb["Main Testing"]
    col = {h: i for i, h in enumerate(MAIN_HEADERS, start=1)}
    for r, row in enumerate(result.main_rows, start=2):
        overall = ws.cell(r, col["Overall result"])
        assert overall.value == row.overall.capitalize()
        expected_fill = {"pass": "C6EFCE", "exception": "FFC7CE", "review": "FFEB9C"}[row.overall]
        assert overall.fill.fgColor.rgb.endswith(expected_fill)
        assert ws.cell(r, col["A"]).value in "✓✗?–"
    assert ws.freeze_panes == "B2"
    assert ws.auto_filter.ref.startswith("A1:")


def test_resolution_dropdown(built):
    _, wb, _ = built
    ws = wb["Exceptions"]
    validations = ws.data_validations.dataValidation
    assert any('"Open,Cleared,Adjusted,Passed to ML"' == v.formula1 for v in validations)
    assert ws.cell(2, EXCEPTION_HEADERS.index("Resolution") + 1).value == "Open"


def test_processing_log_lists_problem_files(built):
    _, wb, _ = built
    files = {row[0]: row[2] for row in wb["Processing Log"].iter_rows(min_row=2, values_only=True) if row[2]}
    assert files["corrupt_file.pdf"] == "Failed"
    assert files["old_format.doc"] == "Excluded"
    assert files["supplier_statement.pdf"] == "Excluded"


def test_money_and_date_formats(built):
    _, wb, _ = built
    ws = wb["Main Testing"]
    col = {h: i for i, h in enumerate(MAIN_HEADERS, start=1)}
    assert ws.cell(2, col["Ledger amount"]).number_format == "#,##0.00"
    assert ws.cell(2, col["Invoice date"]).number_format == "DD/MM/YYYY"


def test_results_json(built):
    result, _, out = built
    data = json.loads((out / "latest_run.json").read_text(encoding="utf-8"))
    assert data["counts"]["exceptions"] == sum(1 for f in result.findings if f.status == "exception")
    assert data["counts"]["failed"] == 1
    assert len(data["main_testing"]) == len(result.main_rows)
    assert isinstance(data["findings"][0]["amount_impact"], (str, type(None)))  # Decimals as strings
    assert data["workpaper_absolute"].endswith(".xlsx")


def test_run_template_is_valid_toml_and_config():
    data = tomllib.loads(RUN_TEMPLATE)
    cfg = RunConfig.model_validate(data)
    assert cfg.ai.model == "claude-sonnet-5-5"
