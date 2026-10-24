"""Smoke test: the package installs and the CLI starts."""

from typer.testing import CliRunner

from invoice_audit import __version__
from invoice_audit.cli import app


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
