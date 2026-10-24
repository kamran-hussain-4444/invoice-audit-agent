import pytest
from rapidfuzz import fuzz

from invoice_audit.matching import (
    index_ledger,
    match_addressee,
    normalise_entity_name,
    normalise_invoice_number,
)
from tests.conftest import make_line


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("inv 2231", "INV2231"), ("INV2231", "INV2231"), (" INV-2231 ", "INV-2231"), ("a\tb c", "ABC")],
)
def test_invoice_number_normalisation(raw, expected):
    assert normalise_invoice_number(raw) == expected


def test_index_groups_duplicates():
    idx = index_ledger([make_line(invoice_number="A 1"), make_line(invoice_number="a1"), make_line(invoice_number="B")])
    assert len(idx["A1"]) == 2
    assert len(idx["B"]) == 1


def test_entity_normalisation():
    assert normalise_entity_name("Brackenfield Engineering Ltd.") == "brackenfield engineering"
    assert normalise_entity_name("BRACKENFIELD ENGINEERING LIMITED") == "brackenfield engineering"
    assert normalise_entity_name("Lumen Print & Design Ltd") == "lumen print and design"
    assert normalise_entity_name("The Widget Co (UK) PLC") == "widget"


@pytest.mark.parametrize(
    "name",
    [
        "Brackenfield Engineering Ltd",
        "BRACKENFIELD ENGINEERING LIMITED",
        "Brackenfield Engineering Ltd.",
        "Brackenfield Precision",  # alias
    ],
)
def test_exact_matches(cfg, name):
    assert match_addressee(name, cfg).outcome == "exact"


def test_typo_scores_at_least_pass_threshold(cfg):
    # The planted clean control in the synthetic data relies on this being a Pass.
    score = fuzz.token_sort_ratio("brackenfeild engineering", "brackenfield engineering")
    assert score >= 92
    result = match_addressee("Brackenfeild Engineering Ltd", cfg)
    assert result.outcome == "close"
    assert result.score >= 92


def test_group_entity_is_exception(cfg):
    result = match_addressee("Brackenfield Holdings Ltd", cfg)
    assert result.outcome == "group"
    assert result.group_entity == "Brackenfield Holdings Ltd"


@pytest.mark.parametrize("name", ["Calder Mill Catering Ltd", "Mr J Brackenfield"])
def test_unrelated_entities_are_different(cfg, name):
    assert match_addressee(name, cfg).outcome == "different"


def test_borderline_is_review(cfg):
    # Similar enough to need a look (could be a different group entity), not similar enough to pass.
    result = match_addressee("Brackenfield Engineering Group", cfg)
    assert 85 <= result.score < 92, result.score
    assert result.outcome == "borderline"
