"""iperf3 throughput runner — optional bandwidth test.

Requires an iperf3 server to be available. This runner is optional
and only runs when throughput.enabled=true in the config and a server
address is provided.
"""

from __future__ import annotations

import json
import logging
import subprocess
from uuid import UUID

from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity
from beacon.runners.base import BaseTestRunner, RunnerConfig

logger = logging.getLogger(__name__)


class ThroughputRunner(BaseTestRunner):
    name = "throughput"
    version = "0.1.0"

    def run(self, run_id: UUID, config: RunnerConfig) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []

        server = config.extra.get("server")
        if not server and config.targets:
            server = config.targets[0]
        if not server:
            notes.append("No iperf3 server configured — skipping throughput test")
            return PluginEnvelope(
                plugin_name=self.name,
                plugin_version=self.version,
                run_id=run_id,
                notes=notes,
                started_at=started_at,
                completed_at=self._now(),
            )

        duration = config.extra.get("duration", 10)
        port = config.extra.get("port", 5201)

        for direction in ["download", "upload"]:
            now = self._now()
            try:
                cmd = [
                    "iperf3", "-c", server, "-p", str(port),
                    "-t", str(duration), "-J",
                ]
                if direction == "download":
                    cmd.append("-R")

                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=duration + 15,
                )

                if result.returncode != 0:
                    notes.append(f"iperf3 {direction} failed: {result.stderr}")
                    continue

                data = json.loads(result.stdout)
                end = data.get("end", {})
                summary = end.get("sum_received", end.get("sum_sent", {}))

                bits_per_second = summary.get("bits_per_second", 0)
                mbps = bits_per_second / 1_000_000

                fields: dict[str, float | int | str | bool] = {
                    "mbps": round(mbps, 2),
                    "bytes_transferred": summary.get("bytes", 0),
                    "duration_seconds": summary.get("seconds", duration),
                    "direction": direction,
                }

                # Jitter and loss from UDP mode
                if "jitter_ms" in summary:
                    fields["jitter_ms"] = summary["jitter_ms"]
                if "lost_packets" in summary:
                    fields["lost_packets"] = summary["lost_packets"]

                metrics.append(Metric(
                    measurement="throughput",
                    fields=fields,
                    tags={"server": server, "direction": direction},
                    timestamp=now,
                ))

                if mbps < 10:
                    events.append(Event(
                        event_type="low_throughput",
                        severity=Severity.WARNING,
                        message=f"Low {direction} throughput: {mbps:.1f} Mbps",
                        tags={"server": server, "direction": direction},
                        timestamp=now,
                    ))

            except FileNotFoundError:
                notes.append("iperf3 not installed — skipping throughput test")
                break
            except subprocess.TimeoutExpired:
                notes.append(f"iperf3 {direction} timed out")
            except json.JSONDecodeError:
                notes.append(f"Failed to parse iperf3 {direction} output")
            except Exception as e:
                notes.append(f"Throughput {direction} test failed: {e}")

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
