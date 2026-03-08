"""Device collector — CPU, memory, disk, and thermal metrics via psutil."""

from __future__ import annotations

import logging
from uuid import UUID

import psutil

from beacon.collectors.base import BaseCollector
from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity

logger = logging.getLogger(__name__)


class DeviceCollector(BaseCollector):
    name = "device"
    version = "0.1.0"

    def collect(self, run_id: UUID) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []
        now = self._now()

        # CPU
        cpu_pct = psutil.cpu_percent(interval=1)
        load_1, load_5, load_15 = psutil.getloadavg()
        metrics.append(
            Metric(
                measurement="device_cpu",
                fields={
                    "percent": cpu_pct,
                    "load_avg_1m": load_1,
                    "load_avg_5m": load_5,
                    "load_avg_15m": load_15,
                    "core_count": psutil.cpu_count(logical=True) or 1,
                },
                timestamp=now,
            )
        )

        if cpu_pct > 90.0:
            events.append(
                Event(
                    event_type="high_cpu",
                    severity=Severity.WARNING,
                    message=f"CPU usage at {cpu_pct}%",
                    timestamp=now,
                )
            )

        # Memory
        mem = psutil.virtual_memory()
        metrics.append(
            Metric(
                measurement="device_memory",
                fields={
                    "total_mb": mem.total / (1024 * 1024),
                    "available_mb": mem.available / (1024 * 1024),
                    "percent_used": mem.percent,
                },
                timestamp=now,
            )
        )

        if mem.percent > 90.0:
            events.append(
                Event(
                    event_type="high_memory",
                    severity=Severity.WARNING,
                    message=f"Memory usage at {mem.percent}%",
                    timestamp=now,
                )
            )

        # Disk
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                metrics.append(
                    Metric(
                        measurement="device_disk",
                        fields={
                            "total_gb": usage.total / (1024**3),
                            "free_gb": usage.free / (1024**3),
                            "percent_used": usage.percent,
                        },
                        tags={"mountpoint": part.mountpoint},
                        timestamp=now,
                    )
                )
            except PermissionError:
                notes.append(f"Permission denied for disk {part.mountpoint}")

        # Thermals
        try:
            temps = psutil.sensors_temperatures()  # type: ignore[attr-defined]
            for label, entries in temps.items():
                for entry in entries:
                    fields: dict[str, float | int | str | bool] = {
                        "current_celsius": entry.current,
                    }
                    if entry.high is not None:
                        fields["high_celsius"] = entry.high
                    if entry.critical is not None:
                        fields["critical_celsius"] = entry.critical
                    metrics.append(
                        Metric(
                            measurement="device_thermal",
                            fields=fields,
                            tags={"sensor": entry.label or label},
                            timestamp=now,
                        )
                    )
        except AttributeError:
            notes.append("Thermal sensors not available on this platform")

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
