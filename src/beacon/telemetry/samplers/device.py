"""Device health telemetry sampler — CPU, memory, load via psutil in thread executor."""

from __future__ import annotations

import asyncio
import logging

import psutil

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class DeviceSampler(BaseSampler):
    name = "device"
    tier = 0
    default_interval = 15

    async def sample(self) -> list[Metric]:
        now = self._now()
        fields = await asyncio.to_thread(self._collect)
        return [Metric(measurement="t_device_health", fields=fields, timestamp=now)]

    @staticmethod
    def _collect() -> dict:
        """Synchronous psutil calls (runs in thread executor)."""
        cpu_pct = psutil.cpu_percent(interval=0)  # non-blocking snapshot
        load_1, load_5, load_15 = psutil.getloadavg()
        mem = psutil.virtual_memory()

        return {
            "cpu_percent": cpu_pct,
            "load_avg_1m": load_1,
            "load_avg_5m": load_5,
            "load_avg_15m": load_15,
            "memory_percent": mem.percent,
            "memory_available_mb": round(mem.available / (1024 * 1024), 1),
        }
