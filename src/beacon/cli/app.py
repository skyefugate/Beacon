"""Typer CLI application assembly — the main entry point."""

from __future__ import annotations

import typer

from beacon import __version__
from beacon.cli.commands.evidence import evidence_app
from beacon.cli.commands.metrics import metrics_app
from beacon.cli.commands.packs import packs_app
from beacon.cli.commands.run import run_app
from beacon.cli.commands.server import server_app
from beacon.cli.commands.telemetry import telemetry_app

app = typer.Typer(
    name="beacon",
    help="Beacon — Docker-first network diagnostics platform",
    no_args_is_help=True,
)


def version_callback(value: bool):
    if value:
        typer.echo(f"beacon {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version",
    ),
):
    """Beacon — turn subjective 'it's slow' into repeatable evidence."""
    pass


app.add_typer(server_app, name="server")
app.add_typer(run_app, name="run")
app.add_typer(packs_app, name="packs")
app.add_typer(evidence_app, name="evidence")
app.add_typer(metrics_app, name="metrics")
app.add_typer(telemetry_app, name="telemetry")
