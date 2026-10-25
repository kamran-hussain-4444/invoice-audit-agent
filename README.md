# invoice-audit-agent

[![CI](https://github.com/kamran-hussain-4444/invoice-audit-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kamran-hussain-4444/invoice-audit-agent/actions/workflows/ci.yml)

> Work in progress. Full write-up to follow.

A Python CLI that reads large batches (100–500+) of invoices (PDF, scans, photos, Word, Excel, emails) with Claude,
then runs audit **main testing** and **cut-off testing** against ledger listings in plain, deterministic Python and
writes a formatted Excel workpaper. A Power Automate Desktop flow can trigger runs from a watched folder.

**AI reads, Python judges:** Claude only extracts fields. Every pass / exception / review decision is a Python rule.

## Results so far

Synthetic engagement with planted errors (fictional client, see `data/synthetic/`). Model `claude-sonnet-5-5`,
effort `medium`, Message Batches API.

| Run | Documents | Planted errors caught | Clean invoices wrongly flagged | Time | Cost (USD) |
|---|---|---|---|---|---|
| 60-invoice engagement + 4 edge-case files | 62 sent to Claude | **28 / 28** | **0 / 32** | 10 min | $0.27 |
| 500-invoice scale test (`--scale 500`) | 500 | **234 / 234** | **0 / 266** | 8 min | $2.13 (≈ $0.004 per invoice) |
| Re-run of the 500 (cache) | 500 | same | same | seconds | $0.00 (0 API calls) |

- On the 60-invoice set, **660 / 660** extracted fields (supplier, addressee, invoice number, date, currency, net,
  VAT, gross, service period, category) matched the answer key exactly.
- Edge cases behaved as designed: a corrupt PDF failed cleanly without stopping the run, a legacy `.doc` and a
  supplier statement were excluded, and a deliberately blurred photo went to **Review**: nothing was guessed.
- Caveat: these are clean, generated documents. Real client scans will be harder; the confidence and rule checks
  exist so that anything Claude cannot read reliably becomes a Review item rather than a wrong answer.

A sample output is in [`docs/sample_workpaper.xlsx`](docs/sample_workpaper.xlsx).

## Quick start (Windows, PowerShell)

```powershell
uv sync                                                            # install dependencies
uv run pytest                                                      # offline tests (free)
uv run audit run --config runs/example_fy2026.toml --dry-run       # count files, estimate cost, no API calls
uv run audit run --config runs/example_fy2026.toml                 # full run → output/*.xlsx (needs .env)
```

Put your API key in `.env` as `ANTHROPIC_API_KEY=...` (copy `.env.example`).

Uses synthetic data only. Fictional entities. Any resemblance to real organisations is coincidental.
