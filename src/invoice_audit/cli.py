"""Command-line entry point (`uv run audit ...`), PLAN section 17.

Exit codes: 0 = completed, 2 = completed but some documents failed, 1 = fatal (settings, ledger, API key).
"""

from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from invoice_audit import __version__

app = typer.Typer(help="Invoice extraction and audit testing (main testing + cut-off).", no_args_is_help=True)
cache_app = typer.Typer(help="Inspect or clear the extraction cache.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")
console = Console()


@app.callback()
def main() -> None:
    """Invoice extraction and audit testing (main testing + cut-off)."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"invoice-audit-agent {__version__}")


def _load_config_or_exit(config: Path, check_files: bool = True):
    from invoice_audit.config import ConfigError, load_config

    try:
        return load_config(config, check_files=check_files)
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


def _settings_panel(cfg, mode: str) -> Panel:
    e, i = cfg.engagement, cfg.inputs
    lines = [
        f"Client: [bold]{e.company_name}[/bold]   Period: {e.fy_start:%d/%m/%Y} – {e.fy_end:%d/%m/%Y}",
        f"Tests: {', '.join(cfg.tests.run)}   Ledger: {i.ledger_type} (compare {cfg.amount_basis})",
        f"Model: {cfg.ai.model} (effort {cfg.ai.effort})   Mode: {mode}",
    ]
    return Panel("\n".join(lines), title="Invoice audit run", expand=False)


def _print_extractions(result) -> None:
    table = Table(title="Extracted documents", show_lines=False)
    for column in ("File", "Status", "Supplier", "Invoice no", "Date", "Gross", "Category", "Source"):
        table.add_column(column, overflow="fold")
    for record in result.records:
        inv = record.invoice
        status = record.status if not record.reasons else f"{record.status}: {'; '.join(record.reasons)[:60]}"
        table.add_row(
            record.source.display_name,
            status,
            inv.supplier_name if inv else "",
            inv.invoice_number if inv else "",
            f"{inv.invoice_date:%d/%m/%Y}" if inv and inv.invoice_date else "",
            f"{inv.currency or ''} {inv.gross_amount}" if inv and inv.gross_amount is not None else "",
            inv.suggested_category if inv else "",
            record.mode or "",
        )
    console.print(table)


def _print_summary(result) -> None:
    from invoice_audit.procedures.main_testing import value_tested

    table = Table(title="Results")
    for column in ("Test", "Tested", "Pass", "Exception", "Review", "Value tested (£)"):
        table.add_column(column, justify="right" if column != "Test" else "left")
    for name, rows in (("Main", result.main_rows), ("Cut-off", result.cutoff_rows)):
        if not rows and name.lower().replace("-", "") not in result.cfg.tests.run:
            continue
        counts = Counter(row.overall for row in rows)
        value = f"{value_tested(rows, result.cfg):,.2f}" if name == "Main" else ""
        table.add_row(name, str(len(rows)), str(counts["pass"]), str(counts["exception"]), str(counts["review"]), value)
    console.print(table)
    s = result.stats
    t = s.tokens
    console.print(
        f"Documents: {s.documents}  cache hits: {s.cache_hits}  API calls: {s.live_calls + s.batch_calls} "
        f"({s.mode})  tokens in/out/cache-read: {t.input_tokens:,}/{t.output_tokens:,}/{t.cache_read_tokens:,}  "
        f"estimated cost: ${s.cost_usd:.4f}  time: {s.duration_seconds:.0f}s"
    )
    console.print(f"Findings: {len(result.findings)}  failed documents: {len(result.failed)}")


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Run settings file (TOML)."),
    mode: str = typer.Option(None, help="auto | live | batch (overrides the settings file)."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cached extractions (re-pays for every document)."),
    limit: int = typer.Option(None, help="Only the first N documents per folder (cheap experiments)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count files and estimate cost. No API calls."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Also print every extracted document."),
) -> None:
    """Extract every invoice and run the audit tests."""
    from datetime import datetime

    from invoice_audit.ledger import LedgerError
    from invoice_audit.logging_setup import start_run_log
    from invoice_audit.pipeline import DryRun, FatalError, run_pipeline

    if mode not in (None, "auto", "live", "batch"):
        console.print("[red]--mode must be auto, live or batch[/red]")
        raise typer.Exit(1)
    cfg = _load_config_or_exit(config)
    console.print(_settings_panel(cfg, mode or cfg.ai.mode))
    log_path = start_run_log(Path("logs"), datetime.now())

    progress = Progress(
        TextColumn("[bold]Extracting"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("failed: {task.fields[failed]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    task = None
    failed = 0
    batch_mode = False

    def on_start(total: int, chosen_mode: str) -> None:
        nonlocal task, batch_mode
        batch_mode = chosen_mode == "batch"
        note = (
            " (Batches API: usually minutes, can take up to an hour; safe to Ctrl+C and re-run)" if batch_mode else ""
        )
        console.print(f"Extracting {total} document(s) in {chosen_mode} mode{note}...")
        progress.start()
        task = progress.add_task("extract", total=total, failed=0)

    def on_progress(result) -> None:
        nonlocal failed
        failed += result.outcome == "failed"
        if batch_mode:
            progress.update(task, failed=failed)  # batch progress comes from on_poll
        else:
            progress.update(task, advance=1, failed=failed)

    def on_poll(done: int) -> None:
        if task is None:
            console.print(f"Collecting a batch from an earlier run: {done} result(s) ready...")
        else:
            progress.update(task, completed=done)

    try:
        result = run_pipeline(cfg, mode, not no_cache, limit, dry_run, on_progress=on_progress, on_start=on_start,
                              on_poll=on_poll)  # fmt: skip
    except (FatalError, LedgerError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    finally:
        progress.stop()

    if isinstance(result, DryRun):
        kinds = ", ".join(f"{kind} {count}" for kind, count in sorted(result.by_kind.items()))
        console.print(f"Documents by type: {kinds}")
        console.print(f"Already cached: {result.cached}   New (need extraction): {result.new}   "
                      f"Excluded/unreadable: {result.skipped}")  # fmt: skip
        console.print(f"Mode: {result.mode}   Estimated cost: ${result.estimated_cost_usd:.2f} (no API calls made)")
        return

    from invoice_audit.workpaper import write_results_json, write_workpaper

    result.log_path = log_path
    result.workpaper_path = write_workpaper(result, cfg.output.folder)
    write_results_json(result, cfg.output.folder)
    if verbose:
        _print_extractions(result)
    _print_summary(result)
    console.print(f"Log: {log_path}")
    # Power Automate reads this exact last line, so print it plainly (no wrapping or colour).
    print(f"WORKPAPER: {result.workpaper_path.resolve()}")
    raise typer.Exit(2 if result.failed else 0)


@app.command("init-config")
def init_config(
    path: Path = typer.Argument(..., help="Where to write the new run file, e.g. runs/my_client.toml"),
) -> None:
    """Write a commented run-settings template to fill in for a new engagement."""
    from invoice_audit.config import RUN_TEMPLATE

    if path.exists():
        console.print(f"[red]{path} already exists. Choose another name or delete it first.[/red]")
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RUN_TEMPLATE, encoding="utf-8")
    console.print(f"Wrote {path}. Fill in the [engagement] and [inputs] sections, then run:")
    console.print(f"  uv run audit run --config {path.as_posix()} --dry-run")


@cache_app.command("stats")
def cache_stats(config: Path = typer.Option(Path("runs/example_fy2026.toml"), "--config", "-c")) -> None:
    """Show how many extractions are cached."""
    from invoice_audit.extraction.cache import ExtractionCache

    cfg = _load_config_or_exit(config, check_files=False)
    stats = ExtractionCache(cfg.ai.cache_path).stats()
    console.print(f"Cache: {stats['path']}\nEntries: {stats['entries']}")
    for model, prompt_version, count in stats["by_model"]:
        console.print(f"  {model} (prompt v{prompt_version}): {count}")


@cache_app.command("clear")
def cache_clear(
    config: Path = typer.Option(Path("runs/example_fy2026.toml"), "--config", "-c"),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Delete every cached extraction (the next run pays again for every document)."""
    from invoice_audit.extraction.cache import ExtractionCache

    cfg = _load_config_or_exit(config, check_files=False)
    if not yes and not typer.confirm("Delete all cached extractions? The next run will pay for them again."):
        raise typer.Exit(0)
    removed = ExtractionCache(cfg.ai.cache_path).clear()
    console.print(f"Removed {removed} cached extraction(s).")


@app.command("generate-data")
def generate_data(
    seed: int = typer.Option(42, help="Random seed. The same seed always gives the same files."),
    out: Path = typer.Option(Path("data/synthetic"), help="Folder to write into."),
    scale: int | None = typer.Option(
        None, help="Generate N invoices for a load test (written to data/scale_N, not committed)."
    ),
) -> None:
    """Generate the synthetic engagement: invoices, ledgers and answer_key.json."""
    from invoice_audit.synthetic.generate import generate
    from invoice_audit.synthetic.scale import generate_scale

    if scale is not None:
        if out == Path("data/synthetic"):
            out = Path(f"data/scale_{scale}")  # never overwrite the committed 60-invoice data set
        if scale < 60:
            typer.echo("--scale needs at least 60 invoices.", err=True)
            raise typer.Exit(1)
        answer_key = generate_scale(scale, seed, out)
        typer.echo(f"Run it: uv run audit run --config {out.as_posix()}/run.toml --dry-run")
    else:
        answer_key = generate(seed, out)
    formats = Counter(item["format"] for item in answer_key["invoices"])
    typer.echo(f"Wrote {len(answer_key['invoices'])} invoices + {len(answer_key['edge_cases'])} edge cases to {out}")
    for name, count in sorted(formats.items()):
        typer.echo(f"  {name:<12} {count}")
