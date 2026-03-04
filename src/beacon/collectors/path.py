"""Path collector — gateway reachability check (privileged).

Pings the default gateway to verify local network path is healthy.
Requires NET_RAW capability for ICMP.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from uuid import UUID

from beacon.collectors.base import BaseCollector
from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity

logger = logging.getLogger(__name__)


def _detect_gateway() -> str | None:
    """Detect the default gateway address."""
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "gateway:" in line:
                    return line.split("gateway:")[-1].strip()
        elif system == "Linux":
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            parts = result.stdout.strip().split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except Exception:
        logger.debug("Gateway detection failed", exc_info=True)
    return None


class PathCollector(BaseCollector):
    name = "path"
    version = "0.1.0"

    def __init__(self, gateway: str | None = None):
        self._gateway = gateway

    def collect(self, run_id: UUID) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []
        now = self._now()

        gateway = self._gateway or _detect_gateway()
        if not gateway:
            notes.append("Could not detect default gateway")
            return PluginEnvelope(
                plugin_name=self.name,
                plugin_version=self.version,
                run_id=run_id,
                notes=notes,
                started_at=started_at,
                completed_at=self._now(),
            )

        try:
            system = platform.system()
            count_flag = "-c" if system != "Windows" else "-n"
            result = subprocess.run(
                ["ping", count_flag, "5", "-W", "2", gateway],
                capture_output=True,
                text=True,
                timeout=15,
            )

            # Parse ping output for stats
            output = result.stdout
            loss_match = re.search(r"(\d+(?:\.\d+)?)% (?:packet )?loss", output)
            rtt_match = re.search(
                r"(?:rtt|round-trip)\s+min/avg/max(?:/[a-z]+)?\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)",
                output,
            )

            fields: dict[str, float | int | str | bool] = {
                "reachable": result.returncode == 0,
                "gateway": gateway,
            }

            if loss_match:
                fields["loss_pct"] = float(loss_match.group(1))
            if rtt_match:
                fields["rtt_min_ms"] = float(rtt_match.group(1))
                fields["rtt_avg_ms"] = float(rtt_match.group(2))
                fields["rtt_max_ms"] = float(rtt_match.group(3))

            metrics.append(
                Metric(
                    measurement="path_gateway",
                    fields=fields,
                    tags={"gateway": gateway},
                    timestamp=now,
                )
            )

            if result.returncode != 0:
                events.append(
                    Event(
                        event_type="gateway_unreachable",
                        severity=Severity.CRITICAL,
                        message=f"Default gateway {gateway} is unreachable",
                        tags={"gateway": gateway},
                        timestamp=now,
                    )
                )

        except subprocess.TimeoutExpired:
            notes.append(f"Ping to gateway {gateway} timed out")
            events.append(
                Event(
                    event_type="gateway_timeout",
                    severity=Severity.CRITICAL,
                    message=f"Ping to gateway {gateway} timed out",
                    tags={"gateway": gateway},
                    timestamp=now,
                )
            )
        except Exception as e:
            notes.append(f"Gateway ping failed: {e}")

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
