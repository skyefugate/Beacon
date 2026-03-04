"""CLI commands for the telemetry subsystem — start, stop, status."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

import typer
from rich.console import Console

from beacon.config import get_settings

telemetry_app = typer.Typer(
    name="telemetry",
    help="Manage the continuous telemetry daemon",
    no_args_is_help=True,
)

console = Console()


@telemetry_app.command()
def start(
    daemon: bool = typer.Option(
        False, "--daemon", "-d",
        help="Run as a background daemon",
    ),
    config: Path | None = typer.Option(
        None, "--config", "-c",
        help="Path to beacon.yaml config file",
    ),
) -> None:
    """Start the telemetry daemon."""
    from beacon.telemetry.daemon import read_pid, run

    existing = read_pid()
    if existing is not None:
        console.print(f"[yellow]Telemetry daemon already running (PID {existing})[/yellow]")
        raise typer.Exit(1)

    if daemon:
        console.print("[green]Starting telemetry daemon in background...[/green]")
        # Fork into background
        pid = os.fork()
        if pid > 0:
            console.print(f"[green]Daemon started (PID {pid})[/green]")
            return
        # Child process
        os.setsid()
        sys.stdin.close()
        run(config_path=config, daemon=True)
    else:
        console.print("[green]Starting telemetry (foreground)...[/green]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        run(config_path=config)


@telemetry_app.command()
def stop() -> None:
    """Stop the telemetry daemon."""
    from beacon.telemetry.daemon import read_pid

    pid = read_pid()
    if pid is None:
        console.print("[yellow]Telemetry daemon is not running[/yellow]")
        raise typer.Exit(1)

    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent SIGTERM to daemon (PID {pid})[/green]")
    except ProcessLookupError:
        console.print("[yellow]Daemon process not found[/yellow]")
    except PermissionError:
        console.print("[red]Permission denied sending signal[/red]")
        raise typer.Exit(1)


@telemetry_app.command()
def status() -> None:
    """Show telemetry daemon status."""
    from beacon.telemetry.daemon import read_pid

    settings = get_settings()

    pid = read_pid()
    if pid is not None:
        console.print(f"[green]Telemetry daemon is running (PID {pid})[/green]")
    else:
        console.print("[yellow]Telemetry daemon is not running[/yellow]")

    console.print(f"\n[bold]Configuration:[/bold]")
    ts = settings.telemetry
    console.print(f"  Enabled:        {ts.enabled}")
    console.print(f"  Window:         {ts.window_seconds}s")
    console.print(f"  Buffer:         {ts.buffer_path}")
    console.print(f"  InfluxDB:       {'enabled' if ts.export_influx_enabled else 'disabled'}")
    console.print(f"  File export:    {'enabled' if ts.export_file_enabled else 'disabled'}")
