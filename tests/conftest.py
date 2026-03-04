"""Shared test fixtures for Beacon."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from beacon.models.envelope import Artifact, Event, Metric, PluginEnvelope, Severity
from beacon.models.fault import CompetingHypothesis, FaultDomain, FaultDomainResult
from beacon.models.health import CPUHealth, DiskHealth, HealthSnapshot, MemoryHealth, ThermalHealth
from beacon.models.evidence import EnvironmentSnapshot, EvidencePack, EventCorrelation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def run_id():
    return uuid4()


@pytest.fixture
def sample_metric():
    return Metric(
        measurement="ping",
        fields={"rtt_ms": 12.5, "loss_pct": 0.0},
        tags={"target": "8.8.8.8"},
        timestamp=_utcnow(),
    )


@pytest.fixture
def sample_event():
    return Event(
        event_type="threshold_breach",
        severity=Severity.WARNING,
        message="RTT exceeded 100ms threshold",
        tags={"domain": "isp"},
        timestamp=_utcnow(),
    )


@pytest.fixture
def sample_artifact(tmp_path):
    test_file = tmp_path / "test.log"
    test_file.write_text("test log content")
    return Artifact(
        artifact_type="log",
        ref=str(test_file),
        sha256="abc123def456",
        ttl_hours=24,
        metadata={"source": "ping_runner"},
    )


@pytest.fixture
def sample_envelope(run_id, sample_metric, sample_event, sample_artifact):
    now = _utcnow()
    return PluginEnvelope(
        plugin_name="ping",
        plugin_version="0.1.0",
        run_id=run_id,
        metrics=[sample_metric],
        events=[sample_event],
        artifacts=[sample_artifact],
        notes=["Completed successfully"],
        started_at=now,
        completed_at=now,
    )


@pytest.fixture
def sample_health():
    return HealthSnapshot(
        cpu=CPUHealth(
            percent=25.0,
            load_avg_1m=1.2,
            load_avg_5m=1.0,
            load_avg_15m=0.8,
            core_count=4,
        ),
        memory=MemoryHealth(
            total_mb=8192.0,
            available_mb=4096.0,
            percent_used=50.0,
        ),
        disks=[
            DiskHealth(path="/", total_gb=256.0, free_gb=128.0, percent_used=50.0),
        ],
        thermals=[
            ThermalHealth(label="cpu_thermal", current_celsius=55.0, high_celsius=80.0),
        ],
    )


@pytest.fixture
def sample_environment():
    return EnvironmentSnapshot(
        hostname="beacon-test",
        os="Linux",
        os_version="6.1.0",
        architecture="aarch64",
        python_version="3.11.0",
        interfaces=[{"name": "eth0", "ipv4": "192.168.1.100"}],
        default_gateway="192.168.1.1",
    )


@pytest.fixture
def sample_fault_result():
    return FaultDomainResult(
        fault_domain=FaultDomain.ISP,
        confidence=0.78,
        evidence_refs=["ping:8.8.8.8:rtt_ms", "traceroute:hop_7:timeout"],
        competing_hypotheses=[
            CompetingHypothesis(
                fault_domain=FaultDomain.WIFI,
                confidence=0.35,
                reasoning="Wi-Fi metrics are within normal range",
            ),
        ],
    )


@pytest.fixture
def sample_evidence_pack(
    run_id, sample_envelope, sample_health, sample_environment, sample_fault_result
):
    now = _utcnow()
    return EvidencePack(
        run_id=run_id,
        pack_name="full_diagnostic",
        started_at=now,
        completed_at=now,
        host_id="test-host-001",
        probe_id="beacon-01",
        beacon_version="0.1.0",
        environment=sample_environment,
        health=sample_health,
        test_results=[sample_envelope],
        event_correlation=[
            EventCorrelation(
                event_ref="threshold_breach:rtt",
                correlated_metrics=["ping:8.8.8.8:rtt_ms"],
                description="High RTT coincided with threshold breach",
            ),
        ],
        fault_domain=sample_fault_result,
        artifact_manifest=sample_envelope.artifacts,
    )
