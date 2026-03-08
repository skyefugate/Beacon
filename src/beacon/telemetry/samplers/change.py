"""Change detector -- polls system state and emits Events on changes.

Detects changes in: default route, DNS resolvers, IP addresses, SSID,
BSSID (access-point MAC), and Wi-Fi channel.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
from pathlib import Path

import psutil

from beacon.collectors.lan import LANCollector
from beacon.collectors.wifi import WiFiCollector, _AIRPORT_PATH
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
            "bssid": None,
            "channel": None,
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
                event_type_map = {
                    "bssid": "bssid_change",
                    "channel": "channel_change",
                }
                event_type = event_type_map.get(key, f"{key}_changed")
                self._events.append(
                    Event(
                        event_type=event_type,
                        severity=Severity.WARNING,
                        message=f"{key} changed: {old_val} -> {new_val}",
                        tags={
                            "detector": "change",
                            "old": old_val,
                            "new": new_val if new_val is not None else "",
                        },
                        timestamp=now,
                    )
                )

        self._previous.update(current)

        if changes:
            metrics: list[Metric] = []
            for key, change_str in changes.items():
                old_val, _, new_val = change_str.partition(" -> ")
                event_type_map = {
                    "bssid": "bssid_change",
                    "channel": "channel_change",
                }
                event_type = event_type_map.get(key, f"{key}_changed")
                metrics.append(
                    Metric(
                        measurement="t_change_event",
                        fields={
                            "changes_detected": len(changes),
                            "old_value": old_val,
                            "new_value": new_val,
                        },
                        tags={
                            "event_type": event_type,
                            "changes": ",".join(changes.keys()),
                        },
                        timestamp=now,
                    )
                )
            return metrics
        return []

    def pop_events(self) -> list[Event]:
        """Retrieve and clear accumulated change events."""
        events = list(self._events)
        self._events.clear()
        return events

    def _snapshot(self) -> dict[str, str | None]:
        """Capture current system state (runs in thread)."""
        bssid, channel = self._get_bssid_and_channel()
        return {
            "default_route": self._get_default_route(),
            "dns_servers": self._get_dns_servers(),
            "primary_ip": self._get_primary_ip(),
            "ssid": self._get_ssid(),
            "bssid": bssid,
            "channel": channel,
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
        """Get current SSID (macOS only for now)."""
        system = platform.system()
        if system != "Darwin":
            return None

        import subprocess

        # Use fast airport -I command instead of slow system_profiler
        try:
            result = subprocess.run(
                [_AIRPORT_PATH, "-I"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                fields = WiFiCollector._parse_airport(result.stdout)
                ssid = fields.get("ssid")
                return str(ssid) if ssid is not None else None
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass

        return None

    def _get_bssid_and_channel(self) -> tuple[str | None, str | None]:
        """Return (bssid, channel) for the current Wi-Fi connection.

        Uses the same airport / system_profiler fallback stack as WiFiCollector
        so the values are consistent with the t_wifi_link metrics.  Only macOS
        is supported for now; other platforms return (None, None).
        """
        system = platform.system()
        if system != "Darwin":
            return None, None

        import subprocess

        # 1. airport -I (fast, detailed)
        try:
            result = subprocess.run(
                [_AIRPORT_PATH, "-I"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                fields = WiFiCollector._parse_airport(result.stdout)
                bssid = fields.get("bssid")
                channel = fields.get("channel")
                if bssid or channel:
                    return (
                        str(bssid) if bssid is not None else None,
                        str(channel) if channel is not None else None,
                    )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass

        # 2. system_profiler fallback (no BSSID, but channel is available)
        try:
            result = subprocess.run(
                ["system_profiler", "SPAirPortDataType"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                fields, _ = WiFiCollector._parse_system_profiler(result.stdout)
                bssid = fields.get("bssid")
                channel = fields.get("channel")
                return (
                    str(bssid) if bssid is not None else None,
                    str(channel) if channel is not None else None,
                )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass

        return None, None
