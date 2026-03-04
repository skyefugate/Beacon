"""Change detector — polls system state and emits Events on changes.

Detects changes in: default route, DNS resolvers, IP addresses, SSID.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
from pathlib import Path

import psutil

from beacon.collectors.lan import LANCollector
from beacon.collectors.wifi import _AIRPORT_PATH
from beacon.models.envelope import Event, Metric, Severity
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class ChangeDetector(BaseSampler):
    name = "change"
    tier = 0
    default_interval = 10

    def __init__(self) -> None:
        self._previous: dict[str, str | None] = {
            "default_route": None,
            "dns_servers": None,
            "primary_ip": None,
            "ssid": None,
        }
        self._events: list[Event] = []

    async def sample(self) -> list[Metric]:
        """Detect changes and return metrics + side-effect events."""
        self._events.clear()
        now = self._now()

        current = await asyncio.to_thread(self._snapshot)

        changes: dict[str, str] = {}
        for key, new_val in current.items():
            old_val = self._previous[key]
            if old_val is not None and new_val != old_val:
                changes[key] = f"{old_val} -> {new_val}"
                self._events.append(
                    Event(
                        event_type=f"{key}_changed",
                        severity=Severity.WARNING,
                        message=f"{key} changed: {old_val} -> {new_val}",
                        tags={"detector": "change"},
                        timestamp=now,
                    )
                )

        self._previous.update(current)

        if changes:
            return [
                Metric(
                    measurement="t_change_event",
                    fields={"changes_detected": len(changes)},
                    tags={"changes": ",".join(changes.keys())},
                    timestamp=now,
                )
            ]
        return []

    def pop_events(self) -> list[Event]:
        """Retrieve and clear accumulated change events."""
        events = list(self._events)
        self._events.clear()
        return events

    def _snapshot(self) -> dict[str, str | None]:
        """Capture current system state (runs in thread)."""
        return {
            "default_route": self._get_default_route(),
            "dns_servers": self._get_dns_servers(),
            "primary_ip": self._get_primary_ip(),
            "ssid": self._get_ssid(),
        }

    def _get_default_route(self) -> str | None:
        """Reuses LANCollector._get_default_interface logic."""
        return LANCollector._get_default_interface()

    def _get_dns_servers(self) -> str | None:
        """Parse /etc/resolv.conf for nameservers."""
        try:
            resolv = Path("/etc/resolv.conf").read_text()
            servers = re.findall(r"^nameserver\s+(\S+)", resolv, re.MULTILINE)
            return ",".join(sorted(servers)) if servers else None
        except OSError:
            return None

    def _get_primary_ip(self) -> str | None:
        """Get IPv4 address of the primary interface."""
        default_iface = self._get_default_route()
        if not default_iface:
            return None

        addrs = psutil.net_if_addrs()
        for addr in addrs.get(default_iface, []):
            if addr.family.name == "AF_INET":
                return addr.address
        return None

    def _get_ssid(self) -> str | None:
        """Get current SSID (macOS only for now).

        Uses airport -I for fast detection (< 1s), falling back to
        system_profiler SPAirPortDataType if airport is unavailable.
        """
        system = platform.system()
        if system != "Darwin":
            return None

        import subprocess

        # 1. Try airport -I first (fast, typically < 1s)
        try:
            result = subprocess.run(
                [_AIRPORT_PATH, "-I"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    m = re.match(r"\s+SSID:\s+(.+)", line)
                    if m:
                        return m.group(1).strip()
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass

        # 2. Fallback: system_profiler SPAirPortDataType (slower, ~10s)
        try:
            result = subprocess.run(
                ["system_profiler", "SPAirPortDataType"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return None
            # Find SSID in "Current Network Information:" block
            in_current = False
            for line in result.stdout.splitlines():
                if "Current Network Information:" in line:
                    in_current = True
                    continue
                if in_current:
                    m = re.match(r"^\s{14}(\S.*):$", line)
                    if m and ":" not in m.group(1).rstrip(":"):
                        return m.group(1)
                    if "Other Local Wi-Fi Networks:" in line:
                        break
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

        return None

