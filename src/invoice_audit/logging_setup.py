"""Detailed run log at logs/run_YYYYMMDD_HHMMSS.log (tracebacks go here, not to the console)."""

import logging
from datetime import datetime
from pathlib import Path


def start_run_log(folder: Path, started: datetime) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"run_{started:%Y%m%d_%H%M%S}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger("invoice_audit")
    root.setLevel(logging.INFO)
    for old in [h for h in root.handlers if isinstance(h, logging.FileHandler)]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)
    return path
