"""Invoice-number lookup and addressee matching (PLAN sections 6 D6, D23 and 11.1)."""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from invoice_audit.config import RunConfig
from invoice_audit.models import LedgerLine

# Words that say nothing about *which* entity it is ("Ltd" vs "Limited" must not cause an exception).
_FILLER_WORDS = {"limited", "ltd", "plc", "llp", "llc", "inc", "the", "co", "company", "uk"}


def normalise_invoice_number(number: str) -> str:
    """Light normalisation only: "inv 2231" and "INV2231" are the same invoice."""
    return re.sub(r"\s+", "", number).upper()


def index_ledger(lines: list[LedgerLine]) -> dict[str, list[LedgerLine]]:
    """Ledger lines grouped by normalised invoice number."""
    index: dict[str, list[LedgerLine]] = defaultdict(list)
    for line in lines:
        index[line.invoice_number_norm].append(line)
    return dict(index)


def normalise_entity_name(name: str) -> str:
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if w not in _FILLER_WORDS]
    return " ".join(words)


@dataclass
class AddresseeMatch:
    outcome: Literal["exact", "close", "group", "borderline", "different"]
    score: float
    group_entity: str | None = None


def match_addressee(addressed_to: str, cfg: RunConfig) -> AddresseeMatch:
    """Compare the invoice's bill-to name with the audited entity (and its aliases)."""
    engagement = cfg.engagement
    target = normalise_entity_name(addressed_to)
    own_names = [normalise_entity_name(n) for n in [engagement.company_name, *engagement.company_aliases]]

    if target in own_names:
        return AddresseeMatch("exact", 100.0)

    score = max(fuzz.token_sort_ratio(target, own) for own in own_names)
    if score >= cfg.matching.addressee_pass_score:
        return AddresseeMatch("close", score)
    for group_name in engagement.group_entities:
        if target == normalise_entity_name(group_name):
            return AddresseeMatch("group", score, group_entity=group_name)
    if score >= cfg.matching.addressee_review_score:
        return AddresseeMatch("borderline", score)
    return AddresseeMatch("different", score)
