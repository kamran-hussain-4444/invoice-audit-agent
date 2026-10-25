"""REAL API end-to-end test. Costs money (about $0.50 in batch mode), so it never runs by default.

Run manually:  uv run pytest -m live -s
"""

import pytest

from invoice_audit.config import load_config
from invoice_audit.pipeline import run_pipeline
from tests.conftest import EXAMPLE_RUN, ROOT
from tests.e2e_checks import MAX_UNEXPECTED_CLEAN, report, score

pytestmark = pytest.mark.live


def test_live_extraction_catches_every_planted_error(tmp_path):
    cfg = load_config(EXAMPLE_RUN, base_dir=ROOT)
    cfg.ai.cache_path = tmp_path / "fresh_cache.sqlite"  # force real extraction of every document
    result = run_pipeline(cfg, mode="batch")
    scores = score(result)
    print(report(scores))
    print(f"Cost: ${result.stats.cost_usd:.4f} for {result.stats.documents} documents")
    assert scores["missed"] == [], report(scores)
    if len(scores["unexpected_clean"]) > MAX_UNEXPECTED_CLEAN:
        pytest.fail(f"More than {MAX_UNEXPECTED_CLEAN} clean invoices flagged:\n{report(scores)}")
