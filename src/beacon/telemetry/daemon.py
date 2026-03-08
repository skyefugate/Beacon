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

from beacon.config import BeaconSettings, TelemetrySettings, get_settings, reset_settings
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
from beacon.telemetry.samplers.tcp import TcpSampler
from beacon.telemetry.samplers.nic import NicSampler
from beacon.telemetry.samplers.wifi import WiFiSampler
from beacon.telemetry.scheduler import TelemetryScheduler

logger = logging.getLogger(__name__)

_PID_FILE = Path("/tmp/beacon-telemetry.pid")

# Sampler name -> TelemetrySettings attribute that stores its interval.
_SAMPLER_INTERVAL_MAP = {
    "wifi": "tier0_wifi_interval",
    "ping": "tier0_ping_interval",
    "dns": "tier0_dns_interval",
    "http": "tier0_http_interval",
    "device": "tier0_device_interval",
    "context": "tier0_context_interval",
    "change": "change_detection_interval",
}

# Fields that require a full restart to apply safely.
_RESTART_REQUIRED_FIELDS = (
    "buffer_path",
    "buffer_max_mb",
    "buffer_retention_days",
)

# Export fields safe to hot-reload (logged for visibility only).
_EXPORT_LIVE_FIELDS = (
    "export_influx_bucket",
    "export_influx_enabled",
    "export_file_enabled",
    "export_file_path",
    "export_file_max_mb",
    "export_file_max_files",
    "export_batch_size",
)


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


def _reload_config(scheduler: TelemetryScheduler, config_path: Path | None = None) -> None:
    """Reload configuration and apply safe changes to running scheduler."""
    try:
        reset_settings()
        new_settings = get_settings(config_path)

        # Update log level
        level = getattr(logging, new_settings.log_level.upper(), logging.INFO)
        logging.getLogger().setLevel(level)

        # Update scheduler settings reference
        scheduler._settings = new_settings
        ts = new_settings.telemetry

        # Update sampler intervals
        for sampler in scheduler._samplers:
            interval_key = f"tier0_{sampler.name}_interval"
            if hasattr(ts, interval_key):
                sampler.default_interval = getattr(ts, interval_key)

        # Update sampler targets for ping, DNS, HTTP
        for sampler in scheduler._samplers:
            if sampler.name == "ping" and hasattr(sampler, "_targets"):
                sampler._targets = ts.ping_targets  # type: ignore[attr-defined]
                if hasattr(sampler, "_ping_gateway"):
                    sampler._ping_gateway = ts.ping_gateway  # type: ignore[attr-defined]
            elif sampler.name == "dns" and hasattr(sampler, "_resolvers"):
                sampler._resolvers = ts.dns_resolvers  # type: ignore[attr-defined]
                if hasattr(sampler, "_domains"):
                    sampler._domains = ts.dns_domains  # type: ignore[attr-defined]
            elif sampler.name == "http" and hasattr(sampler, "_targets"):
                sampler._targets = ts.http_targets  # type: ignore[attr-defined]

        logger.info("Configuration reloaded successfully")
    except Exception as e:
        logger.error("Failed to reload configuration: %s", e)


def _build_scheduler(settings: BeaconSettings) -> TelemetryScheduler:
    """Build the scheduler with all configured samplers and exporters."""
    ts = settings.telemetry

    # Tier 0 samplers
    samplers = [
        WiFiSampler(),
        TcpSampler(),
        NicSampler(),
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




def apply_config_reload(
    scheduler: TelemetryScheduler,
    old_ts: TelemetrySettings,
    new_settings: BeaconSettings,
) -> None:
    """Apply hot-reloadable config changes to a running scheduler.

    Mutates *scheduler* in-place.  Logs each changed field at INFO level.
    Fields that require a full restart are logged at WARNING level and skipped.
    """
    new_ts = new_settings.telemetry

    # --- sampler intervals ---
    for sampler_name, attr in _SAMPLER_INTERVAL_MAP.items():
        old_val = getattr(old_ts, attr)
        new_val = getattr(new_ts, attr)
        if old_val != new_val:
            scheduler.set_interval(sampler_name, new_val)
            logger.info(
                "SIGHUP reload: %s interval %ds -> %ds",
                sampler_name,
                old_val,
                new_val,
            )

    # --- sampler targets (update sampler attributes directly) ---
    sampler_by_name = {s.name: s for s in scheduler._samplers}

    ping_sampler = sampler_by_name.get("ping")
    if ping_sampler is not None:
        if old_ts.ping_targets != new_ts.ping_targets:
            ping_sampler._targets = list(new_ts.ping_targets)
            logger.info("SIGHUP reload: ping_targets -> %s", new_ts.ping_targets)
        if old_ts.ping_gateway != new_ts.ping_gateway:
            ping_sampler._ping_gateway = new_ts.ping_gateway
            logger.info("SIGHUP reload: ping_gateway -> %s", new_ts.ping_gateway)

    dns_sampler = sampler_by_name.get("dns")
    if dns_sampler is not None:
        if old_ts.dns_resolvers != new_ts.dns_resolvers:
            dns_sampler._resolvers = list(new_ts.dns_resolvers)
            logger.info("SIGHUP reload: dns_resolvers -> %s", new_ts.dns_resolvers)
        if old_ts.dns_domains != new_ts.dns_domains:
            dns_sampler._domains = list(new_ts.dns_domains)
            logger.info("SIGHUP reload: dns_domains -> %s", new_ts.dns_domains)

    http_sampler = sampler_by_name.get("http")
    if http_sampler is not None:
        if old_ts.http_targets != new_ts.http_targets:
            http_sampler._targets = list(new_ts.http_targets)
            logger.info("SIGHUP reload: http_targets -> %s", new_ts.http_targets)

    # --- export live settings (informational only) ---
    for field in _EXPORT_LIVE_FIELDS:
        old_val = getattr(old_ts, field)
        new_val = getattr(new_ts, field)
        if old_val != new_val:
            logger.info("SIGHUP reload: %s %r -> %r", field, old_val, new_val)

    # --- fields that require a full restart ---
    for field in _RESTART_REQUIRED_FIELDS:
        old_val = getattr(old_ts, field)
        new_val = getattr(new_ts, field)
        if old_val != new_val:
            logger.warning(
                "SIGHUP reload: %s changed %r -> %r — full restart required",
                field,
                old_val,
                new_val,
            )

    # Update the scheduler settings reference so export/aggregation loops see new values.
    scheduler._settings = new_settings

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

    def _handle_sighup() -> None:
        """Reload config from disk and apply live changes to the running scheduler."""
        logger.info("Received SIGHUP, reloading configuration...")
        old_settings = get_settings()
        old_ts = old_settings.telemetry
        config_path = old_settings.config_path

        reset_settings()
        try:
            new_settings = get_settings(config_path)
        except Exception as exc:
            logger.error(
                "SIGHUP reload: failed to parse config — keeping current settings: %s", exc
            )
            # Restore the old singleton so the daemon keeps running with prior config.
            import beacon.config as _cfg_mod
            _cfg_mod._settings = old_settings
            return

        apply_config_reload(scheduler, old_ts, new_settings)

        # Update log level if it changed.
        if old_settings.log_level != new_settings.log_level:
            new_level = getattr(logging, new_settings.log_level.upper(), logging.INFO)
            logging.getLogger().setLevel(new_level)
            logger.info(
                "SIGHUP reload: log_level %s -> %s",
                old_settings.log_level,
                new_settings.log_level,
            )

        logger.info("SIGHUP reload complete")

    try:
        loop.add_signal_handler(signal.SIGHUP, _handle_sighup)
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
