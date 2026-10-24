# PLAN.md: invoice-audit-agent

> Build specification. A Claude Code session should be able to build the whole project from this file
> and `CLAUDE.md` without asking questions. Where this plan conflicts with the `claude-api` skill on
> **Claude API usage details** (parameter names, SDK calls), the skill wins. Everything else here is
> an agreed decision. Don't change it without asking the user.

---

## 1. What we are building

A Python command-line tool that:

1. Reads **every invoice in a folder** (100–500+ files): PDF (digital and scanned), images (JPG/PNG/TIFF),
   Word (.docx), Excel (.xlsx) and emails (.eml/.msg) with invoice attachments.
2. Uses Claude to extract one row per invoice into a data table: file name, supplier, addressed-to entity, invoice number,
   invoice date, net, VAT, gross, currency, description and the service/delivery period inferred from the description.
3. Runs **audit tests in plain Python** against ledger listings (Excel/CSV):
   - **Test 1, Main testing** (tests of detail on the auditor's sample)
   - **Test 2, Cut-off testing** (invoices either side of the year end)
4. Writes a **formatted Excel workpaper**: Summary, Extracted Data, Main Testing, Cut-off Testing, Exceptions, Processing Log.

It is built to handle **large batches reliably**: parallel processing with a progress bar, retries, never crashing on one bad file,
a result cache so re-runs don't re-pay, and the Claude **Message Batches API** (half price) for big runs.

A **Power Automate Desktop** flow watches an inbox folder and triggers runs. This is the Microsoft angle for the
mhance Forward Deployed Engineer application. The Python core works fully without it.

**Context:** a portfolio project by an ACA trainee auditor. The work Copilot tool they use only handles about 20 invoices at a time.
**Synthetic data only.** No real client data, no RSM branding anywhere.

### Success criteria

- `uv run audit run --config runs/example_fy2026.toml` processes the 60 synthetic invoices plus edge-case files and
  produces a workpaper in which **every planted error appears as an exception or review item**, and clean invoices pass.
- One corrupt or unsupported file never stops the run. It appears in the Processing Log.
- A second identical run makes **zero** API calls (all cache hits), and the summary shows this.
- `uv run pytest` (offline, free) proves every planted error is caught. It runs green in GitHub Actions on Windows and Ubuntu.
- A 500-invoice scale run (`audit generate-data --scale 500`) completes through the Batches API with a cost report.

---

## 2. Agreed decisions (and why, in plain English)

| # | Topic | Decision | Why |
|---|---|---|---|
| D1 | Location | Project lives at `C:\Users\mistr\Projects\invoice-audit-agent` (not OneDrive) | OneDrive syncing a venv and cache causes file locks. GitHub is the backup. |
| D2 | Python tooling | **uv** manages Python 3.12, the venv and the lockfile | One tool, one command (`uv sync`), reproducible. |
| D3 | Reading files | Claude reads PDFs and images directly. Word/Excel/email are converted locally to text and attachments. **No local OCR.** | Claude reads scans and photos well. Tesseract is painful on Windows. |
| D4 | AI provider | **Claude API only** (official `anthropic` Python SDK) | One SDK, Batches API built in. The README explains how Azure could slot in. |
| D5 | Sampling | **Auditor picks the sample.** The folder *is* the sample. | Matches real engagements. Sampling methodology is the firm's judgement. |
| D6 | Matching | Match invoice to ledger on **invoice number only** (lightly normalised) | Simple and explainable. No match gives an exception. |
| D7 | Tolerance | **Exact to the penny** (configurable, default 0.00) | The user's choice. Strict. |
| D8 | Amount basis | Set by **ledger type**: `purchase_ledger` compares **net**, `ap_listing` compares **gross** | Purchase ledgers post net. AP/creditors listings show gross. |
| D9 | Ledger format | Standard headers plus a **column mapping** in the run settings | Real exports can be used without code changes. |
| D10 | Cut-off data | **Two separate ledger files**: current-year and post-year-end | The user's choice. The period comes from which file the line is in. |
| D11 | Spanning year end | Flag **Review (auditor judgement)** and suggest a **day-count apportioned** accrual/prepayment | The auditor makes the call, with the maths done for them. |
| D12 | Classification | **Fixed category list** in config, mapped from nominal codes. Claude must pick from the list and give a reason. | Consistent and testable. |
| D13 | Folders | **One folder per test** (`main_folder`, `cutoff_folder`, either optional), **one workpaper** | Main and cut-off samples differ in practice. |
| D14 | Confidence | Claude rates each key field **high/medium/low** and returns null when unreadable, **plus Python rule checks**. Any issue gives "Needs review", and dependent tests give **Review** rather than Pass/Exception. | Models can be over-confident. Rule checks catch real errors. **Never guess.** |
| D15 | Interface | **CLI + TOML settings file** | It's what Power Automate calls, and it's easy to test. |
| D16 | Foreign currency | Ledger has optional **Currency** and **Original Amount** columns. Compare in the original currency. | Realistic, and no FX lookups needed. |
| D17 | Model | **`claude-sonnet-5-5`** by default, configurable in the settings file | Strong on messy scans and judgement, and cheap enough at scale. |
| D18 | Live vs batch | **Auto**: Batches API if > 50 *uncached* documents, else live parallel. `--mode live\|batch` overrides. | Small runs stay interactive. Big runs cost half. |
| D19 | Tests | **Answer key + recorded results.** Offline tests are free and run in CI. One opt-in live test spends real money. | Proves planted errors are caught without paying per test run. |
| D20 | .msg files | Generate **.eml**. An optional script uses classic Outlook (if installed) to save .msg copies. The .msg *reader* is built anyway. | No free Python library reliably writes .msg. |
| D21 | AI vs Python | **AI reads and interprets. Python judges.** One Claude call per invoice returns fields, a suggested category and the service period. Every pass/fail is a Python rule. | Repeatable, testable, defensible in an audit file. |
| D22 | Power Automate | **Watch-folder flow + guided launcher.** PAD polls an Inbox folder, runs a PowerShell wrapper and opens the workpaper in Excel. | The free PAD has no folder trigger, so a polling loop is the honest free option. |
| D23 | Addressee | **Normalise + known aliases + fuzzy score** (thresholds configurable) | Avoids false exceptions on "Ltd" vs "Limited" and still catches sister companies. |
| D24 | Repo data | **Commit** the 60 generated invoices, ledgers, answer key and one sample workpaper | Reviewers can browse the output without running anything. |
| D25 | Extras | **GitHub Actions CI** and **run cost and stats in the summary.** No duplicate check, no Streamlit (stretch only). | Scope control. |

---

## 3. Tech stack

| Purpose | Library | Notes |
|---|---|---|
| Package/env manager | `uv` | `uv sync`, `uv run ...` |
| Python | 3.12 | pinned via `.python-version` |
| Claude | `anthropic` (official SDK) | **Load the `claude-api` skill before writing any Claude code** |
| Data models / validation | `pydantic` v2 | config, extraction results |
| CLI | `typer` | `audit` entry point |
| Progress bar / console | `rich` | |
| Settings | `tomllib` (stdlib) | TOML run files |
| Env vars | `python-dotenv` | loads `ANTHROPIC_API_KEY` from `.env` |
| PDF checks | `pypdf` | page count, encryption, corrupt detection (Claude reads the PDF itself) |
| Images | `Pillow` | EXIF rotation, resize, TIFF→PNG |
| Word | `python-docx` | body, tables, headers/footers |
| Excel (read invoices and ledgers, write workpaper) | `openpyxl` | |
| Ledger loading | `pandas` | read as strings, convert to `Decimal` ourselves |
| Email .msg | `extract-msg` | .eml uses stdlib `email` |
| Fuzzy matching | `rapidfuzz` | addressee checks |
| Cache | `sqlite3` (stdlib) | |
| Synthetic data | `reportlab` (PDF), `pypdfium2` (rasterise PDF → image for "scans"), `Pillow`, `python-docx`, `openpyxl`, `faker` (seeded) | dev dependency group is fine but the generator CLI must work after `uv sync` (put them in main deps) |
| Tests / lint | `pytest`, `ruff` | dev group |

**Money is always `decimal.Decimal`**, quantized to 0.01 with `ROUND_HALF_UP`. Never use float for amounts. When converting
model output (JSON numbers) use `Decimal(str(value))`.

---

## 4. Repository layout

```
invoice-audit-agent/
├── CLAUDE.md
├── PLAN.md
├── README.md                     # portfolio-facing: what, why, demo, architecture (mermaid), cost results, how to run
├── LICENSE                       # MIT
├── pyproject.toml                # project + [project.scripts] audit = "invoice_audit.cli:app"; pytest + ruff config
├── uv.lock
├── .python-version               # 3.12
├── .gitignore                    # .env, .venv/, .cache/, output/, logs/, data/scale_*/, __pycache__/, *.local.toml
├── .env.example                  # ANTHROPIC_API_KEY=
├── .github/workflows/ci.yml
├── config/
│   └── categories.toml           # default category list + nominal code mapping
├── runs/
│   └── example_fy2026.toml       # settings for the synthetic engagement
├── src/invoice_audit/
│   ├── __init__.py
│   ├── cli.py                    # typer app: run, generate-data, init-config, cache
│   ├── config.py                 # load + validate run TOML (pydantic) → RunConfig
│   ├── models.py                 # all pydantic/dataclass models (section 6)
│   ├── money.py                  # Decimal parsing/formatting helpers
│   ├── discovery.py              # walk folders → list[SourceDocument] (expands emails into attachments)
│   ├── loaders/
│   │   ├── __init__.py           # load(source) -> ContentPayload; dispatch by extension
│   │   ├── pdf.py
│   │   ├── image.py
│   │   ├── word.py
│   │   ├── excel.py
│   │   └── email.py              # .eml + .msg
│   ├── extraction/
│   │   ├── prompt.py             # PROMPT_VERSION, system prompt builder
│   │   ├── schema.py             # JSON schema builder (category enum injected)
│   │   ├── requests.py           # build Messages API params for one document (shared by live + batch)
│   │   ├── live.py               # ThreadPoolExecutor runner
│   │   ├── batch.py              # Batches API runner (chunking, resume, poll, collect)
│   │   ├── cache.py              # SQLite cache
│   │   └── cost.py               # usage → USD
│   ├── validation.py             # rule checks → extraction status + reasons
│   ├── ledger.py                 # load + map columns → list[LedgerLine]
│   ├── matching.py               # invoice-number normalisation, ledger lookup, addressee scoring
│   ├── procedures/
│   │   ├── main_testing.py       # Test 1
│   │   └── cutoff.py             # Test 2
│   ├── findings.py               # plain-English exception text + suggested actions
│   ├── workpaper.py              # openpyxl writer
│   ├── pipeline.py               # orchestrates everything; returns RunResult
│   ├── logging_setup.py
│   └── synthetic/
│       ├── __init__.py
│       ├── scenarios.py          # the 60 invoice specs + planted errors + edge cases (single source of truth)
│       ├── entities.py           # fictional company, suppliers, chart of accounts
│       ├── render_pdf.py         # digital PDF via reportlab
│       ├── render_scan.py        # scanned PDF / PNG scan / JPG photo effects
│       ├── render_docx.py
│       ├── render_xlsx.py
│       ├── render_eml.py
│       ├── ledgers.py            # writes current + post-YE ledgers
│       ├── scale.py              # --scale N generator for load tests
│       └── generate.py           # entry point; writes answer_key.json
├── scripts/
│   ├── run_audit.ps1             # wrapper called by Power Automate Desktop
│   ├── make_msg_with_outlook.ps1 # optional: convert .eml → .msg via classic Outlook COM
│   └── export_recorded_fixtures.py  # cache → tests/fixtures/recorded/*.json
├── pad/
│   ├── README.md                 # step-by-step PAD setup (with screenshot placeholders)
│   └── invoice_audit_flow.txt    # PAD actions as text (copy/paste into PAD designer)
├── data/synthetic/               # COMMITTED (seeded, reproducible)
│   ├── main_sample/
│   ├── cutoff_sample/
│   ├── ledger_fy2026.xlsx
│   ├── ledger_post_ye.xlsx
│   └── answer_key.json
├── docs/
│   └── sample_workpaper.xlsx     # committed output of a real run
└── tests/
    ├── conftest.py
    ├── fixtures/                 # small hand-made files + recorded/ Claude outputs
    └── test_*.py                 # section 15
```

---

## 5. Settings (run file)

`runs/example_fy2026.toml` (all keys shown; defaults noted):

```toml
[engagement]
company_name    = "Brackenfield Engineering Ltd"
company_aliases = ["Brackenfield Engineering Limited", "Brackenfield Precision"]   # trading names etc.
group_entities  = ["Brackenfield Holdings Ltd"]     # known related entities → clearer exception text
fy_start = 2025-04-01
fy_end   = 2026-03-31

[tests]
run = ["main", "cutoff"]          # any subset of "main", "cutoff"

[inputs]
main_folder    = "data/synthetic/main_sample"      # required if "main" in run
cutoff_folder  = "data/synthetic/cutoff_sample"    # required if "cutoff" in run
current_ledger = "data/synthetic/ledger_fy2026.xlsx"   # required (both tests)
post_ye_ledger = "data/synthetic/ledger_post_ye.xlsx"  # required if "cutoff" in run
ledger_type    = "purchase_ledger"   # "purchase_ledger" → compare NET ; "ap_listing" → compare GROSS
ledger_sheet   = ""                  # optional sheet name for xlsx; default first sheet. CSV ignored.

[ledger.columns]                     # ledger header → field. Defaults shown. Missing optional columns are fine.
posting_date    = "Posting Date"     # required
supplier        = "Supplier"         # required
invoice_number  = "Invoice No"       # required
description     = "Description"      # optional
nominal_code    = "Nominal Code"     # required
nominal_account = "Nominal Account"  # optional
net             = "Net"              # required if ledger_type = purchase_ledger
vat             = "VAT"              # optional
gross           = "Gross"            # required if ledger_type = ap_listing
currency        = "Currency"         # optional (blank/missing = GBP)
original_amount = "Original Amount"  # optional; amount in original currency on the same basis (net/gross)

[output]
folder = "output"

[ai]
model           = "claude-sonnet-5-5"
effort          = "medium"           # low | medium | high
mode            = "auto"             # auto | live | batch
batch_threshold = 50                 # auto → batch when uncached docs > this
max_workers     = 8                  # live mode parallelism
cache_path      = ".cache/extractions.sqlite"
max_pdf_pages   = 20                 # more → Needs review ("split manually")
image_max_edge  = 1568               # px, long edge after resize

[ai.pricing]                         # USD per million tokens; update if prices change
input       = 2.00
output      = 10.00
cache_read  = 0.20
batch_discount = 0.50

[matching]
value_tolerance        = 0.00        # exact to the penny
addressee_pass_score   = 92          # rapidfuzz token_sort_ratio after normalisation
addressee_review_score = 85          # between review and pass → Review; below → Exception

[categories]
file = "config/categories.toml"
```

`config/categories.toml`:

```toml
[[category]]
name = "Cost of sales"
nominal_codes = ["5000", "5010"]
hint = "Raw materials, components and subcontract work used directly in production."

[[category]]
name = "Marketing"
nominal_codes = ["6100"]
hint = "Advertising, trade shows, exhibitions, brochures, sponsorship, digital ads, PR."

[[category]]
name = "Professional fees"
nominal_codes = ["6200"]
hint = "Legal, accountancy, consultancy, recruitment fees."

[[category]]
name = "Premises (rent & rates)"
nominal_codes = ["6300"]
hint = "Rent, service charges, business rates."

[[category]]
name = "Utilities"
nominal_codes = ["6400"]
hint = "Electricity, gas, water, waste."

[[category]]
name = "IT & software"
nominal_codes = ["6500"]
hint = "Software subscriptions and licences, IT support, hosting, small IT equipment."

[[category]]
name = "Travel & subsistence"
nominal_codes = ["6600"]
hint = "Travel, hotels, subsistence."

[[category]]
name = "Repairs & maintenance"
nominal_codes = ["6700"]
hint = "Repairs and servicing of existing assets and premises. Not new assets."

[[category]]
name = "Insurance"
nominal_codes = ["6900"]
hint = "Insurance premiums."

[[category]]
name = "Administrative expenses"
nominal_codes = ["6800"]
hint = "Stationery, postage, office supplies, subscriptions, cleaning, sundry admin."

[[category]]
name = "Fixed assets (capital)"
nominal_codes = ["0030", "0040"]
hint = "Purchase of new plant, machinery, vehicles or equipment with lasting use (capital expenditure)."
```

Config validation (pydantic): `fy_end > fy_start`; required inputs per selected test exist on disk; category names unique;
every nominal code maps to at most one category. Errors print a friendly message and exit with code 1.

`audit init-config <path>` writes a commented template of the above.

---

## 6. Data models (`models.py`)

```python
class SourceDocument:          # one thing to extract
    doc_id: str                # stable id: sha256 of content bytes (first 16 hex) + suffix for attachments → also the batch custom_id (^[A-Za-z0-9_-]{1,64}$)
    test: Literal["main", "cutoff"]
    file_path: Path            # the file on disk
    display_name: str          # "invoice_07.pdf" or "email_03.eml › INV-2231.pdf"
    kind: Literal["pdf", "image", "docx", "xlsx", "email_body"]
    content_bytes: bytes | None  # for attachments (file_path is the parent email)
    email_context: str | None  # subject + from + first 1,000 chars of body, for attachments

class ContentPayload:          # what goes to Claude
    blocks: list[dict]         # Messages API content blocks (document / image / text)
    approx_bytes: int          # for batch chunking

class ExtractedInvoice:        # validated model output (section 8)
    ...all schema fields, amounts as Decimal, dates as date

class ExtractionRecord:        # per document after extraction + validation
    source: SourceDocument
    status: Literal["ok", "needs_review", "excluded", "failed"]
    reasons: list[str]          # plain English, e.g. "Net + VAT ≠ gross (difference £0.40)"
    weak_fields: set[str]       # fields that are null/low-confidence/failed a rule → drive Review
    invoice: ExtractedInvoice | None
    usage: TokenUsage | None
    from_cache: bool
    mode: Literal["live", "batch", "cache"] | None

class LedgerLine:
    source: Literal["current", "post_ye"]
    row_number: int            # Excel row for traceability
    posting_date: date
    supplier: str
    invoice_number: str
    invoice_number_norm: str
    description: str | None
    nominal_code: str
    nominal_account: str | None
    category: str | None       # via categories.toml mapping; None if code unmapped
    net: Decimal | None
    vat: Decimal | None
    gross: Decimal | None
    currency: str              # default "GBP"
    original_amount: Decimal | None

class CheckResult:
    status: Literal["pass", "exception", "review", "n/a"]
    detail: str                # short cell text
    finding_ref: str | None    # EX-### when exception/review

class MainTestRow / CutoffTestRow   # one per invoice; holds CheckResults per column (sections 11, 12)

class Finding:                 # one row on the Exceptions tab
    ref: str                   # EX-001...
    test: Literal["Main", "Cut-off", "Extraction"]
    test_ref: str              # MT-004 / CO-012 / DOC-…
    status: Literal["exception", "review"]
    issue_type: str            # "Value mismatch", "Date outside FY", ... (fixed vocabulary, section 13)
    explanation: str           # plain English, generated by Python
    ai_reasoning: str | None   # quoted from the model where relevant
    suggested_action: str
    amount_impact: Decimal | None

class RunResult:               # everything the workpaper + run_results.json need, incl. RunStats
```

---

## 7. Pipeline (`pipeline.py`)

```
load config
→ discover documents in main_folder / cutoff_folder           (discovery.py)
→ for each document: look up cache                              (cache.py)
→ uncached → build payload (loaders) → extract (live or batch)  (extraction/*)
     each doc wrapped in try/except: any error → ExtractionRecord(status="failed", reason) + log; continue
→ validate every extraction → status + weak_fields              (validation.py)
→ load ledgers                                                  (ledger.py)  ← a ledger error is FATAL (exit 1, clear message)
→ run Test 1 on main records, Test 2 on cut-off records         (procedures/*)
→ build findings                                                (findings.py)
→ write workpaper + output/run_results.json + output/latest_run.json  (workpaper.py)
→ print summary table + final line:  WORKPAPER: <absolute path>
```

- Loading ledgers happens **before** any API call (fail fast and cheap if the ledger is wrong).
- `--dry-run`: discover, check cache and loaders, print counts per file type, cached vs new, chosen mode and an **estimated cost**
  (estimate = new docs × 3,000 input + 1,000 output tokens × pricing, × batch discount if batch). No API calls.
- `--limit N`: only the first N documents per folder (sorted by name). For cheap experiments.
- Exit codes: `0` = completed, all documents processed. `2` = completed but some documents failed. `1` = fatal (config/ledger/API key).
- Missing `ANTHROPIC_API_KEY` is checked only when uncached documents need extraction. Message: how to create `.env`.

### Discovery rules
- Recursive walk, sorted by relative path. Ignore hidden files, `~$*` Office lock files and `Thumbs.db`.
- Supported: `.pdf`, `.jpg/.jpeg`, `.png`, `.tif/.tiff`, `.webp`, `.docx`, `.xlsx`, `.eml`, `.msg`.
- Unsupported (e.g. `.doc`, `.xls`, `.zip`, `.heic`): `excluded` with reason "Unsupported file type .doc. Save as .docx/PDF and re-run."
- Emails: each supported attachment becomes its own SourceDocument (`display_name` = `email.eml › attachment.pdf`). Inline
  logos/signature images under 20 KB are skipped. If an email has **no** supported attachments, the **body** becomes one
  `email_body` document (an invoice may be written in the body). Attached `.eml`/`.msg` are expanded one level deep.

---

## 8. Loaders (`loaders/`)

Every loader returns `ContentPayload` or raises `LoaderError(reason)`. All blocks are preceded by a short text block such as
`"Source: invoice_07.pdf (PDF)"`, and email attachments also get `"Email context: …"`.

| Kind | Handling |
|---|---|
| PDF | Open with `pypdf`: encrypted → `LoaderError("Password-protected PDF")`; unreadable → `LoaderError("Corrupt or unreadable PDF")`; pages > `max_pdf_pages` → `needs_review` without calling the API. Size > 30 MB → LoaderError. Otherwise send the raw bytes as a base64 `document` block (`application/pdf`). Claude handles both digital and scanned. |
| Image | Pillow: `ImageOps.exif_transpose`, convert to RGB, downscale long edge to `image_max_edge`, re-encode JPEG q=90 (PNG kept as PNG if smaller). Multi-page TIFF → one image block per page (max 10). |
| DOCX | `python-docx`: section header text, body paragraphs **and tables in document order** (rows tab-separated), footer text. Send as one `text` block. Empty text → LoaderError("No text found in Word document"). |
| XLSX | `openpyxl` (`data_only=True`): for each visible sheet, non-empty rows as tab-separated values with the sheet name heading. Cap 500 rows/sheet. Send as `text`. |
| EML | stdlib `email` with `policy.default`. Attachments → bytes passed to the matching loader. Body → text (prefer text/plain, else strip HTML tags). |
| MSG | `extract-msg`: same behaviour as EML. |

---

## 9. Claude extraction (`extraction/`)

**Before writing this code, load the `claude-api` skill** and read `python/claude-api/README.md`, `tool-use.md`
(structured outputs) and `batches.md`. Use the official SDK. Don't guess method names.

### 9.1 Request (built once in `requests.py`, used by both live and batch)
- `model` from config (default `claude-sonnet-5-5`). `max_tokens=16000` (non-streaming).
- Adaptive thinking (default when omitted on this model). Set `output_config.effort` from config (default `medium`).
- **Structured outputs:** `output_config.format = {"type": "json_schema", "schema": <schema>}`. Parse `response` text with
  `ExtractedInvoice.model_validate_json` (pydantic converts and validates).
- **Do not send `temperature`/`top_p`/`top_k`** (rejected by the API since 2026-10-21).
- `system`: the fixed system prompt (9.3) as a text block with `cache_control: {"type": "ephemeral"}`. It is identical for every
  invoice, so it caches across calls (it must exceed the model's minimum cacheable length, so keep the category hints in it).
- `messages`: one user message: content blocks from the loader, then the text "Extract the invoice data as specified."
- Check `stop_reason`: `refusal` → failed ("Model declined to process this document"). `max_tokens` → retry once with `max_tokens=32000`
  via streaming per the skill, else failed. Follow the skill's guidance on refusal fallbacks for Sonnet 5.5.
- Client: `anthropic.Anthropic(max_retries=4, timeout=120)` (SDK retries 429/5xx/connection errors with backoff).

### 9.2 JSON schema (`schema.py`), all properties required, `additionalProperties: false`, nullable via `["string","null"]`
```
document_type: enum [invoice, credit_note, statement, quote, remittance, other]
supplier_name: string|null
supplier_vat_number: string|null
addressed_to: string|null                 # the customer / bill-to entity exactly as printed
invoice_number: string|null               # exactly as printed
invoice_date: string|null                 # YYYY-MM-DD
currency: string|null                     # ISO 4217, e.g. GBP, EUR, USD
net_amount: number|null
vat_amount: number|null
gross_amount: number|null
description: string|null                  # ≤ 300 chars summary of goods/services
line_items: array (max 20) of {description: string, amount: number|null}
delivery_date: string|null                # YYYY-MM-DD if a delivery/dispatch date is shown
service_period_start: string|null         # YYYY-MM-DD
service_period_end: string|null           # YYYY-MM-DD
period_basis: enum [explicit_period, delivery_date, description_inference, not_determinable]
period_reasoning: string                  # one sentence
suggested_category: enum [<category names from categories.toml>]
category_reasoning: string                # one sentence
multiple_invoices_detected: boolean
field_confidence: object {supplier_name, addressed_to, invoice_number, invoice_date, amounts, currency, description, service_period}: each enum [high, medium, low]
extraction_notes: string|null             # anything odd: handwriting, amendments, cut-off text, partial page
```

### 9.3 System prompt (`prompt.py`), `PROMPT_VERSION = "1"`, bump on **any** change (it is part of the cache key)
Content to include (write it as clear prose, not shouty rules):
- Role: careful accounts-payable data extractor supporting a UK statutory audit. Accuracy matters more than completeness.
- **Never guess.** If a value is not clearly legible or not present, return null and set that field's confidence to low.
  Do not calculate missing amounts. Copy what is printed (Python checks the arithmetic).
- Amounts as plain numbers (no symbols or commas). Credit notes as positive numbers with `document_type=credit_note`.
- Dates as YYYY-MM-DD. UK documents use day/month order (03/04/2026 = 3 April 2026) unless clearly US.
- `addressed_to` = the bill-to/customer entity (not the supplier, not a delivery address unless no bill-to exists).
- Service period rules with examples: "Consultancy – March 2026" → 2026-03-01 to 2026-03-31 (explicit_period);
  "Annual licence from 1 April 2026" → 2026-04-01 to 2027-03-31; goods with a delivery date → start=end=delivery date
  (delivery_date); "Q1 2026" → 2026-01-01 to 2026-03-31; no clue → nulls + not_determinable. Never use the invoice
  date as the service period (Python handles fallback).
- Category: choose the single best category from the list (names + hints rendered from categories.toml), judging what was
  bought, **not** what the supplier usually sells. One-sentence reason.
- Email context, if given, can help interpretation, but the invoice document takes precedence.
- Set `multiple_invoices_detected` true if the document contains more than one invoice. Extract only the first.

### 9.4 Live mode (`live.py`)
`ThreadPoolExecutor(max_workers)` with the sync client. `rich` progress bar (done/total, failed count, elapsed, ETA).
Each future is isolated: any exception → failed record + log entry with traceback in the log file. Results are written to the cache
as each completes (so a crash mid-run loses nothing).

### 9.5 Batch mode (`batch.py`)
1. Build requests (`custom_id = doc_id`, `params` = 9.1 params) for uncached documents.
2. **Chunk**: ≤ 150 MB of payload and ≤ 5,000 requests per batch (stay well under API limits).
3. Submit each chunk. **Persist** `{batch_id, doc_ids, submitted_at, config_fingerprint}` to `.cache/pending_batches.json`
   **immediately**, so an interrupted run (Ctrl+C, laptop sleep) **resumes polling** on the next `audit run` instead of resubmitting and paying twice.
4. Poll `batches.retrieve` every 15 s. Progress bar driven by `request_counts` (processing/succeeded/errored).
5. Collect `batches.results`. **Key by `custom_id`** (results come in any order). `succeeded` → validate → cache.
   `errored`/`expired`/`canceled` → retry those documents **once in live mode**, then mark failed.
6. Remove the entry from `pending_batches.json` when collected.

### 9.6 Cache (`cache.py`)
SQLite table `extractions(key PK, doc_display_name, model, prompt_version, created_at, response_json, input_tokens, output_tokens, cache_read_tokens, mode)`.
`key = sha256(content_bytes + email_context + model + PROMPT_VERSION + schema_hash)`. Extraction does **not** depend on the
ledger or engagement settings, so re-running with different settings or ledgers is free. Only responses that parsed
successfully are cached (including needs-review ones). Failures are not cached. `--no-cache` bypasses reads.
`audit cache stats` / `audit cache clear`.

### 9.7 Cost (`cost.py`)
From each response's `usage`: input, output, cache read and cache creation tokens → USD using `[ai.pricing]`, with
`batch_discount` applied to batch results. Totals go to RunStats: documents, cache hits, live calls, batch calls, tokens by type,
estimated USD, duration, docs/minute.

---

## 10. Validation and confidence (`validation.py`)

Applied to every successful extraction. Each failed rule adds a plain-English reason and adds fields to `weak_fields`.

| Rule | Outcome |
|---|---|
| `document_type` ≠ invoice | `excluded`: "Document is a {type}, not an invoice". Listed in the Processing Log + one Extraction finding (review). |
| `multiple_invoices_detected` | needs_review (all fields weak): "File contains more than one invoice. Split and re-run." |
| Any of supplier, invoice_number, invoice_date, gross_amount is null | needs_review; that field weak |
| Any `field_confidence` = low | needs_review; mapped field(s) weak (`amounts` → net, vat, gross) |
| net + vat ≠ gross (difference > 0.01) | needs_review; amounts weak: "Net + VAT ≠ gross (difference £x)" |
| GBP invoice and VAT/net not ≈ 0%, 5% or 20% (±0.5 percentage points) | needs_review; amounts weak: "Unusual VAT rate x%" |
| invoice_date invalid, after today, or before 2015 | needs_review; invoice_date weak |
| currency not a 3-letter code | needs_review; currency weak |
| service_period_end < start | needs_review; service_period weak |

Medium confidence does **not** trigger review by itself, but it is shown on the Extracted Data tab.
**Field → dependent tests:** invoice_number → every ledger-dependent check; amounts/currency → value check; invoice_date →
date-in-FY (and the cut-off fallback); addressed_to → addressee; description → classification; service_period → cut-off.
A weak field makes its dependent checks **Review** ("Unable to test: low-confidence extraction of X"). Never Pass, never Exception.

---

## 11. Test 1: Main testing (`procedures/main_testing.py`)

For each main-sample record (status ok or needs_review; excluded/failed appear only in the Processing Log):

**Ledger match.** `normalise(no) = no.strip().upper()` with all whitespace removed. Look up in the **current** ledger.
- 0 matches → every check `n/a`. Overall **Exception** "No ledger entry found for invoice number X". If the number is found in the
  **post-YE ledger**, add "(found in post-year-end ledger, posted dd/mm/yyyy)".
- More than 1 match → Review "Invoice number appears N times in ledger. Agree manually." (no duplicate-detection feature beyond this).
- Exactly 1 match → run the four checks.

| Column | Rule | Pass | Exception | Review |
|---|---|---|---|---|
| **A: Value agrees** | basis = net (purchase_ledger) or gross (ap_listing). If invoice currency = GBP: compare invoice basis amount to ledger net/gross. If invoice currency ≠ GBP: ledger currency must equal invoice currency and compare to ledger `original_amount`. | \|difference\| ≤ tolerance | difference > tolerance; currency mismatch | ledger lacks original_amount for a foreign-currency invoice ("FX: auditor to agree"); amounts weak |
| **D: Date in FY** | fy_start ≤ invoice_date ≤ fy_end (inclusive) | inside | outside (state whether prior or later period) | date weak |
| **E: Addressed to entity** | section 11.1 | match | different entity | borderline score; addressed_to weak/null |
| **C: Classification** | ledger nominal code → category (categories.toml) vs `suggested_category` | same | different, and description confidence ≥ medium: suggest the AI category | nominal code unmapped; description weak |

**Overall** = Exception if any check is an exception, else Review if any is review, else Pass.
**Value tested** = the ledger basis amount (GBP) of matched items.

### 11.1 Addressee matching (`matching.py`)
`norm(name)`: lowercase, `&`→`and`, strip punctuation, remove the words `limited, ltd, plc, llp, llc, inc, the, co, company, uk`,
collapse spaces.
1. norm(addressed_to) equals norm(company_name) or norm(any alias) → **Pass**.
2. Else score = max `rapidfuzz.fuzz.token_sort_ratio` against company and aliases.
   - score ≥ `addressee_pass_score` (92) → **Pass** (detail: "close match, score N", e.g. a typo).
   - norm equals a `group_entities` entry → **Exception** "Addressed to group company {name}, not the audited entity".
   - score ≥ `addressee_review_score` (85) → **Review**.
   - else → **Exception** "Addressed to {name}, a different entity".

---

## 12. Test 2: Cut-off testing (`procedures/cutoff.py`)

For each cut-off-sample record. YE = `fy_end`.

**Period of activity.**
- `period_basis` explicit_period / description_inference → start/end from the model. delivery_date → start = end = delivery_date.
- not_determinable or nulls → **fallback to invoice date** (start = end = invoice_date), basis "invoice date (fallback)".
  **A fallback-based result can never be Pass.** Pass becomes Review with "Service period not stated. Invoice date used. Confirm."
- Position: `pre_ye` if end ≤ YE; `post_ye` if start > YE; `spans` if start ≤ YE < end.

**Where recorded.** Look up the normalised invoice number in **both** ledgers → `current`, `post_ye`, `both`, `neither`.

| Position \ Recorded | current | post_ye | both | neither |
|---|---|---|---|---|
| **pre_ye** | ✓ Pass | ✗ Exception: pre-YE cost recorded after YE. Current-year expenses **understated**, accrual needed (amount). | ✗ Exception: recorded in both periods, possible double count | ✗ Exception: not in either ledger, **possible unrecorded liability** |
| **post_ye** | ✗ Exception: post-YE cost recorded in current year. Expenses **overstated**, prepayment/deferral needed (amount) | ✓ Pass | ✗ Exception: both periods | ? Review: not yet recorded. No current-year impact, confirm. |
| **spans** | ? Review (judgement): suggested **prepayment** = amount × days_after / total_days | ? Review (judgement): suggested **accrual** = amount × days_before / total_days | ✗ Exception: both periods | ✗ Exception: not recorded, unrecorded liability for the pre-YE portion |

- `days_before = (YE − start).days + 1`, `days_after = (end − YE).days`, `total = days_before + days_after`. Amount = ledger basis
  amount if matched, else the invoice basis amount. Round to the penny. Show the working in the detail text, e.g. "90/365 days pre-YE".
- Cut-off tab also shows the **value check (column A)** using the same rule as Test 1 against the ledger line found.
- service_period weak → the period check is Review.

---

## 13. Findings (`findings.py`)

Every Exception or Review check becomes one Finding (refs EX-001… in workpaper order: Main, then Cut-off, then Extraction).
Explanations are **Python templates filled with real numbers**. The model never writes them, so they are consistent.
Where relevant, quote the model's `category_reasoning` / `period_reasoning` in the **AI reasoning** column.

Fixed issue-type vocabulary and template examples:
- **Value mismatch**: "Invoice net £1,243.50 does not agree to ledger net £1,234.50 (difference £9.00). The difference is divisible by 9, a possible transposition." Action: "Obtain explanation and correct posting if needed."
  (Add the transposition note only when difference × 100 is divisible by 9 and the difference is not zero.)
- **Currency / FX**: "Invoice is in EUR. Ledger has no original-currency amount to agree to." Action: "Agree to the FX rate used and the original amount."
- **Date outside FY**: "Invoice dated 15/02/2025 is before the financial year starting 01/04/2025." Action: "Confirm why a prior-period invoice is in the current-year ledger."
- **Wrong addressee**: "Invoice is addressed to Brackenfield Holdings Ltd (group company), not Brackenfield Engineering Ltd." Action: "Confirm the cost belongs to the audited entity. Consider a recharge."
- **Misclassification**: "Posted to 6800 Administrative expenses, but the description ('Exhibition stand hire and brochures') suggests Marketing." Action: "Consider a reclassification journal."
- **No ledger match** / **Multiple ledger matches**
- **Cut-off error** (understatement/overstatement, with amount) / **Spans year end** (with apportionment working) / **Possible unrecorded liability** / **Recorded in both periods**
- **Low-confidence extraction**: "Could not reliably read invoice date (low confidence). Date test not performed." Action: "Inspect the invoice manually."
- **Not an invoice** / **Multiple invoices in file**

---

## 14. Workpaper (`workpaper.py`, openpyxl)

File: `output/{company_slug}_FY{fy_end:%Y}_invoice_testing_{YYYYMMDD_HHMMSS}.xlsx`. Neutral styling, **no firm branding**.
Common formatting: header row bold white on dark slate (`2F3E4E`), frozen header + first column, autofilter, sensible column
widths, wrap text on long columns, money `#,##0.00`, dates `DD/MM/YYYY`, landscape print, fit to page width.
Result fills: Pass `C6EFCE` (green), Exception `FFC7CE` (red), Review `FFEB9C` (amber). Low-confidence cells on the Extracted Data tab amber.
Tick marks: `✓` pass, `✗` exception, `?` review, `–` n/a (font Segoe UI Symbol).

1. **Summary**: header block: Client, Period (fy_start–fy_end), Workpaper "Purchases: tests of detail and cut-off",
   Prepared by ____ / Date ____ / Reviewed by ____ / Date ____ (blank cells for the auditor), Objective text for each test,
   Settings used (folders, ledger files, ledger type/basis, tolerance, model, prompt version).
   **Counts**: files found, documents extracted, from cache, needs review, excluded, failed.
   **Per test**: items tested, Pass, Exception, Review, total value tested (£), value of exceptions (£).
   **Run stats**: mode (live/batch/mixed), API calls, cache hits, input/output/cache-read tokens, estimated cost (USD), duration, docs/min.
   **Tick mark legend.** Disclaimer: "Data extracted with AI assistance. Exceptions and review items require auditor
   judgement. This schedule does not replace professional scepticism."
2. **Extracted Data**: one row per document: Doc ref, File, Test (Main/Cut-off), Status, Reasons, Document type, Supplier,
   Supplier VAT no, Addressed to, Invoice no, Invoice date, Currency, Net, VAT, Gross, Description, Delivery date, Service
   period start, Service period end, Period basis, Period reasoning, Suggested category, Category reasoning, confidence per field, Extraction notes, Source (cache/live/batch).
3. **Main Testing**: Ref (MT-001), File, Supplier, Invoice no, Invoice date, Ledger row, Posting date, Nominal code, Nominal account,
   Ledger amount, Invoice amount (basis), Difference, **A**, **D**, **E**, **C** (tick cells), Suggested category, Overall result, Finding refs, Notes.
4. **Cut-off Testing**: Ref (CO-001), File, Supplier, Invoice no, Invoice date, Period basis, Period start, Period end, Position
   (Pre-YE/Post-YE/Spans), Recorded in (Current/Post-YE/Both/Neither), Posting date, Ledger amount, **A** (value), **P** (period
   tick), Apportionment working, Suggested adjustment (£), Overall result, Finding refs, Notes.
5. **Exceptions**: Ref, Test, Test ref, Status (Exception/Review), Issue type, File, Supplier, Invoice no, Explanation,
   AI reasoning, Suggested action, Amount impact (£), **Auditor conclusion** (blank), **Resolution** (dropdown data validation: Open / Cleared / Adjusted / Passed to ML), default Open.
6. **Processing Log**: every file and attachment that was failed, excluded or skipped, with its reason, plus the log file path.

Also write `output/run_results.json` (full RunResult, Decimals as strings) and copy it to `output/latest_run.json` for Power Automate.

---

## 15. Synthetic data (`synthetic/`)

Command: `uv run audit generate-data --seed 42 --out data/synthetic` (deterministic: same seed gives the same files and answer key).
**All names are fictional.** Include a README note: "Fictional entities. Any resemblance to real organisations is coincidental."

### 15.1 Entities
- Audited company: **Brackenfield Engineering Ltd** (alias: "Brackenfield Precision"). FY **1 Apr 2025 – 31 Mar 2026**.
- Group company: **Brackenfield Holdings Ltd**. Unrelated entity: **Calder Mill Catering Ltd**.
- ~13 fictional suppliers, each with a typical category, for example: Lumen Print & Design Ltd (Marketing), Carter & Vale LLP (Professional fees),
  Oakridge Property Management Ltd (Premises), Greenline Energy Supply Ltd (Utilities), Stackwise Software Ltd (IT),
  Meridian Business Travel Ltd (Travel), Fixwell Facilities Ltd (Repairs), Pemberton Steel Stockholders Ltd (Cost of sales),
  Harbour Office Supplies Ltd (Admin), Kestrel Insurance Brokers Ltd (Insurance), Atlas Machine Tools Ltd (Fixed assets),
  Bauer Komponenten GmbH (EUR, Cost of sales), Summit Cloud Inc. (USD, IT). Fake VAT numbers in the `GB` + 9 digits format.
- Invoice templates: at least 4 visual layouts (different header positions, table styles, fonts) so the extraction isn't trivially uniform.

### 15.2 The 60 invoices: format mix
| Format | Count | How produced |
|---|---|---|
| Digital PDF | 17 | reportlab |
| Scanned PDF | 10 | reportlab → `pypdfium2` raster at 150 dpi → Pillow: greyscale, slight rotation (±2°), noise, JPEG artefacts → image-only PDF |
| JPG photo | 6 | raster → perspective skew, uneven lighting gradient, slight blur, JPEG q≈70 |
| PNG scan | 6 | raster → greyscale, slight rotation, speckle |
| DOCX | 6 | python-docx (supplier details in the **header**, line items in a table) |
| XLSX | 6 | openpyxl invoice template layout |
| Email (.eml) | 9 invoices in 8 files | 6 files with one attachment (PDF/JPG), 1 file with **two** invoice attachments, 1 file with the invoice **in the body** |

Split: **35 in `main_sample/`**, **25 in `cutoff_sample/`**, each with a mix of formats. File names neutral (e.g. `doc_014.pdf`, `scan_03.jpg`).

### 15.3 Planted errors: main sample (35 invoices; 16 erroneous, 19 clean)
| ID | Type | Scenario | Expected |
|---|---|---|---|
| E01 | Value | Ledger net 1,234.50 vs invoice 1,243.50 (transposition) | A ✗ |
| E02 | Value | Ledger posted **gross** in the Net column (VAT included in error) | A ✗ |
| E03 | Value | Ledger typo 4,580.00 vs invoice 4,850.00 | A ✗ |
| E04 | Value | **1p** difference (612.34 vs 612.35) to prove exact-to-penny | A ✗ |
| E05 | Date | Invoice dated 15/02/2025 (prior FY) | D ✗ |
| E06 | Date | Invoice dated 12/05/2026 (after FY) posted in current ledger | D ✗ |
| E07 | Date | Invoice dated **31/03/2025**, one day before FY start (boundary) | D ✗ |
| E08 | Addressee | Addressed to Brackenfield Holdings Ltd (group) | E ✗ |
| E09 | Addressee | Addressed to Calder Mill Catering Ltd (unrelated) | E ✗ |
| E10 | Addressee | Addressed to "Mr J Brackenfield" personally | E ✗ |
| E11 | Classification | Exhibition stand hire and brochures, posted 6800 Admin → Marketing | C ✗ |
| E12 | Classification | New CNC lathe £18,500, posted 6700 Repairs → Fixed assets | C ✗ |
| E13 | Classification | Legal fees for a lease review, posted 6800 Admin → Professional fees | C ✗ |
| E14 | Classification | Electricity bill, posted 6300 Premises → Utilities | C ✗ |
| E15 | No match | Invoice number not in either ledger | Exception (no ledger entry) |
| E16 | FX | EUR invoice €3,200.00. Ledger original amount €3,020.00 | A ✗ |

Clean controls that **must pass** (all within the 19): invoices dated exactly 01/04/2025 and 31/03/2026 (boundaries);
addressee variants "BRACKENFIELD ENGINEERING LIMITED", "Brackenfield Engineering Ltd.", "Brackenfield Precision" (alias), and
"Brackenfeild Engineering Ltd" (typo, should score ≥ 92 — verify the score in a unit test and adjust the typo if not); a
USD invoice whose ledger original amount agrees; a ledger invoice number written with different spacing/case ("inv 2231" vs "INV2231").

**Edge-case files in `main_sample/`** (not counted in the 60):
- `corrupt_file.pdf` (truncated bytes) → failed, in Processing Log
- `supplier_statement.pdf` (a statement of account) → excluded (not an invoice)
- `blurry_receipt.jpg` (heavily blurred photo of a real-format invoice) → needs_review, checks Review
- `old_format.doc` (any bytes) → excluded (unsupported type)

### 15.4 Planted errors: cut-off sample (25 invoices; 12 erroneous/judgement, 13 clean)
| ID | Type | Scenario | Expected |
|---|---|---|---|
| C01 | Pre-YE in post-YE ledger | "Consultancy services – March 2026", invoice 10/04/2026, posted post-YE | ✗ understatement |
| C02 | Pre-YE in post-YE ledger | Goods with delivery note date 28/03/2026, invoice 02/04/2026, posted post-YE | ✗ understatement |
| C03 | Pre-YE in post-YE ledger | "Repairs carried out 24–26 March 2026", posted post-YE | ✗ understatement |
| C04 | Post-YE in current ledger | "Annual software licence 01/04/2026–31/03/2027", invoice 25/03/2026, posted current | ✗ overstatement |
| C05 | Post-YE in current ledger | "Rent for April 2026 in advance", invoice 25/03/2026, posted current | ✗ overstatement |
| C06 | Post-YE in current ledger | "Trade show sponsorship, event 14 May 2026", posted current | ✗ overstatement |
| C07 | Spans | Insurance 01/01/2026–31/12/2026, posted current | ? Review, prepayment = amount × 275/365 |
| C08 | Spans | Maintenance contract 01/02/2026–31/05/2026, posted post-YE | ? Review, accrual = amount × 59/120 |
| C09 | Spans | Cleaning services "Q1 and April 2026" (01/01/2026–30/04/2026), posted current | ? Review, prepayment = amount × 30/120 |
| C10 | Unrecorded | Pre-YE services (Feb 2026), in **neither** ledger | ✗ unrecorded liability |
| C11 | Both | Same invoice number in both ledgers | ✗ both periods |
| C12 | Not determinable | No period in description; invoice date 30/03/2026; posted current | ? Review (fallback) |

Clean: about 7 pre-YE items correctly in current (include a March 2026 service invoiced in April 2026 and **recorded in current** as an accrued
invoice: pass), and about 6 post-YE items correctly in post-YE.

(Day counts: C07 days_before = 90 [1 Jan–31 Mar], days_after = 275, total 365. C08: 59 + 61 = 120. C09: 90 + 30 = 120. Unit tests assert these.)

### 15.5 Ledgers
- `ledger_fy2026.xlsx`: current year, posting dates 01/04/2025–31/03/2026, about 150 lines in total: all main and cut-off
  invoices that are "recorded in current", plus about 100 **filler lines** (other suppliers and invoices not in the sample) so it looks real.
  Standard headers (section 5). `Currency`/`Original Amount` filled only for foreign-currency lines.
- `ledger_post_ye.xlsx`: posting dates 01/04/2026–30/06/2026, about 60 lines including the post-YE-recorded sample items plus filler.
- Amounts: net/VAT/gross consistent (20% VAT on most, 0% on a few, e.g. insurance is VAT-exempt), except where an error is planted.

### 15.6 Answer key (`answer_key.json`)
```json
{
  "seed": 42, "company": "...", "fy_start": "2025-04-01", "fy_end": "2026-03-31",
  "invoices": [
    {
      "invoice_id": "INV-M-014", "test": "main",
      "file": "main_sample/doc_014.pdf", "attachment": null, "format": "digital_pdf",
      "truth": { "supplier_name": "...", "addressed_to": "...", "invoice_number": "...", "invoice_date": "2025-11-03",
                 "currency": "GBP", "net_amount": "1243.50", "vat_amount": "248.70", "gross_amount": "1492.20",
                 "description": "...", "delivery_date": null, "service_period_start": "...", "service_period_end": "...",
                 "period_basis": "explicit_period", "true_category": "Marketing" },
      "planted_errors": ["E01"],
      "expected": { "overall": "exception", "checks": {"A": "exception", "D": "pass", "E": "pass", "C": "pass"} }
    }
  ],
  "edge_cases": [ { "file": "main_sample/corrupt_file.pdf", "expected_status": "failed" } ]
}
```

### 15.7 Scale generator
`uv run audit generate-data --scale 500 --seed 7 --out data/scale_500` generates N invoices by sampling the scenario templates
(same error ratios, varied suppliers, amounts and dates, and format mix weighted towards PDF), plus matching ledgers, an answer key and
a run file `data/scale_500/run.toml`. Output is gitignored. This proves the 100–500+ claim.

### 15.8 .msg (optional)
`scripts/make_msg_with_outlook.ps1`: if classic Outlook is installed, use COM (`Outlook.Application` → `CreateItem(0)`,
set subject/body, `Attachments.Add`, `SaveAs(path, 3)` = olMSG) to produce `.msg` copies of the synthetic emails in
`data/synthetic/msg_extra/`. Also copy one into `tests/fixtures/sample.msg` for the loader test. The msg loader test is
**skipped** if that fixture is absent. Not part of the 60.

---

## 16. Automated tests (`tests/`)

`pytest` config: `markers = ["live: calls the real Claude API (costs money)"]`, `addopts = "-m 'not live'"`.

| File | What it proves |
|---|---|
| `test_config.py` | example run file loads; fy_end ≤ fy_start rejected; missing folder/ledger → clear error; categories load and map codes |
| `test_money.py` | parses "1,234.50", "£1,234.50", "(100.00)" → −100.00, "1234.5", numbers; quantize rules |
| `test_ledger.py` | column mapping (renamed headers via config); missing required column → message listing the found headers; CSV + XLSX; currency default GBP |
| `test_matching.py` | invoice-number normalisation; addressee: exact, Ltd/Limited, alias, typo (≥92), group entity → exception, unrelated → exception, borderline → review |
| `test_validation.py` | each rule in section 10 sets the right status, reasons and weak_fields |
| `test_main_testing.py` | each check incl. penny difference, boundary dates both ends, FX agree/disagree/missing, unmapped code → review, no match, multiple matches, weak field → review |
| `test_cutoff.py` | every cell of the section 12 matrix; apportionment maths (C07/C08/C09 numbers); fallback never passes |
| `test_findings.py` | templates render with correct numbers; transposition note logic |
| `test_loaders.py` | small fixture files per format → expected block types/text (docx header + table captured; xlsx grid; eml attachments split + body fallback + inline logo skipped); corrupt PDF → LoaderError; encrypted PDF → LoaderError; .doc → excluded; .msg (skip if no fixture) |
| `test_cache.py` | miss → store → hit; key changes when model or PROMPT_VERSION changes; failures not cached |
| `test_live_runner.py` | **mocked** SDK client: one document raises → others still complete; failed record produced; progress reaches total |
| `test_batch_runner.py` | **mocked** client: chunking by bytes/count; results out of order matched by custom_id; errored → live retry; **resume** from `pending_batches.json` without resubmitting |
| `test_workpaper.py` | the 6 tabs exist with expected headers; Summary counts equal RunResult; every exception/review check has a finding with non-empty explanation; fills applied; Resolution dropdown present |
| `test_generator.py` | same seed → identical answer_key.json (hash); file counts per format = section 15.2; every planted error ID present once |
| **`test_planted_errors.py`** | **Headline test.** Build perfect `ExtractedInvoice`s from `answer_key.json` truth → run the real ledger loading, procedures and findings on the committed ledgers → **every planted error ID gives its expected check result, every clean invoice passes**, and edge cases have their expected status. Parametrised per invoice so failures are readable. |
| `test_recorded_e2e.py` | Replays **real recorded Claude outputs** (`tests/fixtures/recorded/*.json`, exported from a live run's cache) through the full pipeline with a fake client → same assertions as above, plus a written workpaper. Skipped until fixtures exist. |
| `test_live_e2e.py` (`@pytest.mark.live`) | Real API on all of `data/synthetic` → asserts 100% of planted errors caught. Reports (does not fail on) ≤ 2 unexpected exceptions among clean items. Run manually: `uv run pytest -m live`. |

### CI (`.github/workflows/ci.yml`)
On push/PR: matrix `windows-latest`, `ubuntu-latest`. Steps: checkout → `astral-sh/setup-uv` → `uv sync` → `uv run ruff check` → `uv run pytest`.
No secrets needed (live tests excluded). Add a CI badge to the README.

---

## 17. CLI (`cli.py`)

```
uv run audit run --config runs/example_fy2026.toml [--mode auto|live|batch] [--no-cache] [--limit N] [--dry-run]
uv run audit generate-data [--seed 42] [--out data/synthetic] [--scale N]
uv run audit init-config runs/my_client.toml
uv run audit cache stats | clear
```
Console output: rich panel with settings → progress bar(s) → summary table (per test: tested/pass/exception/review/value) →
cost line → `WORKPAPER: <path>` as the **last line** (Power Automate reads it). Detailed log at `logs/run_YYYYMMDD_HHMMSS.log`.

---

## 18. Power Automate Desktop (`pad/`, `scripts/run_audit.ps1`)

**Honest constraint (put this in pad/README.md):** free PAD on Windows 11 has no automatic "file arrived" trigger.
Cloud Power Automate has one (OneDrive/SharePoint "When a file is created"), but running a desktop flow from a cloud flow
needs a premium licence. So the free design is a **polling loop inside a running PAD flow**. The README's "Production
version" section describes the upgrade path: SharePoint document library → cloud flow trigger → run the job on a server or as an
Azure Function/Container → workpaper back to SharePoint/Teams.

`scripts/run_audit.ps1 -Config <path> [-Mode auto]`: `cd` to the repo, run `uv run audit run --config ...`, tee the output to the log,
exit with the CLI's exit code. Prints the `WORKPAPER:` line. Keeps the PAD flow simple.

**Flow "Invoice Audit: Watch & Run"** (`pad/invoice_audit_flow.txt` = actions as text to paste into the PAD designer.
`pad/README.md` = the same steps in words, with screenshot placeholders for the user to fill):
1. Set variables: `ProjectDir`, `InboxMain` (`%ProjectDir%\inbox\main`), `InboxCutoff`, `ProcessedDir`, `RunConfig`.
2. **Display select-from-list dialog**: "Use saved settings" / "Enter new settings".
   New: **Display custom form** (fallback: a sequence of input dialogs) asking for company name, FY start, FY end, tests to run,
   ledger file paths. Then **Write text to file** to produce `runs\pad_run.toml` from a template (`runs\pad_template.toml` with `{{placeholders}}`).
3. **Loop** (until the user stops the flow):
   a. **Get files in folder** (InboxMain and InboxCutoff). If the total is 0 → **Wait** 15 s → next iteration.
   b. Debounce: wait 15 s, count again. If the count changed (files still copying) → repeat. Else continue.
   c. **Run PowerShell script** → `scripts\run_audit.ps1 -Config runs\pad_run.toml`. Capture output and exit code.
   d. Exit code 0 or 2 → parse the `WORKPAPER:` line → **Launch Excel** with that file → **Display notification**
      "Invoice audit complete: X exceptions (see Summary)" (read counts from `output\latest_run.json` via **Convert JSON to custom object**).
      Exit code 1 → **Display message** with the error and the log path.
   e. **Move files** from the inbox folders to `%ProcessedDir%\<timestamp>\main|cutoff` (so they aren't re-processed. The cache would make a re-run free anyway).
4. The `inbox/` and `processed/` folders are gitignored.

A Claude session cannot run PAD. Write the flow text and docs as best-effort, and tell the user they must import and verify it manually.

---

## 19. Milestones (build in this order; each ends with tests passing and a commit)

| # | Milestone | Done when |
|---|---|---|
| M0 | **Setup**: install uv (`winget install --id=astral-sh.uv -e`), `uv python install 3.12`, `git init`, pyproject, skeleton package, ruff, pytest, `.gitignore`, `.env.example`, CI workflow, README stub. **Ask the user before** creating the public GitHub repo (`gh repo create invoice-audit-agent --public`) and pushing. | `uv run pytest` green (smoke test), CI green |
| M1 | **Core audit logic, no AI**: config, models, money, ledger, matching, procedures, findings + unit tests | sections 10–13 tests green |
| M2 | **Synthetic data**: entities, scenarios, all renderers, ledgers, answer key + `test_generator` + **`test_planted_errors`** | headline test green. Data committed. |
| M3 | **Loaders + discovery** for all formats + `test_loaders` | green |
| M4 | **Live extraction**: prompt, schema, request builder, live runner, cache, validation, cost, `--dry-run`, `--limit`. First real run on `--limit 5` (ask the user before spending). | 5 invoices extracted sensibly; second run all cache hits |
| M5 | **Workpaper + full pipeline + CLI polish** + `test_workpaper` | full run on 60 → workpaper; copy to `docs/sample_workpaper.xlsx` |
| M6 | **Batch mode**: chunking, persistence/resume, retries + `test_batch_runner`; run all 60 with `--mode batch --no-cache`; export recorded fixtures; `test_recorded_e2e`; `test_live_e2e` | all planted errors caught by real AI. Results noted in the README. |
| M7 | **Scale**: `--scale 500` generator; one 500-invoice batch run (ask the user first; estimate the cost with `--dry-run`) | timings + cost recorded in the README |
| M8 | **Power Automate**: `run_audit.ps1`, template run file, `pad/` docs + flow text; optional `.msg` script | user confirms the flow works on their laptop |
| M9 | **Portfolio polish**: README (problem → solution, mermaid architecture, screenshots of the workpaper, results table, cost at scale, "how I'd deploy this for a client on Microsoft 365/Azure", limitations), LICENSE | ready to share |

**Stretch (only after M9, only if the user asks):** Streamlit UI, duplicate-invoice check, Azure AI Document Intelligence
comparison, multi-invoice PDF splitting.

---

## 20. Out of scope (v1)

Sample selection, FX rate lookups, duplicate detection beyond "multiple ledger matches", splitting multi-invoice PDFs,
legacy `.doc`/`.xls`, zip files, HEIC photos, real client data, any RSM or other firm branding, a web UI.
