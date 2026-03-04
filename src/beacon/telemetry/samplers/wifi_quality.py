"""Tier 1 Wi-Fi quality sampler — retry rate, TX failures via wdutil/iw station dump.

Activated by escalation engine when Wi-Fi degradation is suspected.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class WiFiQualitySampler(BaseSampler):
    name = "wifi_quality"
    tier = 1
    default_interval = 5

    async def sample(self) -> list[Metric]:
        now = self._now()
        system = platform.system()

        try:
            if system == "Darwin":
                fields = await self._sample_macos()
            elif system == "Linux":
                fields = await self._sample_linux()
            else:
                return []
        except Exception as e:
            logger.debug("Wi-Fi quality sample failed: %s", e)
            return []

        if not fields:
            return []

        return [
            Metric(
                measurement="t_wifi_quality",
                fields=fields,
                timestamp=now,
            )
        ]

    async def _sample_macos(self) -> dict:
        """Parse wdutil info for retry/error counters."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "wdutil",
                "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return {}
            return self._parse_wdutil_quality(stdout.decode())
        except (FileNotFoundError, OSError, asyncio.TimeoutError):
            return {}

    async def _sample_linux(self) -> dict:
        """Parse iw station dump for retry/error stats."""
        try:
            # Find first wireless interface
            proc = await asyncio.create_subprocess_exec(
                "iw",
                "dev",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            interfaces = re.findall(r"Interface\s+(\S+)", stdout.decode())
            if not interfaces:
                return {}

            # Get station dump
            proc = await asyncio.create_subprocess_exec(
                "iw",
                interfaces[0],
                "station",
                "dump",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return self._parse_iw_station(stdout.decode())
        except (FileNotFoundError, OSError, asyncio.TimeoutError):
            return {}

    @staticmethod
    def _parse_wdutil_quality(output: str) -> dict:
        """Extract quality metrics from wdutil info output."""
        fields: dict = {}
        for line in output.splitlines():
            line = line.strip()
            if ": " not in line:
                continue
            key, _, value = line.partition(": ")
            key = key.strip().lower()
            value = value.strip()

            if "tx rate" in key:
                m = re.search(r"([\d.]+)", value)
                if m:
                    fields["tx_rate_mbps"] = float(m.group(1))
            elif "rssi" in key:
                m = re.search(r"(-?\d+)", value)
                if m:
                    fields["rssi_dbm"] = int(m.group(1))

        return fields

    @staticmethod
    def _parse_iw_station(output: str) -> dict:
        """Extract quality metrics from iw station dump."""
        fields: dict = {}
        for line in output.splitlines():
            line = line.strip()
            if "tx retries:" in line:
                m = re.search(r"tx retries:\s*(\d+)", line)
                if m:
                    fields["tx_retries"] = int(m.group(1))
            elif "tx failed:" in line:
                m = re.search(r"tx failed:\s*(\d+)", line)
                if m:
                    fields["tx_failed"] = int(m.group(1))
            elif "tx bitrate:" in line:
                m = re.search(r"tx bitrate:\s*([\d.]+)", line)
                if m:
                    fields["tx_rate_mbps"] = float(m.group(1))
            elif "rx bitrate:" in line:
                m = re.search(r"rx bitrate:\s*([\d.]+)", line)
                if m:
                    fields["rx_rate_mbps"] = float(m.group(1))
            elif "signal:" in line:
                m = re.search(r"signal:\s*(-?\d+)", line)
                if m:
                    fields["rssi_dbm"] = int(m.group(1))

        return fields
