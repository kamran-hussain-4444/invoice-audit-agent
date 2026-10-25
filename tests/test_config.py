from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_audit.config import ConfigError, load_categories, load_config, normalise_nominal_code
from tests.conftest import EXAMPLE_RUN, ROOT


def write_run(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "run.toml"
    path.write_text(text, encoding="utf-8")
    return path


def example_text() -> str:
    return EXAMPLE_RUN.read_text(encoding="utf-8")


def test_example_run_file_loads(cfg):
    assert cfg.engagement.company_name == "Brackenfield Engineering Ltd"
    assert cfg.engagement.fy_start == date(2025, 4, 1)
    assert cfg.engagement.fy_end == date(2026, 3, 31)
    assert cfg.tests.run == ["main", "cutoff"]
    assert cfg.amount_basis == "net"
    assert cfg.matching.value_tolerance == Decimal("0.00")
    assert cfg.ai.model == "claude-sonnet-5-5"
    assert cfg.ai.pricing.input == Decimal("2.0")
    # relative paths are resolved against the project folder
    assert cfg.inputs.current_ledger == ROOT / "data" / "synthetic" / "ledger_fy2026.xlsx"


def test_categories_load_and_map_codes(cfg):
    assert len(cfg.category_list) == 11
    assert cfg.category_for_code("6800") == "Administrative expenses"
    assert cfg.category_for_code("6100") == "Marketing"
    assert cfg.category_for_code("30") == "Fixed assets (capital)"  # Excel dropped the leading zeros
    assert cfg.category_for_code("9999") is None


def test_ap_listing_compares_gross(tmp_path):
    text = example_text().replace('ledger_type    = "purchase_ledger"', 'ledger_type    = "ap_listing"')
    cfg = load_config(write_run(tmp_path, text), base_dir=ROOT, check_files=False)
    assert cfg.amount_basis == "gross"


def test_fy_end_before_start_rejected(tmp_path):
    text = example_text().replace("fy_end   = 2026-03-31", "fy_end   = 2025-03-31")
    with pytest.raises(ConfigError, match="fy_end"):
        load_config(write_run(tmp_path, text), base_dir=ROOT, check_files=False)


def test_typo_in_key_rejected(tmp_path):
    text = example_text().replace("company_name ", "company_nme ")
    with pytest.raises(ConfigError, match="company_nme"):
        load_config(write_run(tmp_path, text), base_dir=ROOT, check_files=False)


def test_cutoff_needs_post_ye_ledger(tmp_path):
    text = example_text().replace('post_ye_ledger = "data/synthetic/ledger_post_ye.xlsx"', 'post_ye_ledger = ""')
    with pytest.raises(ConfigError, match="post_ye_ledger is required"):
        load_config(write_run(tmp_path, text), base_dir=ROOT, check_files=False)


def test_main_only_does_not_need_cutoff_inputs(tmp_path):
    text = example_text().replace('run = ["main", "cutoff"]', 'run = ["main"]')
    text = text.replace('post_ye_ledger = "data/synthetic/ledger_post_ye.xlsx"', 'post_ye_ledger = ""')
    cfg = load_config(write_run(tmp_path, text), base_dir=ROOT, check_files=False)
    assert cfg.inputs.post_ye_ledger is None


def copy_categories(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "categories.toml").write_text(
        (ROOT / "config" / "categories.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )


def test_missing_folder_and_ledger_give_clear_error(tmp_path):
    copy_categories(tmp_path)
    with pytest.raises(ConfigError) as excinfo:
        load_config(write_run(tmp_path, example_text()), base_dir=tmp_path, check_files=True)
    message = str(excinfo.value)
    assert "inputs.main_folder: folder not found" in message
    assert "inputs.current_ledger: file not found" in message


def test_existing_inputs_pass_check(tmp_path):
    copy_categories(tmp_path)
    synthetic = tmp_path / "data" / "synthetic"
    (synthetic / "main_sample").mkdir(parents=True)
    (synthetic / "cutoff_sample").mkdir()
    (synthetic / "ledger_fy2026.xlsx").write_bytes(b"")
    (synthetic / "ledger_post_ye.xlsx").write_bytes(b"")
    cfg = load_config(write_run(tmp_path, example_text()), base_dir=tmp_path, check_files=True)
    assert cfg.inputs.main_folder == synthetic / "main_sample"


def test_settings_file_not_found(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write_run(tmp_path, "this is = = not toml"), check_files=False)


def test_duplicate_category_name_rejected(tmp_path):
    path = tmp_path / "cats.toml"
    path.write_text('[[category]]\nname = "A"\n[[category]]\nname = "A"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="more than once"):
        load_categories(path)


def test_nominal_code_in_two_categories_rejected(tmp_path):
    path = tmp_path / "cats.toml"
    path.write_text(
        '[[category]]\nname = "A"\nnominal_codes = ["6100"]\n[[category]]\nname = "B"\nnominal_codes = ["6100"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="6100"):
        load_categories(path)


def test_power_automate_settings_files(tmp_path):
    saved = load_config(ROOT / "runs" / "pad_run.toml", base_dir=ROOT, check_files=False)
    assert saved.inputs.main_folder == ROOT / "inbox" / "main"
    # What the PAD flow writes after "Enter new settings", with real Windows paths (backslashes).
    text = (ROOT / "runs" / "pad_template.toml").read_text(encoding="utf-8")
    for placeholder, value in {
        "{{company_name}}": "Example Client Ltd",
        "{{fy_start}}": "2025-01-01",
        "{{fy_end}}": "2025-12-31",
        "{{current_ledger}}": r"C:\Users\someone\Ledgers\current.xlsx",
        "{{post_ye_ledger}}": r"C:\Users\someone\Ledgers\post_ye.xlsx",
    }.items():
        text = text.replace(placeholder, value)
    cfg = load_config(write_run(tmp_path, text), base_dir=ROOT, check_files=False)
    # The backslashes survive as written (on Linux "C:\..." isn't absolute, so only compare the ending).
    assert str(cfg.inputs.current_ledger).endswith(r"C:\Users\someone\Ledgers\current.xlsx")
    assert cfg.engagement.fy_end == date(2025, 12, 31)


@pytest.mark.parametrize(("raw", "expected"), [("30", "0030"), (" 6800 ", "6800"), ("6800.0", "6800"), ("A1", "A1")])
def test_normalise_nominal_code(raw, expected):
    assert normalise_nominal_code(raw) == expected
