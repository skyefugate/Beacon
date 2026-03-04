"""Context sampler — device fingerprint, network topology, and geo enrichment.

Tier 0 sampler that collects "who/where/what" metadata:
- Tier 1: Device fingerprint (hostname, OS, arch, primary interface)
- Tier 2: Network topology (gateway, DNS servers, public IP, VPN)
- Tier 3: Geo enrichment (ASN, ISP, city/region/country via ip-api.com)

Emits two measurements:
- t_agent_context — device + network metadata (every interval)
- t_network_geo — ASN/ISP/location (cached, re-fetched on IP change)
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import socket
import subprocess
import time
from pathlib import Path

import httpx
import psutil

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)

# Interface prefixes that indicate VPN tunnels (shared with VPNSampler)
_VPN_PREFIXES = ("utun", "tun", "tap", "ppp", "ipsec", "wg")


class ContextSampler(BaseSampler):
    """Collects device fingerprint, network topology, and geo enrichment."""

    name = "context"
    tier = 0
    default_interval = 60

    def __init__(
        self,
        public_ip_ttl: int = 300,
        geo_ttl: int = 900,
        geo_enabled: bool = True,
    ) -> None:
        self._public_ip_ttl = public_ip_ttl
        self._geo_ttl = geo_ttl
        self._geo_enabled = geo_enabled

        # TTL caches
        self._cached_public_ip: str | None = None
        self._public_ip_fetched_at: float = 0.0
        self._cached_geo: dict[str, str] | None = None
        self._geo_fetched_at: float = 0.0
        self._geo_for_ip: str | None = None  # IP the geo was fetched for

    async def sample(self) -> list[Metric]:
        now = self._now()
        metrics: list[Metric] = []

        # Tier 1 + 2: device + network (runs in thread for psutil/socket)
        context_fields = await asyncio.to_thread(self._collect_context)

        # Tier 2 continued: public IP (async HTTP)
        public_ip = await self._get_public_ip()
        if public_ip:
            context_fields["public_ip"] = public_ip

        metrics.append(Metric(
            measurement="t_agent_context",
            fields=context_fields,
            timestamp=now,
        ))

        # Tier 3: geo enrichment (async HTTP, heavily cached)
        if self._geo_enabled and public_ip:
            geo_fields = await self._get_geo(public_ip)
            if geo_fields:
                metrics.append(Metric(
                    measurement="t_network_geo",
                    fields=geo_fields,
                    timestamp=now,
                ))

        return metrics

    # --- Tier 1: Device Fingerprint ---

    def _collect_context(self) -> dict[str, str | int | float | bool]:
        """Synchronous collection of device + network metadata (runs in thread)."""
        fields: dict[str, str | int | float | bool] = {}

        # Device fingerprint
        fields["hostname"] = platform.node() or "unknown"
        fields["os"] = platform.system()
        fields["os_version"] = platform.release()
        fields["arch"] = platform.machine()

        # System uptime
        try:
            boot_time = psutil.boot_time()
            uptime_hours = round((time.time() - boot_time) / 3600, 1)
            fields["system_uptime_hours"] = uptime_hours
        except Exception:
            pass

        # Primary interface detection
        iface = self._detect_primary_interface()
        if iface:
            fields["primary_interface"] = iface
            self._collect_interface_details(fields, iface)

        # Network topology
        fields["dns_servers"] = self._get_dns_servers()

        # VPN detection (simplified)
        fields["vpn_active"] = self._detect_vpn()

        # Default gateway
        gateway = self._detect_gateway_sync()
        if gateway:
            fields["default_gateway"] = gateway

        return fields

    def _detect_primary_interface(self) -> str | None:
        """Find the primary network interface (the one with a default route)."""
        system = platform.system()
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["route", "-n", "get", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"interface:\s*(\S+)", result.stdout)
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
        except (FileNotFoundError, OSError):
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

    def _collect_interface_details(
        self, fields: dict[str, str | int | float | bool], iface: str,
    ) -> None:
        """Populate interface-level fields (speed, MTU, MAC, link type)."""
        stats = psutil.net_if_stats()
        if iface in stats:
            iface_stats = stats[iface]
            if iface_stats.speed > 0:
                fields["interface_speed_mbps"] = iface_stats.speed
            fields["interface_mtu"] = iface_stats.mtu

        addrs = psutil.net_if_addrs()
        for addr in addrs.get(iface, []):
            # AF_LINK (macOS) or AF_PACKET (Linux) = MAC address
            if addr.family.name in ("AF_LINK", "AF_PACKET"):
                mac = addr.address
                if mac and mac != "00:00:00:00:00:00":
                    fields["mac_address"] = mac
                break

        fields["link_type"] = self._detect_link_type(iface)

    def _detect_link_type(self, iface: str) -> str:
        """Determine whether an interface is wifi or ethernet."""
        system = platform.system()

        if system == "Darwin":
            try:
                result = subprocess.run(
                    ["networksetup", "-listallhardwareports"],
                    capture_output=True, text=True, timeout=5,
                )
                # Parse blocks like:
                # Hardware Port: Wi-Fi
                # Device: en0
                blocks = result.stdout.split("\n\n")
                for block in blocks:
                    if f"Device: {iface}" in block:
                        if "Wi-Fi" in block:
                            return "wifi"
                        if "Ethernet" in block or "Thunderbolt" in block:
                            return "ethernet"
                        return "other"
            except (FileNotFoundError, OSError):
                pass

        # Linux: check interface name prefixes
        wifi_prefixes = ("wl", "wlan", "ath", "ra")
        eth_prefixes = ("en", "eth", "em", "eno")

        if any(iface.startswith(p) for p in wifi_prefixes):
            return "wifi"
        if any(iface.startswith(p) for p in eth_prefixes):
            return "ethernet"
        return "other"

    # --- Tier 2: Network Topology ---

    def _get_dns_servers(self) -> str:
        """Discover system DNS servers.

        On macOS, uses ``scutil --dns`` which reflects the real resolver
        config (not the Docker-rewritten resolv.conf).  Falls back to
        parsing /etc/resolv.conf on Linux or when scutil is unavailable.
        """
        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["scutil", "--dns"],
                    capture_output=True, text=True, timeout=5,
                )
                servers = sorted(
                    set(re.findall(r"nameserver\[\d+\]\s*:\s*(\S+)", result.stdout))
                )
                if servers:
                    return ",".join(servers)
            except (FileNotFoundError, OSError):
                pass

        try:
            resolv = Path("/etc/resolv.conf").read_text()
            servers = re.findall(r"^nameserver\s+(\S+)", resolv, re.MULTILINE)
            return ",".join(sorted(servers)) if servers else "unknown"
        except OSError:
            return "unknown"

    def _detect_vpn(self) -> bool:
        """Simplified VPN detection via interface name scanning."""
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for iface in addrs:
            if any(iface.startswith(p) for p in _VPN_PREFIXES):
                if iface in stats and stats[iface].isup:
                    return True
        return False

    def _detect_gateway_sync(self) -> str | None:
        """Detect default gateway (sync version for thread executor)."""
        system = platform.system()
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["route", "-n", "get", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"gateway:\s*(\S+)", result.stdout)
                if m:
                    return m.group(1)
            elif system == "Linux":
                result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"via\s+(\S+)", result.stdout)
                if m:
                    return m.group(1)
        except (FileNotFoundError, OSError):
            pass
        return None

    async def _get_public_ip(self) -> str | None:
        """Fetch public IP with TTL caching."""
        now = time.monotonic()
        if (
            self._cached_public_ip
            and (now - self._public_ip_fetched_at) < self._public_ip_ttl
        ):
            return self._cached_public_ip

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("https://api.ipify.org?format=text")
                if resp.status_code == 200:
                    ip = resp.text.strip()
                    self._cached_public_ip = ip
                    self._public_ip_fetched_at = now
                    return ip
        except Exception as e:
            logger.debug("Public IP fetch failed: %s", e)

        # Return stale cache on failure
        return self._cached_public_ip

    # --- Tier 3: Geo Enrichment ---

    async def _get_geo(self, public_ip: str) -> dict[str, str] | None:
        """Fetch geo data with TTL caching, re-fetches on IP change."""
        now = time.monotonic()

        # Return cache if still valid and IP hasn't changed
        if (
            self._cached_geo
            and self._geo_for_ip == public_ip
            and (now - self._geo_fetched_at) < self._geo_ttl
        ):
            return self._cached_geo

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"http://ip-api.com/json/{public_ip}",
                    params={"fields": "as,isp,city,regionName,country"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    geo = {
                        "asn": data.get("as", ""),
                        "isp_name": data.get("isp", ""),
                        "geo_city": data.get("city", ""),
                        "geo_region": data.get("regionName", ""),
                        "geo_country": data.get("country", ""),
                    }
                    self._cached_geo = geo
                    self._geo_fetched_at = now
                    self._geo_for_ip = public_ip
                    return geo
        except Exception as e:
            logger.debug("Geo lookup failed: %s", e)

        # Return stale cache on failure
        return self._cached_geo
