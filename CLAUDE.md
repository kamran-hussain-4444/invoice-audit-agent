# CLAUDE.md

## What this is
`invoice-audit-agent` is a Python CLI that extracts data from large batches (100–500+) of invoices (PDF, scans, photos,
Word, Excel, emails) with Claude, then runs audit **main testing** and **cut-off testing** against ledger listings and
writes a formatted Excel workpaper. It's a public portfolio project for a Forward Deployed Engineer application at mhance
(a Microsoft partner), so a Power Automate Desktop flow is the trigger layer.

**The full build spec is in [PLAN.md](PLAN.md). Read it before starting any work.** It records agreed decisions (section 2).
Don't reverse them without asking the user.

## The user
An ACA trainee auditor and **beginner programmer**. They know the audit side well (use correct audit terms) but need code
choices explained simply: what you did, why, and the one command to run. Recommend the simplest professional option.
Don't offer long lists of alternatives.

## Hard rules
- **Synthetic data only.** Never add real client data. **No RSM (or any firm) branding** in code, docs or output.
- **AI reads, Python judges.** Claude only extracts fields, suggests a category and infers the service period. Every
  pass/exception/review decision is a deterministic Python rule (PLAN sections 11–12).
- **Never guess.** Unreadable or low-confidence data gives Review, never Pass or Exception (PLAN section 10).
- **Money is `Decimal`**, never float. Value test is exact to the penny by default.
- **One bad file never crashes a run.** Catch per document, log it, continue. Only config/ledger/API-key problems are fatal.
- **Before writing or changing any Claude API code, load the `claude-api` skill** and follow it (model IDs, structured
  outputs, Batches API, caching). Don't write SDK calls from memory. Default model `claude-sonnet-5-5` (configurable).
- Bump `PROMPT_VERSION` in `extraction/prompt.py` whenever the prompt or schema changes (it is part of the cache key).
- **Ask before spending money**: any live/batch run beyond the offline tests. Use `--dry-run` to show an estimate first.
- **Ask before outward-facing actions**: creating the GitHub repo, pushing, making it public.
- Never commit `.env`, `.cache/`, `output/`, `logs/`, `inbox/`, `processed/` or `data/scale_*`.
  `data/synthetic/` and `docs/sample_workpaper.xlsx` **are** committed.

## Commands
```powershell
uv sync                                                    # install/refresh dependencies
uv run pytest                                              # offline tests (free; what CI runs)
uv run pytest -m live                                      # real-API end-to-end test (costs money, ask first)
uv run ruff check . ; uv run ruff format .                 # lint / format
uv run audit generate-data --seed 42 --out data/synthetic  # regenerate synthetic invoices + ledgers + answer key
uv run audit run --config runs/example_fy2026.toml --dry-run   # count files + estimate cost, no API calls
uv run audit run --config runs/example_fy2026.toml             # full run → output/*.xlsx
```
The API key goes in `.env` as `ANTHROPIC_API_KEY=...` (copy `.env.example`).

## Environment
Windows 11 laptop, PowerShell, Python 3.12 via uv. The project lives at `C:\Users\mistr\Projects\invoice-audit-agent`
(deliberately **not** in OneDrive). Use `pathlib` everywhere. No hard-coded `\` paths. Code must also pass CI on Ubuntu.

## Conventions
- Source in `src/invoice_audit/`, tests in `tests/`, layout per PLAN section 4.
- Type hints on public functions. Pydantic models for config and extraction results.
- Short docstrings that explain *why* for anything audit-specific. Keep code beginner-readable: plain functions over clever abstractions.
- Every new rule or planted error gets a test. `tests/test_planted_errors.py` is the headline proof and must stay green.
- Build milestone by milestone (PLAN section 19). Finish each with green tests and a commit, then summarise for the user in plain English.
