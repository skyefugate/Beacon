"""Daemon entry point — runs the telemetry scheduler as a background process.

Handles signal management (SIGTERM, SIGHUP), PID file, and logging setup.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from beacon.config import BeaconSettings, get_settings
from beacon.telemetry.buffer import SQLiteBuffer
from beacon.telemetry.export.base import BaseExporter
from beacon.telemetry.export.file import FileExporter
from beacon.telemetry.export.influx import InfluxExporter
from beacon.telemetry.samplers.change import ChangeDetector
from beacon.telemetry.samplers.context import ContextSampler
from beacon.telemetry.samplers.device import DeviceSampler
from beacon.telemetry.samplers.dns import DNSSampler
from beacon.telemetry.samplers.http import HTTPSampler
from beacon.telemetry.samplers.ping import PingSampler
from beacon.telemetry.samplers.wifi import WiFiSampler
from beacon.telemetry.scheduler import TelemetryScheduler

logger = logging.getLogger(__name__)

_PID_FILE = Path("/tmp/beacon-telemetry.pid")


def _setup_logging(settings: BeaconSettings) -> None:
    """Configure logging for daemon mode."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def _write_pid() -> None:
    """Write PID file."""
    _PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    """Remove PID file."""
    try:
        _PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def read_pid() -> int | None:
    """Read PID from file, or None if not running."""
    try:
        if _PID_FILE.exists():
            pid = int(_PID_FILE.read_text().strip())
            # Check if process is alive
            os.kill(pid, 0)
            return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        pass
    return None


def _build_scheduler(settings: BeaconSettings) -> TelemetryScheduler:
    """Build the scheduler with all configured samplers and exporters."""
    ts = settings.telemetry

    # Tier 0 samplers
    samplers = [
        WiFiSampler(),
        PingSampler(
            targets=ts.ping_targets,
            ping_gateway=ts.ping_gateway,
        ),
        DNSSampler(resolvers=ts.dns_resolvers, domains=ts.dns_domains),
        HTTPSampler(targets=ts.http_targets),
        DeviceSampler(),
        ContextSampler(
            public_ip_ttl=ts.context_public_ip_ttl,
            geo_ttl=ts.context_geo_ttl,
            geo_enabled=ts.context_geo_enabled,
        ),
        ChangeDetector(),
    ]

    # Apply configured intervals
    for sampler in samplers:
        interval_key = f"tier0_{sampler.name}_interval"
        if hasattr(ts, interval_key):
            sampler.default_interval = getattr(ts, interval_key)

    buffer = SQLiteBuffer(
        path=ts.buffer_path,
        max_mb=ts.buffer_max_mb,
        retention_days=ts.buffer_retention_days,
    )

    exporters: list[BaseExporter] = []
    if ts.export_influx_enabled:
        exporters.append(InfluxExporter(settings, buffer))
    if ts.export_file_enabled:
        exporters.append(
            FileExporter(
                path=ts.export_file_path,
                max_mb=ts.export_file_max_mb,
                max_files=ts.export_file_max_files,
            )
        )

    return TelemetryScheduler(settings, samplers, buffer, exporters)


async def _run_daemon(settings: BeaconSettings) -> None:
    """Main async daemon loop."""
    scheduler = _build_scheduler(settings)
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _handle_signal(signum: int) -> None:
        logger.info("Received signal %d, stopping...", signum)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    def _handle_sighup(signum: int) -> None:
        logger.info("Received SIGHUP, reloading not yet implemented")

    try:
        loop.add_signal_handler(signal.SIGHUP, _handle_sighup, signal.SIGHUP)
    except (ValueError, OSError):
        pass  # SIGHUP not available on all platforms

    await scheduler.start()
    logger.info("Beacon telemetry daemon running (PID %d)", os.getpid())

    await stop_event.wait()
    await scheduler.stop()


def run(config_path: Path | None = None, daemon: bool = False) -> None:
    """Entry point for the telemetry daemon."""
    settings = get_settings(config_path)
    _setup_logging(settings)

    if not settings.telemetry.enabled:
        logger.error("Telemetry is not enabled in configuration. Set telemetry.enabled=true")
        sys.exit(1)

    existing = read_pid()
    if existing is not None:
        logger.error("Daemon already running (PID %d)", existing)
        sys.exit(1)

    _write_pid()
    try:
        asyncio.run(_run_daemon(settings))
    finally:
        _remove_pid()
