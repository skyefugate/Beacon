"""Evidence pack assembler — ties everything together into a complete EvidencePack.

This is the final step in a diagnostic run. It combines environment snapshot,
health data, test results, event correlations, fault domain analysis, and
artifact manifest into a single EvidencePack.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import psutil

from beacon import __version__
from beacon.config import BeaconSettings
from beacon.engine.fault_domain import FaultDomainEngine
from beacon.evidence.environment import capture_environment
from beacon.evidence.manifest import build_manifest
from beacon.models.envelope import PluginEnvelope
from beacon.models.evidence import Capabilities, EvidencePack, Summary
from beacon.models.health import CPUHealth, DiskHealth, HealthSnapshot, MemoryHealth, ThermalHealth

logger = logging.getLogger(__name__)


def _capture_health() -> HealthSnapshot:
    """Capture current device health snapshot."""
    cpu_pct = psutil.cpu_percent(interval=0)
    load_1, load_5, load_15 = psutil.getloadavg()
    mem = psutil.virtual_memory()

    disks: list[DiskHealth] = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append(DiskHealth(
                path=part.mountpoint,
                total_gb=usage.total / (1024**3),
                free_gb=usage.free / (1024**3),
                percent_used=usage.percent,
            ))
        except PermissionError:
            pass

    thermals: list[ThermalHealth] = []
    try:
        for label, entries in psutil.sensors_temperatures().items():
            for entry in entries:
                thermals.append(ThermalHealth(
                    label=entry.label or label,
                    current_celsius=entry.current,
                    high_celsius=entry.high,
                    critical_celsius=entry.critical,
                ))
    except AttributeError:
        pass

    return HealthSnapshot(
        cpu=CPUHealth(
            percent=cpu_pct,
            load_avg_1m=load_1,
            load_avg_5m=load_5,
            load_avg_15m=load_15,
            core_count=psutil.cpu_count(logical=True) or 1,
        ),
        memory=MemoryHealth(
            total_mb=mem.total / (1024 * 1024),
            available_mb=mem.available / (1024 * 1024),
            percent_used=mem.percent,
        ),
        disks=disks,
        thermals=thermals,
    )


class EvidencePackBuilder:
    """Assembles a complete EvidencePack from diagnostic run data."""

    def __init__(
        self,
        settings: BeaconSettings,
        engine: FaultDomainEngine | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine or FaultDomainEngine()

    def build(
        self,
        run_id: UUID,
        pack_name: str,
        envelopes: list[PluginEnvelope],
        started_at: datetime,
    ) -> EvidencePack:
        """Build a complete EvidencePack from collected envelopes."""
        completed_at = datetime.now(timezone.utc)

        # Capture environment and health
        environment = capture_environment()
        health = _capture_health()

        # Run fault domain analysis
        fault_result, correlations = self._engine.analyze(envelopes)

        # Build artifact manifest
        manifest = build_manifest(envelopes)

        # Derive capabilities from what the plugins actually produced
        capabilities = self._derive_capabilities(envelopes)

        # Build summary
        total_metrics = sum(len(e.metrics) for e in envelopes)
        total_events = sum(len(e.events) for e in envelopes)
        faults_detected = 1 if fault_result.confidence > 0 else 0

        if faults_detected:
            result_str = fault_result.fault_domain.value
            detail = (
                f"Fault domain: {fault_result.fault_domain.value} "
                f"({fault_result.confidence:.0%} confidence), "
                f"{len(fault_result.evidence_refs)} evidence signals"
            )
        elif total_metrics > 0:
            result_str = "healthy"
            detail = f"{total_metrics} metrics collected, all within normal ranges"
        else:
            result_str = "unknown"
            detail = "Insufficient data to classify"

        summary = Summary(
            tests_run=len(envelopes),
            metrics_collected=total_metrics,
            events_detected=total_events,
            faults_detected=faults_detected,
            result=result_str,
            detail=detail,
        )

        import socket
        host_id = socket.gethostname()

        return EvidencePack(
            run_id=run_id,
            pack_name=pack_name,
            started_at=started_at,
            completed_at=completed_at,
            host_id=host_id,
            probe_id=self._settings.probe_id,
            beacon_version=__version__,
            capabilities=capabilities,
            summary=summary,
            environment=environment,
            health=health,
            test_results=envelopes,
            event_correlation=correlations,
            fault_domain=fault_result,
            artifact_manifest=manifest,
        )

    @staticmethod
    def _derive_capabilities(envelopes: list[PluginEnvelope]) -> Capabilities:
        """Derive capabilities from what the plugins actually produced."""
        wifi = False
        wifi_method: str | None = None
        traceroute = False
        pcap = False
        privileged = False

        for env in envelopes:
            if env.plugin_name == "wifi":
                # Check notes for method info
                for note in env.notes:
                    if "unavailable" in note.lower():
                        wifi = False
                        wifi_method = "unavailable"
                        break
                else:
                    # Check if any wifi metrics were produced
                    if env.metrics:
                        wifi = True
                        # Extract method from metric tags
                        for m in env.metrics:
                            if m.measurement == "wifi_link" and "wifi_method" in m.tags:
                                wifi_method = m.tags["wifi_method"]
                                break
                    else:
                        wifi_method = "unavailable"

            elif env.plugin_name == "traceroute":
                traceroute = bool(env.metrics)

            elif env.plugin_name in ("path", "wifi"):
                # These are typically privileged collectors
                if env.metrics:
                    privileged = True

            # Check for pcap artifacts
            for artifact in env.artifacts:
                if artifact.artifact_type == "pcap":
                    pcap = True

        return Capabilities(
            wifi=wifi,
            traceroute=traceroute,
            pcap=pcap,
            privileged_collectors=privileged,
            wifi_method=wifi_method,
        )
