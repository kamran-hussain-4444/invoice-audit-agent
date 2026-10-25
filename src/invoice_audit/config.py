"""Load and validate a run settings file (TOML) into a `RunConfig`.

Relative paths in the run file are resolved against the folder `audit` is run from (the project root),
so the same run file works from PowerShell, CI and Power Automate.
"""

import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ConfigError(Exception):
    """A problem with the run settings. The message is shown to the user as-is."""


def normalise_nominal_code(code: object) -> str:
    """Make nominal codes comparable: Excel turns "0030" into 30 and sometimes 30.0."""
    text = str(code).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(4) if text.isdigit() else text


class _Section(BaseModel):
    # Unknown keys are an error, so a typo in the run file is reported instead of silently ignored.
    model_config = ConfigDict(extra="forbid")


class Engagement(_Section):
    company_name: str
    company_aliases: list[str] = Field(default_factory=list)
    group_entities: list[str] = Field(default_factory=list)
    fy_start: date
    fy_end: date

    @model_validator(mode="after")
    def _fy_order(self) -> "Engagement":
        if self.fy_end <= self.fy_start:
            raise ValueError(f"fy_end ({self.fy_end}) must be after fy_start ({self.fy_start})")
        return self


class Tests(_Section):
    run: list[Literal["main", "cutoff"]] = Field(default_factory=lambda: ["main", "cutoff"], min_length=1)


class Inputs(_Section):
    main_folder: Path | None = None
    cutoff_folder: Path | None = None
    current_ledger: Path
    post_ye_ledger: Path | None = None
    ledger_type: Literal["purchase_ledger", "ap_listing"] = "purchase_ledger"
    ledger_sheet: str = ""

    @field_validator("main_folder", "cutoff_folder", "post_ye_ledger", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if value == "" else value


class LedgerColumns(_Section):
    posting_date: str = "Posting Date"
    supplier: str = "Supplier"
    invoice_number: str = "Invoice No"
    description: str = "Description"
    nominal_code: str = "Nominal Code"
    nominal_account: str = "Nominal Account"
    net: str = "Net"
    vat: str = "VAT"
    gross: str = "Gross"
    currency: str = "Currency"
    original_amount: str = "Original Amount"


class LedgerSettings(_Section):
    columns: LedgerColumns = Field(default_factory=LedgerColumns)


class Output(_Section):
    folder: Path = Path("output")


class Pricing(_Section):
    """USD per million tokens."""

    input: Decimal = Decimal("2.00")
    output: Decimal = Decimal("10.00")
    cache_read: Decimal = Decimal("0.20")
    cache_write: Decimal = Decimal("2.50")
    batch_discount: Decimal = Decimal("0.50")

    @field_validator("*", mode="before")
    @classmethod
    def _exact_decimal(cls, value: object) -> object:
        return Decimal(str(value)) if isinstance(value, float) else value


class AISettings(_Section):
    model: str = "claude-sonnet-5-5"
    effort: Literal["low", "medium", "high"] = "medium"
    mode: Literal["auto", "live", "batch"] = "auto"
    batch_threshold: int = Field(50, ge=0)
    max_workers: int = Field(8, ge=1, le=64)
    cache_path: Path = Path(".cache/extractions.sqlite")
    max_pdf_pages: int = Field(20, ge=1)
    image_max_edge: int = Field(1568, ge=200)
    pricing: Pricing = Field(default_factory=Pricing)


class MatchingSettings(_Section):
    value_tolerance: Decimal = Field(Decimal("0.00"), ge=0)
    addressee_pass_score: int = Field(92, ge=0, le=100)
    addressee_review_score: int = Field(85, ge=0, le=100)

    @field_validator("value_tolerance", mode="before")
    @classmethod
    def _exact_decimal(cls, value: object) -> object:
        return Decimal(str(value)) if isinstance(value, float) else value

    @model_validator(mode="after")
    def _score_order(self) -> "MatchingSettings":
        if self.addressee_review_score > self.addressee_pass_score:
            raise ValueError("addressee_review_score must not be higher than addressee_pass_score")
        return self


class CategoriesRef(_Section):
    file: Path = Path("config/categories.toml")


class Category(_Section):
    name: str
    nominal_codes: list[str] = Field(default_factory=list)
    hint: str = ""

    @field_validator("nominal_codes", mode="before")
    @classmethod
    def _normalise_codes(cls, value: object) -> object:
        return [normalise_nominal_code(c) for c in value] if isinstance(value, list) else value


class RunConfig(_Section):
    engagement: Engagement
    tests: Tests = Field(default_factory=Tests)
    inputs: Inputs
    ledger: LedgerSettings = Field(default_factory=LedgerSettings)
    output: Output = Field(default_factory=Output)
    ai: AISettings = Field(default_factory=AISettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    categories: CategoriesRef = Field(default_factory=CategoriesRef)
    # Filled by load_config from the categories file (not written in the run file).
    category_list: list[Category] = Field(default_factory=list)

    @model_validator(mode="after")
    def _inputs_for_selected_tests(self) -> "RunConfig":
        problems = []
        if "main" in self.tests.run and self.inputs.main_folder is None:
            problems.append('inputs.main_folder is required when "main" is in tests.run')
        if "cutoff" in self.tests.run:
            if self.inputs.cutoff_folder is None:
                problems.append('inputs.cutoff_folder is required when "cutoff" is in tests.run')
            if self.inputs.post_ye_ledger is None:
                problems.append('inputs.post_ye_ledger is required when "cutoff" is in tests.run')
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def amount_basis(self) -> Literal["net", "gross"]:
        """Purchase ledgers post net; AP/creditors listings show gross (PLAN D8)."""
        return "net" if self.inputs.ledger_type == "purchase_ledger" else "gross"

    @property
    def category_names(self) -> list[str]:
        return [c.name for c in self.category_list]

    def category_for_code(self, code: str) -> str | None:
        wanted = normalise_nominal_code(code)
        for category in self.category_list:
            if wanted in category.nominal_codes:
                return category.name
        return None


def _format_validation_error(source: Path, error: ValidationError) -> str:
    lines = [f"Problem with settings in {source}:"]
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "(top level)"
        message = item["msg"].removeprefix("Value error, ")
        lines.append(f"  - {where}: {message}")
    return "\n".join(lines)


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"Settings file not found: {path}")
    try:
        # utf-8-sig: Notepad and PowerShell 5 often save files with an invisible "BOM" that tomllib rejects.
        return tomllib.loads(path.read_bytes().decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise ConfigError(f"{path} is not saved as UTF-8 text. Re-save it as UTF-8.") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from None


def load_categories(path: Path) -> list[Category]:
    """Read categories.toml; names must be unique and each nominal code may map to one category only."""
    data = _read_toml(path)
    try:
        categories = [Category.model_validate(item) for item in data.get("category", [])]
    except ValidationError as e:
        raise ConfigError(_format_validation_error(path, e)) from None
    if not categories:
        raise ConfigError(f"{path} defines no [[category]] entries")

    seen_names: set[str] = set()
    code_owner: dict[str, str] = {}
    for category in categories:
        if category.name in seen_names:
            raise ConfigError(f"{path}: category name '{category.name}' is used more than once")
        seen_names.add(category.name)
        for code in category.nominal_codes:
            if code in code_owner:
                raise ConfigError(
                    f"{path}: nominal code {code} is mapped to both '{code_owner[code]}' and '{category.name}'"
                )
            code_owner[code] = category.name
    return categories


def _resolve(path: Path | None, base_dir: Path) -> Path | None:
    if path is None or path.is_absolute():
        return path
    return base_dir / path


def load_config(path: Path, base_dir: Path | None = None, check_files: bool = True) -> RunConfig:
    """Load the run file, resolve paths, load categories and (optionally) check the inputs exist."""
    base_dir = base_dir or Path.cwd()
    path = _resolve(Path(path), base_dir)
    data = _read_toml(path)
    try:
        cfg = RunConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(_format_validation_error(path, e)) from None

    inputs = cfg.inputs
    inputs.main_folder = _resolve(inputs.main_folder, base_dir)
    inputs.cutoff_folder = _resolve(inputs.cutoff_folder, base_dir)
    inputs.current_ledger = _resolve(inputs.current_ledger, base_dir)
    inputs.post_ye_ledger = _resolve(inputs.post_ye_ledger, base_dir)
    cfg.output.folder = _resolve(cfg.output.folder, base_dir)
    cfg.ai.cache_path = _resolve(cfg.ai.cache_path, base_dir)
    cfg.categories.file = _resolve(cfg.categories.file, base_dir)
    cfg.category_list = load_categories(cfg.categories.file)

    if check_files:
        check_inputs_exist(cfg)
    return cfg


def check_inputs_exist(cfg: RunConfig) -> None:
    """Fail early with a clear message if a folder or ledger named in the run file is missing."""
    needed: list[tuple[str, Path | None, bool]] = [("inputs.current_ledger", cfg.inputs.current_ledger, False)]
    if "main" in cfg.tests.run:
        needed.append(("inputs.main_folder", cfg.inputs.main_folder, True))
    if "cutoff" in cfg.tests.run:
        needed.append(("inputs.cutoff_folder", cfg.inputs.cutoff_folder, True))
        needed.append(("inputs.post_ye_ledger", cfg.inputs.post_ye_ledger, False))
    missing = []
    for key, path, is_folder in needed:
        exists = path is not None and (path.is_dir() if is_folder else path.is_file())
        if not exists:
            missing.append(f"  - {key}: {'folder' if is_folder else 'file'} not found: {path}")
    if missing:
        raise ConfigError("Input files or folders are missing:\n" + "\n".join(missing))


RUN_TEMPLATE = """# Run settings for one engagement. Paths are relative to the project folder.
# Fill in [engagement] and [inputs], then: uv run audit run --config <this file> --dry-run

[engagement]
company_name    = "Example Client Ltd"          # the audited entity, as it should appear on invoices
company_aliases = []                            # trading names, e.g. ["Example Client Limited"]
group_entities  = []                            # related companies, e.g. ["Example Holdings Ltd"]
fy_start = 2025-04-01
fy_end   = 2026-03-31

[tests]
run = ["main", "cutoff"]                        # any subset of "main", "cutoff"

[inputs]
main_folder    = "inbox/main"                   # invoices sampled for Test 1 (main testing)
cutoff_folder  = "inbox/cutoff"                 # invoices sampled for Test 2 (cut-off)
current_ledger = "ledgers/current_year.xlsx"    # current-year purchase ledger / AP listing (xlsx or csv)
post_ye_ledger = "ledgers/post_year_end.xlsx"   # post-year-end ledger (needed for cut-off)
ledger_type    = "purchase_ledger"              # "purchase_ledger" compares NET; "ap_listing" compares GROSS
ledger_sheet   = ""                             # sheet name for xlsx; blank = first sheet

[ledger.columns]                                # your ledger's column headers (change to match the export)
posting_date    = "Posting Date"
supplier        = "Supplier"
invoice_number  = "Invoice No"
description     = "Description"
nominal_code    = "Nominal Code"
nominal_account = "Nominal Account"
net             = "Net"
vat             = "VAT"
gross           = "Gross"
currency        = "Currency"                    # optional; blank = GBP
original_amount = "Original Amount"             # optional; foreign-currency amount

[output]
folder = "output"

[ai]
model           = "claude-sonnet-5-5"
effort          = "medium"                      # low | medium | high
mode            = "auto"                        # auto | live | batch
batch_threshold = 50                            # auto uses the (half price) Batches API above this many new documents
max_workers     = 8
cache_path      = ".cache/extractions.sqlite"
max_pdf_pages   = 20
image_max_edge  = 1568

[ai.pricing]                                    # USD per million tokens; update if prices change
input          = 2.00
output         = 10.00
cache_read     = 0.20
batch_discount = 0.50

[matching]
value_tolerance        = 0.00                   # exact to the penny
addressee_pass_score   = 92
addressee_review_score = 85

[categories]
file = "config/categories.toml"
"""
