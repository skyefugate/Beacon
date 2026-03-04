"""DHCP health telemetry sampler -- lease tracking, renew failures, time-to-IP.

Parses ipconfig getpacket <interface> on macOS to extract DHCP lease
information, tracking lease age, time remaining, and validity.

On Linux, parses lease files from common DHCP client paths (dhcpcd, NetworkManager).
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import subprocess
import time
from pathlib import Path

import psutil

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)

# Linux DHCP lease file locations (checked in order)
_LINUX_LEASE_PATHS = [
    "/var/lib/dhcpcd",
    "/var/lib/dhcp",
    "/run/NetworkManager/dhcp",
    "/var/lib/NetworkManager",
]


class DhcpSampler(BaseSampler):
    """Collects DHCP lease health metrics: age, time remaining, and validity."""

    name = "dhcp"
    tier = 0
    default_interval = 60

    async def sample(self) -> list[Metric]:
        now = self._now()
        system = platform.system()

        try:
            if system == "Darwin":
                fields = await asyncio.to_thread(self._collect_macos)
            elif system == "Linux":
                fields = await asyncio.to_thread(self._collect_linux)
            else:
                logger.debug("DHCP sampler: unsupported platform %s", system)
                return []
        except Exception as e:
            logger.debug("DHCP sample failed: %s", e)
            return []

        if not fields:
            return []

        return [Metric(measurement="t_dhcp_health", fields=fields, timestamp=now)]

    # ------------------------------------------------------------------
    # macOS collection
    # ------------------------------------------------------------------

    def _collect_macos(self) -> dict:
        """Collect DHCP lease info on macOS via ipconfig getpacket."""
        iface = self._detect_primary_interface()
        if not iface:
            logger.debug("DHCP sampler: no primary interface found")
            return {}

        try:
            result = subprocess.run(
                ["ipconfig", "getpacket", iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
            logger.debug("ipconfig getpacket failed: %s", e)
            return {}

        if result.returncode != 0 or not result.stdout.strip():
            logger.debug("DHCP sampler: no DHCP lease on interface %s", iface)
            return self._no_lease_fields()

        return self._parse_ipconfig_output(result.stdout)

    @staticmethod
    def _parse_ipconfig_output(output: str) -> dict:
        r"""Parse ipconfig getpacket output into lease fields.

        Example output::

            op = BOOTREPLY
            yiaddr = 192.168.1.50
            lease_time = 0x15180  (86400)
            renewal_time = 0xa8c0  (43200)
            router = 192.168.1.1
            domain_name_server = 8.8.8.8, 8.8.4.4
        """
        fields: dict = {}

        # Extract lease_time (seconds) -- may appear as hex+decimal pair or plain decimal
        m = re.search(r"lease_time\s*=\s*(?:0x[0-9a-fA-F]+)?\s*\((\d+)\)", output)
        if not m:
            m = re.search(r"lease_time\s*=\s*(\d+)", output)
        if m:
            fields["lease_time_seconds"] = int(m.group(1))

        # Extract assigned IP address
        m = re.search(r"yiaddr\s*=\s*([\d.]+)", output)
        if m:
            fields["ip_address"] = m.group(1)

        # Extract router/gateway
        m = re.search(r"router\s*=\s*([\d.]+)", output)
        if m:
            fields["router"] = m.group(1)

        # Extract DNS servers
        m = re.search(r"domain_name_server\s*=\s*([^\n]+)", output)
        if m:
            dns_raw = m.group(1).strip().strip("{}")
            servers = [s.strip() for s in dns_raw.split(",") if s.strip()]
            if servers:
                fields["dns_servers"] = ",".join(servers)

        if not fields.get("lease_time_seconds") or not fields.get("ip_address"):
            return {"has_valid_lease": 0}

        lease_time = fields["lease_time_seconds"]

        # Estimate lease age from renewal_time (typically 50% of lease_time at acquisition).
        # renewal_time decrements as the lease ages; age ~ lease_time - renewal_time.
        renewal_m = re.search(r"renewal_time\s*=\s*(?:0x[0-9a-fA-F]+)?\s*\((\d+)\)", output)
        if not renewal_m:
            renewal_m = re.search(r"renewal_time\s*=\s*(\d+)", output)

        if renewal_m:
            renewal_time = int(renewal_m.group(1))
            lease_age = max(0, lease_time - renewal_time)
            lease_remaining = max(0, renewal_time)
        else:
            lease_age = 0
            lease_remaining = lease_time

        lease_remaining_pct = round((lease_remaining / lease_time) * 100, 1) if lease_time > 0 else 0.0

        fields["lease_age_seconds"] = lease_age
        fields["lease_remaining_pct"] = lease_remaining_pct
        fields["has_valid_lease"] = 1
        fields["lease_expiry_approaching"] = 1 if lease_remaining_pct < 10.0 else 0

        return fields

    # ------------------------------------------------------------------
    # Linux collection
    # ------------------------------------------------------------------

    def _collect_linux(self) -> dict:
        """Collect DHCP lease info on Linux by parsing lease files."""
        iface = self._detect_primary_interface()
        if not iface:
            return {}

        for base in _LINUX_LEASE_PATHS:
            base_path = Path(base)
            if not base_path.exists():
                continue
            for candidate in base_path.rglob(f"*{iface}*"):
                if candidate.is_file():
                    try:
                        return self._parse_linux_lease_file(candidate.read_text())
                    except OSError:
                        continue

        logger.debug("DHCP sampler: no lease file found for interface %s", iface)
        return self._no_lease_fields()

    @staticmethod
    def _parse_linux_lease_file(content: str) -> dict:
        """Parse a dhcpcd/ISC DHCP lease file into lease fields."""
        fields: dict = {}

        # ISC dhclient format
        lease_time_m = re.search(r"default-lease-time\s+(\d+)", content)
        if lease_time_m:
            fields["lease_time_seconds"] = int(lease_time_m.group(1))

        ip_m = re.search(r"fixed-address\s+([\d.]+)", content)
        if ip_m:
            fields["ip_address"] = ip_m.group(1)

        router_m = re.search(r"option routers\s+([\d.]+)", content)
        if router_m:
            fields["router"] = router_m.group(1)

        dns_m = re.search(r"option domain-name-servers\s+([^\n;]+)", content)
        if dns_m:
            servers = [s.strip() for s in dns_m.group(1).split(",") if s.strip()]
            if servers:
                fields["dns_servers"] = ",".join(servers)

        # dhcpcd simple format
        if not fields.get("lease_time_seconds"):
            lt_m = re.search(r"lease_time=(\d+)", content)
            if lt_m:
                fields["lease_time_seconds"] = int(lt_m.group(1))

        if not fields.get("ip_address"):
            ip_m2 = re.search(r"ip_address=([\d.]+)", content)
            if ip_m2:
                fields["ip_address"] = ip_m2.group(1)

        acquired_m = re.search(r"acquired=(\d+)", content)
        if acquired_m:
            acquired_ts = int(acquired_m.group(1))
            lease_age = max(0, int(time.time()) - acquired_ts)
            lease_time = fields.get("lease_time_seconds", 0)
            if lease_time > 0:
                lease_remaining = max(0, lease_time - lease_age)
                lease_remaining_pct = round((lease_remaining / lease_time) * 100, 1)
                fields["lease_age_seconds"] = lease_age
                fields["lease_remaining_pct"] = lease_remaining_pct
                fields["has_valid_lease"] = 1
                fields["lease_expiry_approaching"] = 1 if lease_remaining_pct < 10.0 else 0
                return fields

        if fields.get("lease_time_seconds") and fields.get("ip_address"):
            fields.setdefault("lease_age_seconds", 0)
            fields.setdefault("lease_remaining_pct", 100.0)
            fields["has_valid_lease"] = 1
            fields["lease_expiry_approaching"] = 0
            return fields

        return {"has_valid_lease": 0}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_primary_interface() -> str | None:
        """Detect the primary network interface (the one with a default route)."""
        system = platform.system()
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["route", "-n", "get", "default"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                m = re.search(r"interface:\s*(\S+)", result.stdout)
                if m:
                    return m.group(1)
            elif system == "Linux":
                result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                m = re.search(r"dev\s+(\S+)", result.stdout)
                if m:
                    return m.group(1)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass

        # Fallback: first non-loopback interface with an IPv4 address
        addrs = psutil.net_if_addrs()
        for name, addr_list in addrs.items():
            if name == "lo" or name.startswith("lo"):
                continue
            for addr in addr_list:
                if addr.family.name == "AF_INET" and not addr.address.startswith("127."):
                    return name
        return None

    @staticmethod
    def _no_lease_fields() -> dict:
        """Return fields indicating no valid DHCP lease is present."""
        return {
            "has_valid_lease": 0,
            "lease_time_seconds": 0,
            "lease_age_seconds": 0,
            "lease_remaining_pct": 0.0,
            "lease_expiry_approaching": 0,
        }
