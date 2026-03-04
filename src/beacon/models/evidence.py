"""Evidence Pack v1 — the final output artifact of a diagnostic run.

An EvidencePack is a self-contained, portable JSON document that captures
everything needed to understand and reproduce a network diagnosis.

Schema versioning: `schema_version` evolves independently from `beacon_version`.
The schema version tracks structural changes to the JSON format, while the
beacon version tracks the software release.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from beacon.models.envelope import Artifact, PluginEnvelope
from beacon.models.fault import FaultDomainResult
from beacon.models.health import HealthSnapshot


class EnvironmentSnapshot(BaseModel):
    """Captures the host environment at the time of the diagnostic run."""

    hostname: str
    os: str
    os_version: str
    architecture: str
    python_version: str
    interfaces: list[dict[str, Any]] = Field(default_factory=list)
    default_gateway: str | None = None
    public_ip: str | None = None


class EventCorrelation(BaseModel):
    """Links events to metrics that occurred around the same time."""

    event_ref: str
    correlated_metrics: list[str] = Field(default_factory=list)
    time_window_seconds: float = 5.0
    description: str = ""


class Capabilities(BaseModel):
    """What this host/run was able to collect."""

    wifi: bool = False
    traceroute: bool = False
    pcap: bool = False
    privileged_collectors: bool = False
    wifi_method: str | None = None


class Summary(BaseModel):
    """Human-readable verdict matching the CLI output."""

    tests_run: int = 0
    metrics_collected: int = 0
    events_detected: int = 0
    faults_detected: int = 0
    result: str = "unknown"
    detail: str = ""


class EvidencePack(BaseModel):
    """Complete diagnostic evidence bundle.

    This is the top-level output of a Beacon diagnostic run. It ties together
    environment context, device health, test results from all plugins,
    event correlations, fault domain analysis, and artifact references.
    """

    schema_version: str = "1.1"
    version: str = "1.0"  # kept for backward compat
    run_id: UUID
    pack_name: str
    started_at: datetime
    completed_at: datetime
    host_id: str
    probe_id: str
    beacon_version: str
    capabilities: Capabilities = Field(default_factory=Capabilities)
    summary: Summary = Field(default_factory=Summary)
    environment: EnvironmentSnapshot
    health: HealthSnapshot
    test_results: list[PluginEnvelope] = Field(default_factory=list)
    event_correlation: list[EventCorrelation] = Field(default_factory=list)
    fault_domain: FaultDomainResult
    artifact_manifest: list[Artifact] = Field(default_factory=list)
