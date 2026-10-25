"""Replays REAL recorded Claude outputs through the full pipeline (free, runs in CI).

Recordings come from scripts/export_recorded_fixtures.py after a real run. Skipped until they exist.
"""

import json

import pytest

from invoice_audit.config import load_config
from invoice_audit.pipeline import run_pipeline
from invoice_audit.workpaper import write_workpaper
from tests.conftest import EXAMPLE_RUN, ROOT
from tests.e2e_checks import MAX_UNEXPECTED_CLEAN, report, score
from tests.fake_claude import FakeClient

RECORDED = ROOT / "tests" / "fixtures" / "recorded"
RECORDINGS = {}
if RECORDED.is_dir():
    for path in RECORDED.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        RECORDINGS[data["display_name"]] = data["response"]

pytestmark = pytest.mark.skipif(len(RECORDINGS) < 60, reason="No recorded real extractions yet (see M6)")


class RecordedClient(FakeClient):
    """Answers each request with the real response Claude gave for that document."""

    def create(self, **params):
        from tests.fake_claude import _source_name, message

        name = _source_name(params)
        self.calls.append(name)
        return message(json.dumps(RECORDINGS[name]))

    def answer(self, params):
        from tests.fake_claude import _source_name, message

        return message(json.dumps(RECORDINGS[_source_name(params)]))


def test_recorded_real_extractions_catch_every_planted_error(tmp_path):
    cfg = load_config(EXAMPLE_RUN, base_dir=ROOT)
    cfg.ai.cache_path = tmp_path / "cache.sqlite"
    result = run_pipeline(cfg, mode="live", client=RecordedClient())
    scores = score(result)
    print(report(scores))
    assert scores["missed"] == [], report(scores)
    assert len(scores["unexpected_clean"]) <= MAX_UNEXPECTED_CLEAN, report(scores)
    assert write_workpaper(result, tmp_path).is_file()
