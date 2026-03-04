"""ICMP ping runner — multi-target latency and packet loss measurement."""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from uuid import UUID

from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity
from beacon.runners.base import BaseTestRunner, RunnerConfig

logger = logging.getLogger(__name__)

DEFAULT_TARGETS = ["8.8.8.8", "1.1.1.1"]


class PingRunner(BaseTestRunner):
    name = "ping"
    version = "0.1.0"

    def run(self, run_id: UUID, config: RunnerConfig) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []

        targets = config.targets or DEFAULT_TARGETS

        for target in targets:
            now = self._now()
            try:
                system = platform.system()
                count_flag = "-c" if system != "Windows" else "-n"
                interval_flag = ["-i", str(config.interval)] if system != "Windows" else []

                result = subprocess.run(
                    ["ping", count_flag, str(config.count), *interval_flag, "-W", "2", target],
                    capture_output=True, text=True,
                    timeout=config.timeout_seconds + config.count * config.interval + 5,
                )

                fields = self._parse_ping_output(result.stdout, target)
                fields["reachable"] = result.returncode == 0

                metrics.append(Metric(
                    measurement="ping",
                    fields=fields,
                    tags={"target": target},
                    timestamp=now,
                ))

                loss = fields.get("loss_pct", 0.0)
                if isinstance(loss, (int, float)) and loss > 0:
                    sev = Severity.CRITICAL if loss >= 50.0 else Severity.WARNING
                    events.append(Event(
                        event_type="packet_loss",
                        severity=sev,
                        message=f"Packet loss to {target}: {loss}%",
                        tags={"target": target},
                        timestamp=now,
                    ))

                rtt = fields.get("rtt_avg_ms")
                if isinstance(rtt, (int, float)) and rtt > 100.0:
                    events.append(Event(
                        event_type="high_latency",
                        severity=Severity.WARNING,
                        message=f"High latency to {target}: {rtt:.1f}ms",
                        tags={"target": target},
                        timestamp=now,
                    ))

            except subprocess.TimeoutExpired:
                notes.append(f"Ping to {target} timed out")
                metrics.append(Metric(
                    measurement="ping",
                    fields={"reachable": False, "target": target},
                    tags={"target": target},
                    timestamp=now,
                ))
            except Exception as e:
                notes.append(f"Ping to {target} failed: {e}")

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
    def _parse_ping_output(output: str, target: str) -> dict[str, float | int | str | bool]:
        fields: dict[str, float | int | str | bool] = {"target": target}

        loss_match = re.search(r"(\d+(?:\.\d+)?)% (?:packet )?loss", output)
        if loss_match:
            fields["loss_pct"] = float(loss_match.group(1))

        rtt_match = re.search(
            r"(?:rtt|round-trip)\s+min/avg/max(?:/[a-z]+)?\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)(?:/([\d.]+))?",
            output,
        )
        if rtt_match:
            fields["rtt_min_ms"] = float(rtt_match.group(1))
            fields["rtt_avg_ms"] = float(rtt_match.group(2))
            fields["rtt_max_ms"] = float(rtt_match.group(3))
            if rtt_match.group(4):
                fields["rtt_stddev_ms"] = float(rtt_match.group(4))

        transmitted_match = re.search(r"(\d+) packets? transmitted", output)
        received_match = re.search(r"(\d+) (?:packets? )?received", output)
        if transmitted_match:
            fields["packets_sent"] = int(transmitted_match.group(1))
        if received_match:
            fields["packets_received"] = int(received_match.group(1))

        return fields
