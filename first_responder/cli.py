"""Command-line entry point for first-responder."""

from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(
    name="first-responder",
    help="Autonomous diagnosis agent for production incidents.",
    add_completion=False,
    no_args_is_help=True,
)


@app.command()
def diagnose(
    scenario: str = typer.Option(..., "--scenario", help="Scenario to diagnose."),
    trace: bool = typer.Option(False, "--trace", help="Print the reasoning trace."),
) -> None:
    """Diagnose a single scenario and emit a structured Diagnosis."""
    typer.echo(f"diagnose: scenario={scenario} trace={trace} (not yet implemented)")


@app.command()
def eval(
    all: bool = typer.Option(False, "--all", help="Score the agent across all scenarios."),
) -> None:
    """Score the agent against fault-injected scenarios with known ground truth."""
    typer.echo(f"eval: all={all} (not yet implemented)")


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
