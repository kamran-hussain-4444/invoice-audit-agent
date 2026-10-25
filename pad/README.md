# Power Automate Desktop: "Invoice Audit: Watch & Run"

This flow watches an inbox folder. When invoices arrive it runs the audit, opens the workpaper in Excel and tells
you how many exceptions were found. The Python tool works fully without it; this is the Microsoft automation layer.

## The honest constraint

Free Power Automate Desktop (PAD) on Windows 11 has **no "when a file arrives" trigger**. Cloud Power Automate does
(OneDrive/SharePoint "When a file is created"), but starting a desktop flow from a cloud flow needs a premium
licence. So this free version is a **polling loop inside a running PAD flow**: it checks the inbox every 15 seconds
while the flow is running. See [Production version](#production-version) for how it would work at a client.

## What happens

```
inbox\main  ┐                    ┌─ Excel opens the workpaper
inbox\cutoff┘ → PAD sees files → run_audit.ps1 → audit run ─┼─ message: "N exceptions, M review items"
                                                    └─ files moved to processed\<timestamp>\
```

- `scripts\run_audit.ps1` does the work (runs the audit, writes a log, moves processed files). PAD just watches,
  calls it and shows the result, so the flow stays short.
- Settings come from `runs\pad_run.toml`. It is ready to use with the fictional client (Brackenfield Engineering)
  and its ledgers in `data\synthetic\`.

## Before you start

1. The project works from PowerShell: `uv run audit run --config runs/pad_run.toml --dry-run` prints a cost estimate.
2. In this guide the project folder is `C:\Users\mistr\Projects\invoice-audit-agent`. If yours differs, change the
   `ProjectDir` variable in step 1.

## Build the flow (about 20 minutes)

Open **Power Automate** → **+ New flow** → name it `Invoice Audit: Watch & Run` → **Create**.
The designer opens: actions are in the left panel (use its search box), the flow is built in the middle.
To add an action, drag it into the middle or double-click it. Text in `%...%` is a variable; type it exactly.

> Screenshot placeholder: the empty designer with the Actions panel on the left.

### Part A: variables (5 actions)

Search **Set variable** and add it five times. For each, set the variable name (click the name to rename it) and
the value:

| # | Variable | Value |
|---|---|---|
| 1 | `ProjectDir` | `C:\Users\mistr\Projects\invoice-audit-agent` |
| 2 | `InboxMain` | `%ProjectDir%\inbox\main` |
| 3 | `InboxCutoff` | `%ProjectDir%\inbox\cutoff` |
| 4 | `RunConfig` | `%ProjectDir%\runs\pad_run.toml` |
| 5 | `LastCount` | `0` |

Then add **Create folder** twice (folder `%ProjectDir%\inbox`, names `main` and `cutoff`), so the inbox exists.

### Part B: the watch loop

7. Add **Loop condition**: First operand `1`, Operator `Equal to (=)`, Second operand `1`.
   (Runs until you press Stop.) Every action below goes **inside** this loop.
8. **Get files in folder**: Folder `%InboxMain%`, File filter `*`, Include subfolders **on**.
   In "Variables produced" rename `Files` to `MainFiles`.
9. **Get files in folder** again: Folder `%InboxCutoff%`, produced variable `CutoffFiles`.
10. **Set variable** `Total` = `%MainFiles.Count + CutoffFiles.Count%`
11. **If**: First operand `%Total%`, Operator `Equal to (=)`, Second operand `0`.
    Inside the If: **Wait** `15` seconds, then **Next loop**. (Add **End** if PAD didn't.)
12. Debounce, so you don't start while files are still copying. After the If's **End**:
    - **If** `%Total%` `Not equal to (<>)` `%LastCount%`: inside it **Set variable** `LastCount` = `%Total%`,
      **Wait** `15`, **Next loop**.
    (The run starts only when the file count has stayed the same for 15 seconds.)
13. **Run PowerShell script** with this script:
    ```
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ProjectDir%\scripts\run_audit.ps1" -Config "%RunConfig%" -ArchiveInbox
    ```
    Produced variable: `PowershellOutput` (leave the error variable as is).
14. **Set variable** `LastCount` = `0`
15. **If** `%PowershellOutput%` `Contains` `EXITCODE: 1`:
    - **Display message**: Title `Invoice audit failed`, Message
      `The run stopped with an error. Details:%PowershellOutput%`
    - **Else** (add the **Else** action), then steps 16–19 go inside the Else.
16. **Parse text**: Text to parse `%PowershellOutput%`, Text to find `(?<=WORKPAPER: ).+`,
    "Is regular expression" **on**. Produced variable `WorkpaperPath` (rename from `Match`).
17. **Run application**: Application path `%WorkpaperPath%`. (Windows opens .xlsx files in Excel.)
18. **Read text from file**: File path `%ProjectDir%\output\latest_run.json`, Encoding `UTF-8`.
    Produced variable `LatestRunJson`. Then **Convert JSON to custom object**: JSON `%LatestRunJson%`,
    produced variable `LatestRun`.
19. **Display message**: Title `Invoice audit complete`, Message
    `%LatestRun['counts']['exceptions']% exceptions and %LatestRun['counts']['reviews']% review items. See the Summary tab.`
    Turn on "Close message box automatically" with a timeout of `20` seconds, so the loop carries on.

Save (Ctrl+S).

> Screenshot placeholder: the finished flow.

### Part C (optional): "Enter new settings" launcher

Add these **before** the loop (between Part A and Part B):

1. **Display select from list dialog**: Title `Invoice audit`, Message `Which settings?`, List
   `Use saved settings` and `Enter new settings` (one per line). Produced variable `SelectedItem`.
2. **If** `%SelectedItem%` `Equal to (=)` `Enter new settings`:
   - **Display input dialog** three times (Title `Invoice audit`), producing `CompanyName`, `FyStart`, `FyEnd`.
     Messages: `Company name as it appears on invoices`, `Financial year start (YYYY-MM-DD)`,
     `Financial year end (YYYY-MM-DD)`.
   - **Display select file dialog** twice, producing `CurrentLedger` (title `Current-year ledger`) and
     `PostYeLedger` (title `Post-year-end ledger`). Filter `*.xlsx;*.csv`.
   - **Read text from file** `%ProjectDir%\runs\pad_template.toml` → `Template`.
   - **Replace text** five times on `%Template%` (save each result back into `Template`):
     `{{company_name}}` → `%CompanyName%`, `{{fy_start}}` → `%FyStart%`, `{{fy_end}}` → `%FyEnd%`,
     `{{current_ledger}}` → `%CurrentLedger%`, `{{post_ye_ledger}}` → `%PostYeLedger%`.
   - **Write text to file**: File `%RunConfig%`, Text `%Template%`, If file exists **Overwrite contents**,
     Encoding `UTF-8`.

(The template puts ledger paths in single quotes, so Windows backslashes are fine. A path containing a single
quote `'` would break it; in that case edit `runs\pad_run.toml` by hand instead.)

## Try it

1. Press **Run** (▶) in the designer. Nothing happens yet: the inbox is empty.
2. Copy a few invoices from `data\synthetic\main_sample` into `inbox\main` (and from `cutoff_sample` into
   `inbox\cutoff` if you like).
3. Within about 30 seconds the run starts. Invoices already in the cache cost nothing; new ones are sent to Claude.
4. Excel opens the workpaper and a message shows the exception count. The files move to `processed\<timestamp>\`.
5. Press **Stop** in PAD to end the watch.

Check: `logs\pad_<timestamp>.log` has the full console output of each run.

## If something goes wrong

| Symptom | Fix |
|---|---|
| "uv was not found" in the output | Install uv (`winget install --id=astral-sh.uv -e`) and restart PAD. |
| "ANTHROPIC_API_KEY is not set" | Create `.env` in the project folder (copy `.env.example`). |
| Excel doesn't open | Check `%WorkpaperPath%` in the Variables pane after a run; it should end in `.xlsx`. |
| The run never starts | Is the flow running (not just saved)? Are the files in `inbox\main` or `inbox\cutoff`? |
| Message shows `%LatestRun[...]%` literally | Check step 18 produced `LatestRun`; names are case-sensitive. |

**Shortcut:** `pad\invoice_audit_flow.txt` contains Part A and Part B in PAD's text format. Open it, copy everything
(Ctrl+A, Ctrl+C), click in the empty flow in the designer and paste (Ctrl+V). This was verified in PAD on
Windows 11 (October 2026). If a future PAD version shows an "Unknown action", delete it and add that action by hand
using the steps above; the other actions still paste.

## Production version

At a client this would not run on a laptop:

1. Auditors drop invoices into a **SharePoint document library** for the engagement.
2. A **cloud flow** triggers on "When a file is created" (no polling) and batches arrivals.
3. The audit runs as an **Azure Function or Container App** (the Python core is unchanged; the API key lives in
   **Azure Key Vault**). Claude can also be reached through **Microsoft Foundry**, keeping traffic in the Azure tenant.
4. The workpaper is written back to SharePoint and a **Teams** message posts the exception count with a link.
5. Reviewers record conclusions in the Exceptions tab; the run results JSON could feed a Power BI dashboard.
