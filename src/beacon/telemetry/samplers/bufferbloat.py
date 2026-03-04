"""Tier 2 bufferbloat sampler — networkQuality (macOS) or iperf3 (Linux).

This is a one-shot, expensive test activated only during ACTIVE escalation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import re

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class BufferbloatSampler(BaseSampler):
    name = "bufferbloat"
    tier = 2
    default_interval = 60

    def __init__(self, iperf3_server: str | None = None) -> None:
        self._iperf3_server = iperf3_server

    async def sample(self) -> list[Metric]:
        now = self._now()
        system = platform.system()

        try:
            if system == "Darwin":
                fields = await self._run_network_quality()
            elif system == "Linux" and self._iperf3_server:
                fields = await self._run_iperf3()
            else:
                return []
        except Exception as e:
            logger.debug("Bufferbloat sample failed: %s", e)
            return []

        if not fields:
            return []

        return [Metric(
            measurement="t_bufferbloat",
            fields=fields,
            timestamp=now,
        )]

    async def _run_network_quality(self) -> dict:
        """Run macOS networkQuality in sequential mode with JSON output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "networkQuality", "-s", "-c",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return {}

            return self._parse_network_quality(stdout.decode())
        except (FileNotFoundError, asyncio.TimeoutError):
            return {}

    async def _run_iperf3(self) -> dict:
        """Run iperf3 against a server for bufferbloat measurement."""
        if not self._iperf3_server:
            return {}
        try:
            proc = await asyncio.create_subprocess_exec(
                "iperf3", "-c", self._iperf3_server, "-t", "5", "-J",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return {}

            return self._parse_iperf3(stdout.decode())
        except (FileNotFoundError, asyncio.TimeoutError):
            return {}

    @staticmethod
    def _parse_network_quality(output: str) -> dict:
        """Parse networkQuality -s -c JSON output."""
        try:
            data = json.loads(output)
            fields: dict = {}

            # Download
            dl = data.get("dl_throughput", 0)
            if dl:
                fields["dl_throughput_mbps"] = round(dl / 1_000_000, 2)

            # Upload
            ul = data.get("ul_throughput", 0)
            if ul:
                fields["ul_throughput_mbps"] = round(ul / 1_000_000, 2)

            # Responsiveness (RPM)
            rpm = data.get("dl_responsiveness", 0) or data.get("responsiveness", 0)
            if rpm:
                fields["responsiveness_rpm"] = rpm

            # Interface
            iface = data.get("interface_name", "")
            if iface:
                fields["interface"] = iface

            return fields
        except (json.JSONDecodeError, KeyError):
            return {}

    @staticmethod
    def _parse_iperf3(output: str) -> dict:
        """Parse iperf3 -J JSON output for basic throughput."""
        try:
            data = json.loads(output)
            end = data.get("end", {})
            sum_sent = end.get("sum_sent", {})
            sum_recv = end.get("sum_received", {})

            fields: dict = {}
            if sum_sent.get("bits_per_second"):
                fields["ul_throughput_mbps"] = round(
                    sum_sent["bits_per_second"] / 1_000_000, 2
                )
            if sum_recv.get("bits_per_second"):
                fields["dl_throughput_mbps"] = round(
                    sum_recv["bits_per_second"] / 1_000_000, 2
                )

            # Jitter if available
            if "jitter_ms" in sum_sent:
                fields["jitter_ms"] = sum_sent["jitter_ms"]

            return fields
        except (json.JSONDecodeError, KeyError):
            return {}
