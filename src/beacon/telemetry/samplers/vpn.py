"""Tier 1 VPN tunnel detection — checks route table and utun/tun interfaces."""

from __future__ import annotations

import asyncio
import logging

import psutil

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)

# Interface prefixes that indicate VPN tunnels
_VPN_PREFIXES = ("utun", "tun", "tap", "ppp", "ipsec", "wg")


class VPNSampler(BaseSampler):
    name = "vpn"
    tier = 1
    default_interval = 30

    async def sample(self) -> list[Metric]:
        now = self._now()
        fields = await asyncio.to_thread(self._detect)
        return [Metric(
            measurement="t_vpn_status",
            fields=fields,
            timestamp=now,
        )]

    def _detect(self) -> dict:
        """Detect active VPN tunnels."""
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)

        vpn_interfaces: list[str] = []
        for iface in addrs:
            if any(iface.startswith(p) for p in _VPN_PREFIXES):
                # Check if interface is up and has addresses
                if iface in stats and stats[iface].isup:
                    has_ipv4 = any(
                        a.family.name == "AF_INET" for a in addrs[iface]
                    )
                    has_traffic = (
                        iface in counters
                        and (counters[iface].bytes_sent + counters[iface].bytes_recv) > 0
                    )
                    if has_ipv4 or has_traffic:
                        vpn_interfaces.append(iface)

        return {
            "vpn_active": len(vpn_interfaces) > 0,
            "vpn_count": len(vpn_interfaces),
            "vpn_interfaces": ",".join(vpn_interfaces) if vpn_interfaces else "none",
        }
