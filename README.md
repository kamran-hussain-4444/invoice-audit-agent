# invoice-audit-agent

> Work in progress. Full write-up to follow.

A Python CLI that reads large batches (100–500+) of invoices (PDF, scans, photos, Word, Excel, emails) with Claude,
then runs audit **main testing** and **cut-off testing** against ledger listings in plain, deterministic Python and
writes a formatted Excel workpaper. A Power Automate Desktop flow can trigger runs from a watched folder.

**AI reads, Python judges:** Claude only extracts fields. Every pass / exception / review decision is a Python rule.

## Quick start (Windows, PowerShell)

```powershell
uv sync           # install dependencies
uv run pytest     # offline tests (free)
uv run audit --help
```

Uses synthetic data only. Fictional entities. Any resemblance to real organisations is coincidental.
