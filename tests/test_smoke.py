"""Smoke tests: the package imports and the CLI runs."""

from __future__ import annotations

from typer.testing import CliRunner

from first_responder import __version__
from first_responder.cli import app

runner = CliRunner()


def test_version_is_non_empty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__.strip()


def test_cli_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
