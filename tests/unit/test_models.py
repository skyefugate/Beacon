"""Unit tests for all Beacon data models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from beacon.models.envelope import Artifact, Event, Metric, PluginEnvelope, Severity
from beacon.models.fault import FaultDomain, FaultDomainResult
from beacon.models.health import CPUHealth, HealthSnapshot, MemoryHealth
from beacon.models.evidence import EnvironmentSnapshot, EvidencePack


class TestMetric:
    def test_create_with_required_fields(self):
        m = Metric(
            measurement="ping",
            fields={"rtt_ms": 12.5},
            timestamp=datetime.now(timezone.utc),
        )
        assert m.measurement == "ping"
        assert m.fields["rtt_ms"] == 12.5
        assert m.tags == {}

    def test_create_with_tags(self):
        m = Metric(
            measurement="dns_resolve",
            fields={"latency_ms": 5.2, "success": True},
            tags={"resolver": "8.8.8.8", "domain": "google.com"},
            timestamp=datetime.now(timezone.utc),
        )
        assert m.tags["resolver"] == "8.8.8.8"
        assert m.fields["success"] is True

    def test_json_roundtrip(self):
        m = Metric(
            measurement="wifi_link",
            fields={"rssi_dbm": -65, "noise_dbm": -90},
            tags={"interface": "wlan0"},
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        data = json.loads(m.model_dump_json())
        m2 = Metric.model_validate(data)
        assert m2.measurement == m.measurement
        assert m2.fields == m.fields


class TestEvent:
    def test_severity_enum(self):
        for sev in Severity:
            e = Event(
                event_type="test",
                severity=sev,
                message=f"Test {sev.value}",
                timestamp=datetime.now(timezone.utc),
            )
            assert e.severity == sev

    def test_from_string_severity(self):
        e = Event(
            event_type="deauth",
            severity="critical",
            message="Deauthentication detected",
            timestamp=datetime.now(timezone.utc),
        )
        assert e.severity == Severity.CRITICAL


class TestArtifact:
    def test_create_artifact(self):
        a = Artifact(
            artifact_type="pcap",
            ref="/data/artifacts/capture.pcap",
            sha256="a" * 64,
        )
        assert a.artifact_type == "pcap"
        assert a.ttl_hours is None
        assert a.metadata == {}

    def test_with_metadata(self):
        a = Artifact(
            artifact_type="json",
            ref="/data/artifacts/traceroute.json",
            sha256="b" * 64,
            ttl_hours=48,
            metadata={"hops": 15, "target": "8.8.8.8"},
        )
        assert a.ttl_hours == 48
        assert a.metadata["hops"] == 15


class TestPluginEnvelope:
    def test_minimal_envelope(self):
        now = datetime.now(timezone.utc)
        env = PluginEnvelope(
            plugin_name="test",
            plugin_version="0.1.0",
            run_id=uuid4(),
            started_at=now,
            completed_at=now,
        )
        assert env.metrics == []
        assert env.events == []
        assert env.artifacts == []
        assert env.notes == []

    def test_full_envelope(self, sample_envelope):
        assert sample_envelope.plugin_name == "ping"
        assert len(sample_envelope.metrics) == 1
        assert len(sample_envelope.events) == 1
        assert len(sample_envelope.artifacts) == 1
        assert "Completed successfully" in sample_envelope.notes

    def test_json_serialization(self, sample_envelope):
        json_str = sample_envelope.model_dump_json()
        data = json.loads(json_str)
        assert data["plugin_name"] == "ping"
        assert isinstance(data["run_id"], str)

    def test_json_roundtrip(self, sample_envelope):
        data = json.loads(sample_envelope.model_dump_json())
        restored = PluginEnvelope.model_validate(data)
        assert restored.plugin_name == sample_envelope.plugin_name
        assert restored.run_id == sample_envelope.run_id
        assert len(restored.metrics) == len(sample_envelope.metrics)


class TestFaultDomain:
    def test_all_domains_exist(self):
        expected = {"device", "wifi", "lan", "isp", "dns", "app_saas", "vpn_sase", "unknown"}
        actual = {d.value for d in FaultDomain}
        assert actual == expected

    def test_fault_domain_result_validation(self):
        with pytest.raises(Exception):
            FaultDomainResult(
                fault_domain=FaultDomain.WIFI,
                confidence=1.5,  # Out of range
                evidence_refs=[],
            )

    def test_fault_domain_result(self, sample_fault_result):
        assert sample_fault_result.fault_domain == FaultDomain.ISP
        assert 0.0 <= sample_fault_result.confidence <= 1.0
        assert len(sample_fault_result.competing_hypotheses) == 1
        assert sample_fault_result.competing_hypotheses[0].fault_domain == FaultDomain.WIFI

    def test_json_roundtrip(self, sample_fault_result):
        data = json.loads(sample_fault_result.model_dump_json())
        restored = FaultDomainResult.model_validate(data)
        assert restored.fault_domain == sample_fault_result.fault_domain
        assert restored.confidence == sample_fault_result.confidence


class TestHealthSnapshot:
    def test_health_snapshot(self, sample_health):
        assert sample_health.cpu.core_count == 4
        assert sample_health.memory.percent_used == 50.0
        assert len(sample_health.disks) == 1
        assert len(sample_health.thermals) == 1

    def test_minimal_health(self):
        h = HealthSnapshot(
            cpu=CPUHealth(percent=10.0, load_avg_1m=0.5, load_avg_5m=0.4, load_avg_15m=0.3, core_count=2),
            memory=MemoryHealth(total_mb=4096.0, available_mb=3000.0, percent_used=26.7),
        )
        assert h.disks == []
        assert h.thermals == []


class TestEnvironmentSnapshot:
    def test_environment_snapshot(self, sample_environment):
        assert sample_environment.hostname == "beacon-test"
        assert sample_environment.os == "Linux"
        assert sample_environment.default_gateway == "192.168.1.1"
        assert sample_environment.public_ip is None

    def test_minimal_environment(self):
        env = EnvironmentSnapshot(
            hostname="test",
            os="Linux",
            os_version="6.1",
            architecture="x86_64",
            python_version="3.11.0",
        )
        assert env.interfaces == []
        assert env.default_gateway is None


class TestEvidencePack:
    def test_evidence_pack_version(self, sample_evidence_pack):
        assert sample_evidence_pack.version == "1.0"

    def test_evidence_pack_structure(self, sample_evidence_pack):
        assert sample_evidence_pack.pack_name == "full_diagnostic"
        assert sample_evidence_pack.beacon_version == "0.1.0"
        assert len(sample_evidence_pack.test_results) == 1
        assert len(sample_evidence_pack.event_correlation) == 1
        assert sample_evidence_pack.fault_domain.fault_domain == FaultDomain.ISP

    def test_json_roundtrip(self, sample_evidence_pack):
        json_str = sample_evidence_pack.model_dump_json()
        data = json.loads(json_str)
        restored = EvidencePack.model_validate(data)
        assert restored.run_id == sample_evidence_pack.run_id
        assert restored.pack_name == sample_evidence_pack.pack_name
        assert restored.fault_domain.confidence == sample_evidence_pack.fault_domain.confidence
        assert len(restored.test_results) == len(sample_evidence_pack.test_results)

    def test_model_dump_json_mode(self, sample_evidence_pack):
        """Verify model_dump(mode='json') produces JSON-safe types."""
        data = sample_evidence_pack.model_dump(mode="json")
        assert isinstance(data["run_id"], str)
        assert isinstance(data["started_at"], str)
        assert isinstance(data["fault_domain"]["fault_domain"], str)
