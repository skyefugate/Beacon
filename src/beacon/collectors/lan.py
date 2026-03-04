"""LAN collector — network interface statistics via psutil.

Tags each interface with a role for noise reduction:
  primary     — carries the default route
  physical    — named like en*/eth*/wlan* with traffic
  vpn_tunnel  — utun* with assigned addresses
  virtual     — bridge*, awdl*, llw*, anpi*, ap*, gif*, stf*
  inactive    — no traffic and no addresses
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from uuid import UUID

import psutil

from beacon.collectors.base import BaseCollector
from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity

logger = logging.getLogger(__name__)

# Prefixes that indicate virtual/system interfaces (not user-facing)
_VIRTUAL_PREFIXES = ("bridge", "awdl", "llw", "anpi", "ap", "gif", "stf", "XHC")


class LANCollector(BaseCollector):
    name = "lan"
    version = "0.2.0"

    def collect(self, run_id: UUID) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []
        now = self._now()

        # Determine the default route interface
        default_iface = self._get_default_interface()
        if default_iface:
            notes.append(f"Default route interface: {default_iface}")

        # Gather address info for role classification
        addrs = psutil.net_if_addrs()
        ifaces_with_ipv4: set[str] = set()
        for iface, addr_list in addrs.items():
            for addr in addr_list:
                if addr.family.name == "AF_INET":
                    ifaces_with_ipv4.add(iface)

        # Interface counters
        counters = psutil.net_io_counters(pernic=True)
        for iface, stats in counters.items():
            if iface == "lo" or iface.startswith("lo"):
                continue

            role = self._classify_interface(
                iface, default_iface, ifaces_with_ipv4,
                has_traffic=(stats.bytes_sent + stats.bytes_recv) > 0,
            )

            metrics.append(Metric(
                measurement="lan_interface",
                fields={
                    "bytes_sent": stats.bytes_sent,
                    "bytes_recv": stats.bytes_recv,
                    "packets_sent": stats.packets_sent,
                    "packets_recv": stats.packets_recv,
                    "errin": stats.errin,
                    "errout": stats.errout,
                    "dropin": stats.dropin,
                    "dropout": stats.dropout,
                },
                tags={"interface": iface, "role": role},
                timestamp=now,
            ))

            # Only flag errors/drops on non-virtual interfaces
            if role not in ("virtual", "inactive"):
                total_errors = stats.errin + stats.errout
                total_drops = stats.dropin + stats.dropout
                if total_errors > 0:
                    events.append(Event(
                        event_type="interface_errors",
                        severity=Severity.WARNING,
                        message=f"Interface {iface} ({role}) has {total_errors} errors",
                        tags={"interface": iface, "role": role},
                        timestamp=now,
                    ))
                if total_drops > 100:
                    events.append(Event(
                        event_type="interface_drops",
                        severity=Severity.INFO,
                        message=f"Interface {iface} ({role}) has {total_drops} drops",
                        tags={"interface": iface, "role": role},
                        timestamp=now,
                    ))

        # Interface addresses (only for interfaces with IPv4)
        for iface, addr_list in addrs.items():
            if iface == "lo" or iface.startswith("lo"):
                continue
            for addr in addr_list:
                if addr.family.name == "AF_INET":
                    metrics.append(Metric(
                        measurement="lan_address",
                        fields={"address": addr.address},
                        tags={"interface": iface, "family": "ipv4"},
                        timestamp=now,
                    ))

        # Interface status
        if_stats = psutil.net_if_stats()
        for iface, stats in if_stats.items():
            if iface == "lo" or iface.startswith("lo"):
                continue

            role = self._classify_interface(
                iface, default_iface, ifaces_with_ipv4,
                has_traffic=iface in counters and (
                    counters[iface].bytes_sent + counters[iface].bytes_recv
                ) > 0,
            )

            metrics.append(Metric(
                measurement="lan_status",
                fields={
                    "is_up": stats.isup,
                    "speed_mbps": stats.speed,
                    "mtu": stats.mtu,
                },
                tags={"interface": iface, "role": role},
                timestamp=now,
            ))

        return PluginEnvelope(
            plugin_name=self.name,
            plugin_version=self.version,
            run_id=run_id,
            metrics=metrics,
            events=events,
            notes=notes,
            started_at=started_at,
            completed_at=self._now(),
        )

    @staticmethod
    def _classify_interface(
        iface: str,
        default_iface: str | None,
        ifaces_with_ipv4: set[str],
        has_traffic: bool,
    ) -> str:
        """Classify an interface into a role."""
        if iface == default_iface:
            return "primary"

        # Virtual/system interfaces
        if any(iface.startswith(p) for p in _VIRTUAL_PREFIXES):
            return "virtual"

        # VPN tunnels (utun* with addresses or traffic)
        if iface.startswith("utun"):
            if iface in ifaces_with_ipv4 or has_traffic:
                return "vpn_tunnel"
            return "virtual"

        # Physical interfaces with traffic or addresses
        if has_traffic or iface in ifaces_with_ipv4:
            return "physical"

        return "inactive"

    @staticmethod
    def _get_default_interface() -> str | None:
        """Get the interface used for the default route."""
        system = platform.system()
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["route", "-n", "get", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    m = re.match(r"\s*interface:\s*(\S+)", line)
                    if m:
                        return m.group(1)
            elif system == "Linux":
                result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"dev\s+(\S+)", result.stdout)
                if m:
                    return m.group(1)
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        return None
