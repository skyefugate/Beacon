"""Unit tests for evidence builder and helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4


from beacon.evidence.manifest import build_manifest
from beacon.evidence.builder import EvidencePackBuilder, _capture_health
from beacon.models.envelope import Artifact, Metric, PluginEnvelope


def _now():
    return datetime.now(timezone.utc)


class TestBuildManifest:
    def test_collects_all_artifacts(self):
        env1 = PluginEnvelope(
            plugin_name="a",
            plugin_version="0.1.0",
            run_id=uuid4(),
            artifacts=[
                Artifact(artifact_type="pcap", ref="/a.pcap", sha256="aaa"),
            ],
            started_at=_now(),
            completed_at=_now(),
        )
        env2 = PluginEnvelope(
            plugin_name="b",
            plugin_version="0.1.0",
            run_id=uuid4(),
            artifacts=[
                Artifact(artifact_type="log", ref="/b.log", sha256="bbb"),
            ],
            started_at=_now(),
            completed_at=_now(),
        )

        manifest = build_manifest([env1, env2])
        assert len(manifest) == 2

    def test_deduplicates_by_sha256(self):
        env = PluginEnvelope(
            plugin_name="a",
            plugin_version="0.1.0",
            run_id=uuid4(),
            artifacts=[
                Artifact(artifact_type="pcap", ref="/a.pcap", sha256="same"),
                Artifact(artifact_type="pcap", ref="/b.pcap", sha256="same"),
            ],
            started_at=_now(),
            completed_at=_now(),
        )

        manifest = build_manifest([env])
        assert len(manifest) == 1

    def test_empty_envelopes(self):
        env = PluginEnvelope(
            plugin_name="a",
            plugin_version="0.1.0",
            run_id=uuid4(),
            started_at=_now(),
            completed_at=_now(),
        )
        assert build_manifest([env]) == []


class TestCaptureHealth:
    def test_returns_health_snapshot(self):
        with patch("beacon.evidence.builder.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 30.0
            mock_psutil.getloadavg.return_value = (1.0, 0.8, 0.6)
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=4 * 1024**3, percent=50.0
            )
            mock_psutil.disk_partitions.return_value = []
            mock_psutil.sensors_temperatures.side_effect = AttributeError

            health = _capture_health()
            assert health.cpu.percent == 30.0
            assert health.memory.percent_used == 50.0


class TestEvidencePackBuilder:
    def test_builds_complete_pack(self):
        with (
            patch("beacon.evidence.builder.capture_environment") as mock_env,
            patch("beacon.evidence.builder._capture_health") as mock_health,
        ):
            from beacon.models.evidence import EnvironmentSnapshot
            from beacon.models.health import CPUHealth, HealthSnapshot, MemoryHealth

            mock_env.return_value = EnvironmentSnapshot(
                hostname="test",
                os="Linux",
                os_version="6.1",
                architecture="x86_64",
                python_version="3.11.0",
            )
            mock_health.return_value = HealthSnapshot(
                cpu=CPUHealth(
                    percent=25.0, load_avg_1m=1.0, load_avg_5m=0.8, load_avg_15m=0.6, core_count=4
                ),
                memory=MemoryHealth(total_mb=8192, available_mb=4096, percent_used=50.0),
            )

            from beacon.config import BeaconSettings

            settings = BeaconSettings()

            builder = EvidencePackBuilder(settings)
            run_id = uuid4()
            started_at = _now()

            envelopes = [
                PluginEnvelope(
                    plugin_name="ping",
                    plugin_version="0.1.0",
                    run_id=run_id,
                    metrics=[
                        Metric(
                            measurement="ping",
                            fields={"loss_pct": 0.0, "rtt_avg_ms": 15.0},
                            tags={"target": "8.8.8.8"},
                            timestamp=started_at,
                        ),
                    ],
                    started_at=started_at,
                    completed_at=_now(),
                ),
            ]

            pack = builder.build(run_id, "test_pack", envelopes, started_at)

            assert pack.version == "1.0"
            assert pack.run_id == run_id
            assert pack.pack_name == "test_pack"
            assert pack.beacon_version == "0.1.0"
            assert len(pack.test_results) == 1
            assert pack.fault_domain is not None
            assert pack.environment.hostname == "test"
