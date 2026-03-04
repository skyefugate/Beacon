"""TCP telemetry sampler --- retransmit and socket error counters.

Detects degraded TCP performance (high retransmit rates, connection failures,
resets) even when ping looks fine --- the ping-is-fine-but-it-sucks detector.

Platform support:
  - macOS: netstat -s -p tcp
  - Linux: /proc/net/snmp

Tracks deltas between samples so fields represent rates per interval.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import subprocess
from pathlib import Path

from beacon.models.envelope import Metric
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class TcpSampler(BaseSampler):
    name = "tcp"
    tier = 0
    default_interval = 30

    def __init__(self) -> None:
        super().__init__()
        self._prev: dict[str, int] | None = None

    async def sample(self) -> list[Metric]:
        now = self._now()
        system = platform.system()

        try:
            if system == "Darwin":
                raw = await asyncio.to_thread(self._collect_macos)
            elif system == "Linux":
                raw = await asyncio.to_thread(self._collect_linux)
            else:
                logger.debug("TcpSampler: unsupported platform %s", system)
                return []
        except Exception as exc:
            logger.debug("TCP sample failed: %s", exc)
            return []

        if raw is None:
            return []

        fields = self._compute_deltas(raw)
        self._prev = raw

        if fields is None:
            return []

        return [Metric(measurement="t_tcp_stats", fields=fields, timestamp=now)]

    def _compute_deltas(
        self, current: dict[str, int]
    ) -> dict[str, float | int | str | bool] | None:
        if self._prev is None:
            return None

        prev = self._prev

        def _delta(key: str) -> int:
            diff = current.get(key, 0) - prev.get(key, 0)
            return max(0, diff)

        return {
            "retransmits_per_sec": _delta("retransmits") / self.default_interval,
            "connection_failures": float(_delta("connection_failures")),
            "resets_per_sec": _delta("resets") / self.default_interval,
            "active_opens": float(_delta("active_opens")),
            "passive_opens": float(_delta("passive_opens")),
        }

    def _collect_macos(self) -> dict[str, int] | None:
        try:
            result = subprocess.run(
                ["netstat", "-s", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.debug("netstat failed: %s", exc)
            return None

        if result.returncode != 0:
            logger.debug("netstat exited %d: %s", result.returncode, result.stderr)
            return None

        return self._parse_netstat_macos(result.stdout)

    @staticmethod
    def _parse_netstat_macos(output: str) -> dict[str, int]:
        counters: dict[str, int] = {
            "retransmits": 0,
            "connection_failures": 0,
            "resets": 0,
            "active_opens": 0,
            "passive_opens": 0,
        }

        patterns = [
            ("retransmits", re.compile(r"(\d+)\s+data packets?.*retransmitted", re.I)),
            ("connection_failures", re.compile(r"(\d+)\s+bad connection attempts?", re.I)),
            ("resets", re.compile(r"(\d+)\s+connections? reset", re.I)),
            ("active_opens", re.compile(r"(\d+)\s+connection requests?", re.I)),
            ("passive_opens", re.compile(r"(\d+)\s+connection accepts?", re.I)),
        ]

        for line in output.splitlines():
            line = line.strip()
            for key, pat in patterns:
                m = pat.search(line)
                if m:
                    counters[key] = int(m.group(1))
                    break

        return counters

    def _collect_linux(self, snmp_path: str = "/proc/net/snmp") -> dict[str, int] | None:
        path = Path(snmp_path)
        if not path.exists():
            logger.debug("TcpSampler: %s not found", snmp_path)
            return None

        try:
            content = path.read_text()
        except OSError as exc:
            logger.debug("TcpSampler: failed to read %s: %s", snmp_path, exc)
            return None

        return self._parse_proc_net_snmp(content)

    @staticmethod
    def _parse_proc_net_snmp(content: str) -> dict[str, int] | None:
        lines = content.splitlines()
        header: list[str] | None = None
        values: list[str] | None = None

        for line in lines:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "Tcp:" and header is None:
                header = parts[1:]
            elif parts[0] == "Tcp:" and header is not None:
                values = parts[1:]
                break

        if header is None or values is None:
            logger.debug("TcpSampler: could not find Tcp: rows in /proc/net/snmp")
            return None

        tcp: dict[str, int] = {}
        for name, val in zip(header, values):
            try:
                tcp[name] = int(val)
            except ValueError:
                tcp[name] = 0

        return {
            "retransmits": tcp.get("RetransSegs", 0),
            "connection_failures": tcp.get("AttemptFails", 0),
            "resets": tcp.get("EstabResets", 0),
            "active_opens": tcp.get("ActiveOpens", 0),
            "passive_opens": tcp.get("PassiveOpens", 0),
        }
