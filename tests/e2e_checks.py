"""Shared scoring for the end-to-end tests that use real Claude output (recorded or live).

Real extraction can differ from the answer key in harmless ways, so the bar is the audit one:
every planted error must be flagged (exception or review, never a silent Pass), and only a couple of
clean invoices may be flagged unexpectedly (an auditor would clear those in minutes).
"""

import json

from tests.conftest import ROOT

ANSWER_KEY = json.loads((ROOT / "data" / "synthetic" / "answer_key.json").read_text(encoding="utf-8"))
MAX_UNEXPECTED_CLEAN = 2


def display_name(item: dict) -> str:
    name = item["file"].split("/", 1)[1]
    if item.get("attachment"):
        return f"{name} › {item['attachment']}"
    if item["format"] == "email_body":
        return f"{name} (email body)"
    return name


def score(result) -> dict:
    rows = {r.record.source.display_name: r for r in [*result.main_rows, *result.cutoff_rows]}
    missed, wrong_kind, unexpected = [], [], []
    for item in ANSWER_KEY["invoices"]:
        row = rows.get(display_name(item))
        label = f"{item['invoice_id']} {item['planted_errors'] or 'clean'} {display_name(item)}"
        if item["planted_errors"]:
            if row is None or row.overall == "pass":
                missed.append(f"{label}: {row.overall if row else 'not tested'}")
            elif row.overall != item["expected"]["overall"]:
                wrong_kind.append(f"{label}: expected {item['expected']['overall']}, got {row.overall}")
        elif row is None or row.overall != "pass":
            notes = "; ".join(c.detail for c in (row.checks if row else []) if c.status != "pass" and c.detail)
            unexpected.append(f"{label}: {row.overall if row else 'not tested'} ({notes})")
    return {"missed": missed, "wrong_kind": wrong_kind, "unexpected_clean": unexpected}


def report(scores: dict) -> str:
    lines = []
    for key, title in (("missed", "Planted errors NOT caught"), ("wrong_kind", "Caught, but as review not exception"),
                       ("unexpected_clean", "Clean invoices flagged")):  # fmt: skip
        lines.append(f"{title}: {len(scores[key])}")
        lines += [f"  - {line}" for line in scores[key]]
    return "\n".join(lines)
