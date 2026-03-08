"""CLI command for self-checking agent health, connectivity, and config."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import typer
from rich.console import Console
from rich.table import Table

from beacon.config import _load_yaml_config, get_settings

doctor_app = typer.Typer(
    name="doctor",
    help="Self-check agent health, connectivity, and configuration",
    no_args_is_help=False,
)

console = Console()

PASS = "[bold green]PASS[/bold green]"
FAIL = "[bold red]FAIL[/bold red]"


def _check_config_readable() -> tuple[bool, str]:
    """Check that config file is readable and valid YAML."""
    candidates = [
        Path("beacon.yaml"),
        Path("/etc/beacon/beacon.yaml"),
        Path.home() / ".config" / "beacon" / "beacon.yaml",
    ]
    config_path = None
    for candidate in candidates:
        if candidate.is_file():
            config_path = candidate
            break

    if config_path is None:
        return True, "No config file found; using built-in defaults"

    try:
        data = _load_yaml_config(config_path)
        if data is None:
            return True, f"{config_path} is empty (defaults used)"
        return True, f"{config_path} is readable and valid YAML"
    except Exception as exc:  # noqa: BLE001
        return False, f"{config_path}: {exc}"


def _check_influxdb_reachable() -> tuple[bool, str]:
    """Ping InfluxDB URL (GET /ping)."""
    settings = get_settings()
    url = settings.influxdb.url.rstrip("/") + "/ping"
    try:
        with urlopen(url, timeout=5) as resp:  # noqa: S310
            return True, f"InfluxDB reachable at {settings.influxdb.url} (HTTP {resp.status})"
    except HTTPError as exc:
        return True, f"InfluxDB reachable at {settings.influxdb.url} (HTTP {exc.code})"
    except URLError as exc:
        return False, f"InfluxDB unreachable at {settings.influxdb.url}: {exc.reason}"
    except OSError as exc:
        return False, f"InfluxDB unreachable at {settings.influxdb.url}: {exc}"


def _check_collector_reachable() -> tuple[bool, str]:
    """GET /health on the collector URL."""
    settings = get_settings()
    url = settings.collector.url.rstrip("/") + "/health"
    try:
        with urlopen(url, timeout=5) as resp:  # noqa: S310
            return True, f"Collector reachable at {settings.collector.url} (HTTP {resp.status})"
    except HTTPError as exc:
        return True, f"Collector reachable at {settings.collector.url} (HTTP {exc.code})"
    except URLError as exc:
        return False, f"Collector unreachable at {settings.collector.url}: {exc.reason}"
    except OSError as exc:
        return False, f"Collector unreachable at {settings.collector.url}: {exc}"


def _check_daemon_running() -> tuple[bool, str]:
    """Check if the telemetry daemon PID file exists and process is alive."""
    from beacon.telemetry.daemon import read_pid

    pid = read_pid()
    if pid is not None:
        return True, f"Telemetry daemon is running (PID {pid})"
    return False, "Telemetry daemon is not running (no PID file or stale PID)"


def _check_airport_binary() -> tuple[bool, str]:
    """Check that the macOS airport binary is available."""
    airport_path = (
        "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    )
    if Path(airport_path).is_file():
        return True, f"airport binary found at {airport_path}"
    fallback = shutil.which("airport")
    if fallback:
        return True, f"airport binary found at {fallback}"
    return False, "airport binary not found (Wi-Fi diagnostics may be limited)"


def _check_data_dir_writable() -> tuple[bool, str]:
    """Check that the configured data directory is writable."""
    settings = get_settings()
    data_dir: Path = settings.storage.data_dir

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file = data_dir / ".beacon_doctor_write_test"
        test_file.write_text("ok")
        test_file.unlink()
        return True, f"Data directory is writable: {data_dir.resolve()}"
    except OSError as exc:
        return False, f"Data directory not writable ({data_dir}): {exc}"


CHECKS = [
    ("Config file readable and valid YAML", _check_config_readable),
    ("InfluxDB reachable", _check_influxdb_reachable),
    ("Collector reachable", _check_collector_reachable),
    ("Telemetry daemon running", _check_daemon_running),
    ("airport binary available (macOS)", _check_airport_binary),
    ("Data directory writable", _check_data_dir_writable),
]


@doctor_app.callback(invoke_without_command=True)
def doctor(ctx: typer.Context) -> None:
    """Run all self-checks and report results."""
    if ctx.invoked_subcommand is not None:
        return

    table = Table(title="Beacon Doctor", show_header=True, header_style="bold cyan")
    table.add_column("Check", style="dim", width=40)
    table.add_column("Status", justify="center", width=6)
    table.add_column("Details")

    failures = 0
    for label, fn in CHECKS:
        ok, detail = fn()
        status = PASS if ok else FAIL
        table.add_row(label, status, detail)
        if not ok:
            failures += 1

    console.print()
    console.print(table)
    console.print()

    if failures == 0:
        console.print("[bold green]All checks passed.[/bold green]")
    else:
        console.print(f"[bold red]{failures} check(s) failed.[/bold red] Review the details above.")
        raise typer.Exit(1)
