"""Copy real Claude extractions of the synthetic data from the cache into tests/fixtures/recorded/.

Run after a live or batch run over data/synthetic:
    uv run python scripts/export_recorded_fixtures.py

tests/test_recorded_e2e.py then replays them through the full pipeline in CI, for free.
"""

import json
from pathlib import Path

from invoice_audit.config import load_config
from invoice_audit.discovery import discover
from invoice_audit.extraction.cache import ExtractionCache, cache_key
from invoice_audit.extraction.prompt import PROMPT_VERSION
from invoice_audit.extraction.requests import make_template
from invoice_audit.loaders import LoaderError, read_bytes

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "recorded"


def main() -> None:
    cfg = load_config(ROOT / "runs" / "example_fy2026.toml", base_dir=ROOT)
    template = make_template(cfg)
    cache = ExtractionCache(cfg.ai.cache_path)
    OUT.mkdir(parents=True, exist_ok=True)
    written, missing = 0, []
    for test, folder in (("main", cfg.inputs.main_folder), ("cutoff", cfg.inputs.cutoff_folder)):
        for document in discover(folder, test).documents:
            try:
                key = cache_key(read_bytes(document), document.email_context, template)
            except LoaderError:
                continue
            hit = cache.get(key)
            if hit is None:
                missing.append(document.display_name)
                continue
            record = {
                "display_name": document.display_name,
                "test": test,
                "model": template.model,
                "prompt_version": PROMPT_VERSION,
                "mode": hit.mode,
                "usage": {"input_tokens": hit.usage.input_tokens, "output_tokens": hit.usage.output_tokens},
                "response": json.loads(hit.response_json),
            }
            safe = document.display_name.replace(" › ", "__").replace(" ", "_").replace("(", "").replace(")", "")
            (OUT / f"{test}__{safe}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                                                      encoding="utf-8", newline="\n")  # fmt: skip
            written += 1
    print(f"Wrote {written} recorded extraction(s) to {OUT.relative_to(ROOT)}")
    if missing:
        print(f"Not in the cache (skipped, except the corrupt PDF this is unexpected): {', '.join(missing)}")


if __name__ == "__main__":
    main()
