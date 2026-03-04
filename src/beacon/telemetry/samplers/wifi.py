"""Wi-Fi telemetry sampler — reuses WiFiCollector parsers for continuous monitoring."""

from __future__ import annotations

import asyncio
import logging
import platform

from beacon.collectors.wifi import WiFiCollector, _AIRPORT_PATH
from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class WiFiSampler(BaseSampler):
    name = "wifi"
    tier = 0
    default_interval = 10

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
            logger.debug("Wi-Fi sample failed: %s", e)
            return []

        if not fields:
            return []

        # Compute SNR
        rssi = fields.get("rssi_dbm")
        noise = fields.get("noise_dbm")
        if isinstance(rssi, (int, float)) and isinstance(noise, (int, float)):
            fields["snr_db"] = rssi - noise

        return [Metric(measurement="t_wifi_link", fields=fields, timestamp=now)]

    async def _sample_macos(self) -> dict:
        """Try macOS Wi-Fi tools in priority order (async subprocess)."""
        # 1. airport
        try:
            proc = await asyncio.create_subprocess_exec(
                _AIRPORT_PATH, "-I",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                fields = WiFiCollector._parse_airport(stdout.decode())
                if fields:
                    return fields
        except (FileNotFoundError, OSError, asyncio.TimeoutError):
            pass

        # 2. system_profiler (unprivileged fallback)
        try:
            proc = await asyncio.create_subprocess_exec(
                "system_profiler", "SPAirPortDataType",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                fields, _ = WiFiCollector._parse_system_profiler(stdout.decode())
                if fields:
                    return fields
        except (FileNotFoundError, OSError, asyncio.TimeoutError):
            pass

        return {}

    async def _sample_linux(self) -> dict:
        """Sample Wi-Fi on Linux via iw."""
        try:
            # Find wireless interfaces
            proc = await asyncio.create_subprocess_exec(
                "iw", "dev",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                return {}

            import re
            interfaces = re.findall(r"Interface\s+(\S+)", stdout.decode())
            if not interfaces:
                return {}

            # Get link info for first interface
            proc = await asyncio.create_subprocess_exec(
                "iw", interfaces[0], "link",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            output = stdout.decode()
            if "Not connected" in output:
                return {}

            fields: dict = {}
            for line in output.splitlines():
                line = line.strip()
                if "signal:" in line:
                    m = re.search(r"signal:\s*(-?\d+)", line)
                    if m:
                        fields["rssi_dbm"] = int(m.group(1))
                elif "tx bitrate:" in line:
                    m = re.search(r"tx bitrate:\s*([\d.]+)", line)
                    if m:
                        fields["tx_rate_mbps"] = float(m.group(1))
                elif "SSID:" in line:
                    fields["ssid"] = line.split("SSID:")[1].strip()

            return fields
        except (FileNotFoundError, OSError, asyncio.TimeoutError):
            return {}
