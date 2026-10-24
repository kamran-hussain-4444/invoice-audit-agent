"""Command-line entry point (`uv run audit ...`).

Commands (run, generate-data, init-config, cache) are added milestone by milestone (PLAN section 17).
"""

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
