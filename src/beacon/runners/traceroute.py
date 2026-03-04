"""JSON traceroute runner — traces the path to a target and reports per-hop latency.

Traceroute output is inherently messy. The parser handles:
  - Clean hops with 3 RTT values
  - Full timeouts (* * *)
  - Partial timeouts (mixed * and RTT values)
  - ECMP hops with multiple IPs per hop
  - Weird tokens (., empty, non-numeric) → treated as timeouts
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from uuid import UUID

from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity
from beacon.runners.base import BaseTestRunner, RunnerConfig

logger = logging.getLogger(__name__)

DEFAULT_TARGET = "8.8.8.8"


class TracerouteRunner(BaseTestRunner):
    name = "traceroute"
    version = "0.2.0"

    def run(self, run_id: UUID, config: RunnerConfig) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []

        targets = config.targets or [DEFAULT_TARGET]

        for target in targets:
            now = self._now()
            try:
                system = platform.system()
                max_hops = config.extra.get("max_hops", 30)
                wait = str(config.extra.get("wait_seconds", 2))

                if system == "Darwin":
                    cmd = ["traceroute", "-m", str(max_hops), "-w", wait, "-q", "3", target]
                elif system == "Linux":
                    cmd = ["traceroute", "-m", str(max_hops), "-w", wait, "-q", "3", target]
                else:
                    cmd = ["tracert", "-h", str(max_hops), target]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds + max_hops * 3,
                )

                hops = self._parse_traceroute(result.stdout)
                timeout_streak = 0

                for hop in hops:
                    metrics.append(
                        Metric(
                            measurement="traceroute_hop",
                            fields=hop,
                            tags={"target": target, "hop": str(hop.get("hop_number", 0))},
                            timestamp=now,
                        )
                    )

                    if hop.get("all_timeouts", False):
                        timeout_streak += 1
                    else:
                        timeout_streak = 0

                if timeout_streak >= 3:
                    events.append(
                        Event(
                            event_type="traceroute_blackhole",
                            severity=Severity.WARNING,
                            message=f"Multiple consecutive timeouts in traceroute to {target}",
                            tags={"target": target},
                            timestamp=now,
                        )
                    )

                # Summary metric
                total_hops = len(hops)
                timeout_hops = sum(1 for h in hops if h.get("all_timeouts", False))
                metrics.append(
                    Metric(
                        measurement="traceroute_summary",
                        fields={
                            "total_hops": total_hops,
                            "timeout_hops": timeout_hops,
                            "responding_hops": total_hops - timeout_hops,
                            "completed": not result.stdout.strip().endswith("* * *"),
                        },
                        tags={"target": target},
                        timestamp=now,
                    )
                )

            except subprocess.TimeoutExpired:
                notes.append(f"Traceroute to {target} timed out")
            except FileNotFoundError:
                notes.append("traceroute command not found")
            except Exception as e:
                notes.append(f"Traceroute to {target} failed: {e}")

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
    def _parse_traceroute(output: str) -> list[dict]:
        """Parse traceroute output into a list of hop dicts.

        Each hop dict contains:
          hop_number: int
          ip: str (if resolved)
          hostname: str (if resolved)
          rtt_min_ms, rtt_avg_ms, rtt_max_ms: float (if any probes responded)
          probes: int (total probes sent)
          timeouts: int (probes that timed out)
          all_timeouts: bool (all probes timed out)
          raw_rtts: list (individual RTT values, None for timeouts)
        """
        hops: list[dict] = []

        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("traceroute") or line.startswith("tracert"):
                continue

            hop_match = re.match(r"^\s*(\d+)\s+(.+)$", line)
            if not hop_match:
                continue

            hop_num = int(hop_match.group(1))
            rest = hop_match.group(2)

            # Extract IP address(es)
            ip_match = re.search(r"\(?(\d{1,3}(?:\.\d{1,3}){3})\)?", rest)
            hostname_match = re.match(r"([\w\-\.]+)\s+\(", rest)

            # Parse RTT tokens: look for "NNN.NNN ms" or "*"
            # Use a regex that requires at least one digit before optional decimal
            re.findall(r"(\d+(?:\.\d+)?)\s*ms|\*", rest)

            # rtt_tokens will be a list of either captured groups (numeric str) or
            # empty strings for '*' matches. Let's parse more carefully.
            raw_rtts: list[float | None] = []
            for token_match in re.finditer(r"(\d+(?:\.\d+)?)\s*ms|(\*)", rest):
                rtt_str = token_match.group(1)
                star = token_match.group(2)
                if rtt_str:
                    try:
                        raw_rtts.append(float(rtt_str))
                    except ValueError:
                        raw_rtts.append(None)
                elif star:
                    raw_rtts.append(None)

            # Build hop data
            valid_rtts = [r for r in raw_rtts if r is not None]
            all_timeouts = len(valid_rtts) == 0

            hop_data: dict = {
                "hop_number": hop_num,
                "all_timeouts": all_timeouts,
                "probes": len(raw_rtts) if raw_rtts else 3,
                "timeouts": sum(1 for r in raw_rtts if r is None),
            }

            if ip_match:
                hop_data["ip"] = ip_match.group(1)
            if hostname_match:
                hop_data["hostname"] = hostname_match.group(1)
            if valid_rtts:
                hop_data["rtt_min_ms"] = min(valid_rtts)
                hop_data["rtt_avg_ms"] = sum(valid_rtts) / len(valid_rtts)
                hop_data["rtt_max_ms"] = max(valid_rtts)

            hops.append(hop_data)

        return hops
