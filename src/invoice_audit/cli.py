"""Command-line entry point (`uv run audit ...`).

Commands (run, generate-data, init-config, cache) are added milestone by milestone (PLAN section 17).
"""

from collections import Counter
from pathlib import Path

import typer

from invoice_audit import __version__

app = typer.Typer(help="Invoice extraction and audit testing (main testing + cut-off).", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Invoice extraction and audit testing (main testing + cut-off)."""
    # A callback keeps `audit` a command group even while it only has one command.


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"invoice-audit-agent {__version__}")


@app.command("generate-data")
def generate_data(
    seed: int = typer.Option(42, help="Random seed. The same seed always gives the same files."),
    out: Path = typer.Option(Path("data/synthetic"), help="Folder to write into."),
    scale: int | None = typer.Option(None, help="Generate N invoices for a load test (milestone M7)."),
) -> None:
    """Generate the synthetic engagement: invoices, ledgers and answer_key.json."""
    from invoice_audit.synthetic.generate import generate

    if scale is not None:
        typer.echo("--scale is not available yet (it arrives in milestone M7).", err=True)
        raise typer.Exit(1)
    answer_key = generate(seed, out)
    formats = Counter(item["format"] for item in answer_key["invoices"])
    typer.echo(f"Wrote {len(answer_key['invoices'])} invoices + {len(answer_key['edge_cases'])} edge cases to {out}")
    for name, count in sorted(formats.items()):
        typer.echo(f"  {name:<12} {count}")
