"""Unit tests for evidence builder."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4
import pytest

from beacon.evidence.builder import EvidenceBuilder
from beacon.models.envelope import PluginEnvelope, Metric, Event, Artifact, Severity
from beacon.models.evidence import EnvironmentSnapshot, EvidencePack
from beacon.models.health import HealthSnapshot, CPUHealth, MemoryHealth
from beacon.models.fault import FaultDomainResult, FaultDomain


@pytest.fixture
def mock_environment():
    return EnvironmentSnapshot(
        hostname="test-host",
        os="Linux",
        os_version="5.4.0",
        architecture="x86_64",
        python_version="3.11.0",
        interfaces=[{"name": "eth0", "ipv4": "192.168.1.100"}],
        default_gateway="192.168.1.1",
        public_ip="203.0.113.1",
    )


@pytest.fixture
def mock_health():
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
        disks=[],
        thermals=[],
    )


@pytest.fixture
def sample_envelope():
    now = datetime.now(timezone.utc)
    return PluginEnvelope(
        plugin_name="ping",
        plugin_version="1.0.0",
        run_id=uuid4(),
        metrics=[
            Metric(
                measurement="ping",
                fields={"rtt_ms": 12.5},
                tags={"target": "8.8.8.8"},
                timestamp=now,
            )
        ],
        events=[
            Event(
                event_type="threshold_breach",
                severity=Severity.WARNING,
                message="High RTT detected",
                tags={"target": "8.8.8.8"},
                timestamp=now,
            )
        ],
        artifacts=[
            Artifact(
                artifact_type="log",
                ref="/tmp/test.log",
                sha256="abc123",
                ttl_hours=24,
                metadata={"source": "ping"},
            )
        ],
        notes=["Test completed"],
        started_at=now,
        completed_at=now,
    )


class TestEvidenceBuilder:
    def test_init(self):
        run_id = uuid4()
        builder = EvidenceBuilder(run_id, "test_pack")
        
        assert builder.run_id == run_id
        assert builder.pack_name == "test_pack"
        assert builder.host_id is None
        assert builder.probe_id is None
        assert builder.beacon_version is None
        assert builder.environment is None
        assert builder.health is None
        assert builder.test_results == []
        assert builder.event_correlation == []
        assert builder.fault_domain is None
        assert builder.artifact_manifest == []

    def test_set_metadata(self):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        
        builder.set_metadata(
            host_id="host-001",
            probe_id="probe-001",
            beacon_version="1.0.0"
        )
        
        assert builder.host_id == "host-001"
        assert builder.probe_id == "probe-001"
        assert builder.beacon_version == "1.0.0"

    def test_set_environment(self, mock_environment):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        
        builder.set_environment(mock_environment)
        
        assert builder.environment == mock_environment

    def test_set_health(self, mock_health):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        
        builder.set_health(mock_health)
        
        assert builder.health == mock_health

    def test_add_test_result(self, sample_envelope):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        
        builder.add_test_result(sample_envelope)
        
        assert len(builder.test_results) == 1
        assert builder.test_results[0] == sample_envelope

    def test_add_multiple_test_results(self, sample_envelope):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        envelope2 = PluginEnvelope(
            plugin_name="dns",
            plugin_version="1.0.0",
            run_id=uuid4(),
            metrics=[],
            events=[],
            artifacts=[],
            notes=[],
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        
        builder.add_test_result(sample_envelope)
        builder.add_test_result(envelope2)
        
        assert len(builder.test_results) == 2

    def test_set_fault_domain(self):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        fault_result = FaultDomainResult(
            fault_domain=FaultDomain.ISP,
            confidence=0.85,
            evidence_refs=["ping:8.8.8.8:rtt_ms"],
            competing_hypotheses=[],
        )
        
        builder.set_fault_domain(fault_result)
        
        assert builder.fault_domain == fault_result

    @patch("beacon.evidence.builder.datetime")
    def test_build_complete_evidence_pack(self, mock_datetime, mock_environment, mock_health, sample_envelope):
        now = datetime.now(timezone.utc)
        mock_datetime.now.return_value = now
        
        run_id = uuid4()
        builder = EvidenceBuilder(run_id, "test_pack")
        
        builder.set_metadata("host-001", "probe-001", "1.0.0")
        builder.set_environment(mock_environment)
        builder.set_health(mock_health)
        builder.add_test_result(sample_envelope)
        
        fault_result = FaultDomainResult(
            fault_domain=FaultDomain.ISP,
            confidence=0.85,
            evidence_refs=["ping:8.8.8.8:rtt_ms"],
            competing_hypotheses=[],
        )
        builder.set_fault_domain(fault_result)
        
        evidence_pack = builder.build()
        
        assert isinstance(evidence_pack, EvidencePack)
        assert evidence_pack.run_id == run_id
        assert evidence_pack.pack_name == "test_pack"
        assert evidence_pack.host_id == "host-001"
        assert evidence_pack.probe_id == "probe-001"
        assert evidence_pack.beacon_version == "1.0.0"
        assert evidence_pack.environment == mock_environment
        assert evidence_pack.health == mock_health
        assert len(evidence_pack.test_results) == 1
        assert evidence_pack.fault_domain == fault_result
        assert len(evidence_pack.artifact_manifest) == 1

    @patch("beacon.evidence.builder.datetime")
    def test_build_minimal_evidence_pack(self, mock_datetime):
        now = datetime.now(timezone.utc)
        mock_datetime.now.return_value = now
        
        run_id = uuid4()
        builder = EvidenceBuilder(run_id, "minimal_pack")
        
        evidence_pack = builder.build()
        
        assert isinstance(evidence_pack, EvidencePack)
        assert evidence_pack.run_id == run_id
        assert evidence_pack.pack_name == "minimal_pack"
        assert evidence_pack.started_at == now
        assert evidence_pack.completed_at == now
        assert evidence_pack.host_id is None
        assert evidence_pack.probe_id is None
        assert evidence_pack.beacon_version is None
        assert evidence_pack.environment is None
        assert evidence_pack.health is None
        assert evidence_pack.test_results == []
        assert evidence_pack.event_correlation == []
        assert evidence_pack.fault_domain is None
        assert evidence_pack.artifact_manifest == []

    def test_build_aggregates_artifacts(self, sample_envelope):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        
        # Add multiple envelopes with artifacts
        envelope2 = PluginEnvelope(
            plugin_name="dns",
            plugin_version="1.0.0",
            run_id=uuid4(),
            metrics=[],
            events=[],
            artifacts=[
                Artifact(
                    artifact_type="pcap",
                    ref="/tmp/dns.pcap",
                    sha256="def456",
                    ttl_hours=48,
                    metadata={"source": "dns"},
                )
            ],
            notes=[],
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        
        builder.add_test_result(sample_envelope)
        builder.add_test_result(envelope2)
        
        evidence_pack = builder.build()
        
        # Should aggregate artifacts from all envelopes
        assert len(evidence_pack.artifact_manifest) == 2
        artifact_types = {artifact.artifact_type for artifact in evidence_pack.artifact_manifest}
        assert artifact_types == {"log", "pcap"}

    def test_build_with_event_correlation(self, sample_envelope):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        builder.add_test_result(sample_envelope)
        
        # Manually add event correlation (in real usage, this would be done by analysis)
        from beacon.models.evidence import EventCorrelation
        correlation = EventCorrelation(
            event_ref="threshold_breach:rtt",
            correlated_metrics=["ping:8.8.8.8:rtt_ms"],
            description="High RTT event correlated with metric",
        )
        builder.event_correlation.append(correlation)
        
        evidence_pack = builder.build()
        
        assert len(evidence_pack.event_correlation) == 1
        assert evidence_pack.event_correlation[0] == correlation

    def test_build_preserves_timestamps(self, sample_envelope):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        builder.add_test_result(sample_envelope)
        
        # Set specific timestamps
        start_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2023, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
        
        with patch("beacon.evidence.builder.datetime") as mock_datetime:
            mock_datetime.now.side_effect = [start_time, end_time]
            evidence_pack = builder.build()
        
        assert evidence_pack.started_at == start_time
        assert evidence_pack.completed_at == end_time

    def test_build_multiple_times_returns_same_data(self, mock_environment, sample_envelope):
        builder = EvidenceBuilder(uuid4(), "test_pack")
        builder.set_environment(mock_environment)
        builder.add_test_result(sample_envelope)
        
        pack1 = builder.build()
        pack2 = builder.build()
        
        assert pack1.run_id == pack2.run_id
        assert pack1.pack_name == pack2.pack_name
        assert pack1.environment == pack2.environment
        assert len(pack1.test_results) == len(pack2.test_results)

    def test_builder_state_isolation(self):
        """Test that multiple builders don't interfere with each other."""
        run_id1 = uuid4()
        run_id2 = uuid4()
        
        builder1 = EvidenceBuilder(run_id1, "pack1")
        builder2 = EvidenceBuilder(run_id2, "pack2")
        
        builder1.set_metadata("host1", "probe1", "1.0.0")
        builder2.set_metadata("host2", "probe2", "2.0.0")
        
        pack1 = builder1.build()
        pack2 = builder2.build()
        
        assert pack1.run_id == run_id1
        assert pack2.run_id == run_id2
        assert pack1.pack_name == "pack1"
        assert pack2.pack_name == "pack2"
        assert pack1.host_id == "host1"
        assert pack2.host_id == "host2"