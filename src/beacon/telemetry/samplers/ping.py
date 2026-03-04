"""Ping telemetry sampler — gateway + internet RTT via async subprocess."""

from __future__ import annotations

import asyncio
import logging
import platform

from beacon.models.envelope import Metric
from beacon.runners.ping import PingRunner
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class PingSampler(BaseSampler):
    name = "ping"
    tier = 0
    default_interval = 10

    def __init__(
        self,
        targets: list[str] | None = None,
        ping_gateway: bool = True,
        count: int = 3,
    ) -> None:
        self._targets = targets or ["8.8.8.8"]
        self._ping_gateway = ping_gateway
        self._count = count
        self._gateway: str | None = None

    async def sample(self) -> list[Metric]:
        now = self._now()
        metrics: list[Metric] = []

        # Discover gateway if needed
        if self._ping_gateway and self._gateway is None:
            self._gateway = await self._detect_gateway()

        targets = list(self._targets)
        if self._ping_gateway and self._gateway and self._gateway not in targets:
            targets.insert(0, self._gateway)

        for target in targets:
            fields = await self._ping_target(target)
            if fields:
                measurement = "t_gateway_rtt" if target == self._gateway else "t_internet_rtt"
                metrics.append(
                    Metric(
                        measurement=measurement,
                        fields=fields,
                        tags={"target": target},
                        timestamp=now,
                    )
                )

        return metrics

    async def _ping_target(self, target: str) -> dict:
        """Ping a single target and parse the output."""
        system = platform.system()
        count_flag = "-c" if system != "Windows" else "-n"

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping",
                count_flag,
                str(self._count),
                "-W",
                "2",
                target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            output = stdout.decode()
            fields = PingRunner._parse_ping_output(output, target)
            fields["reachable"] = proc.returncode == 0
            return fields
        except (asyncio.TimeoutError, OSError) as e:
            logger.debug("Ping to %s failed: %s", target, e)
            return {"reachable": False, "target": target}

    async def _detect_gateway(self) -> str | None:
        """Detect the default gateway address."""
        system = platform.system()
        try:
            if system == "Darwin":
                proc = await asyncio.create_subprocess_exec(
                    "route",
                    "-n",
                    "get",
                    "default",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                import re

                m = re.search(r"gateway:\s*(\S+)", stdout.decode())
                if m:
                    return m.group(1)
            elif system == "Linux":
                proc = await asyncio.create_subprocess_exec(
                    "ip",
                    "route",
                    "show",
                    "default",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                import re

                m = re.search(r"via\s+(\S+)", stdout.decode())
                if m:
                    return m.group(1)
        except (FileNotFoundError, OSError, asyncio.TimeoutError):
            pass
        return None
