"""Integration test for pack execution with mocked collectors."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from beacon.config import BeaconSettings, reset_settings
from beacon.evidence.builder import EvidencePackBuilder
from beacon.models.envelope import Metric, PluginEnvelope
from beacon.packs.executor import PackExecutor
from beacon.packs.registry import PluginRegistry
from beacon.packs.schema import PackDefinition, StepConfig
from beacon.storage.evidence_store import EvidenceStore


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


def _mock_envelope(name: str, run_id) -> PluginEnvelope:
    now = datetime.now(timezone.utc)
    return PluginEnvelope(
        plugin_name=name,
        plugin_version="0.1.0",
        run_id=run_id,
        metrics=[
            Metric(
                measurement=f"{name}_test",
                fields={"value": 42.0},
                timestamp=now,
            ),
        ],
        started_at=now,
        completed_at=now,
    )


class TestPackExecution:
    def test_full_execution_produces_evidence(self, tmp_path):
        """Test that executing a pack produces a valid evidence pack."""
        run_id = uuid4()

        # Set up mock registry
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_collector = MagicMock()
        mock_collector.collect.return_value = _mock_envelope("device", run_id)
        mock_runner = MagicMock()
        mock_runner.run.return_value = _mock_envelope("ping", run_id)
        mock_registry.get_collector.return_value = mock_collector
        mock_registry.get_runner.return_value = mock_runner

        # Define a simple pack
        pack = PackDefinition(
            name="test_integration",
            steps=[
                StepConfig(plugin="device", type="collector"),
                StepConfig(plugin="ping", type="runner"),
            ],
        )

        # Execute
        executor = PackExecutor(mock_registry)
        envelopes = executor.execute(pack, run_id)
        assert len(envelopes) == 2

        # Build evidence pack
        from beacon.config import StorageSettings
        settings = BeaconSettings(storage=StorageSettings(
            data_dir=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            evidence_dir=tmp_path / "evidence",
        ))

        with patch("beacon.evidence.builder.capture_environment") as mock_env, \
             patch("beacon.evidence.builder._capture_health") as mock_health:
            from beacon.models.evidence import EnvironmentSnapshot
            from beacon.models.health import CPUHealth, HealthSnapshot, MemoryHealth

            mock_env.return_value = EnvironmentSnapshot(
                hostname="test", os="Linux", os_version="6.1",
                architecture="x86_64", python_version="3.11.0",
            )
            mock_health.return_value = HealthSnapshot(
                cpu=CPUHealth(percent=25.0, load_avg_1m=1.0, load_avg_5m=0.8,
                              load_avg_15m=0.6, core_count=4),
                memory=MemoryHealth(total_mb=8192, available_mb=4096, percent_used=50.0),
            )

            builder = EvidencePackBuilder(settings)
            started_at = datetime.now(timezone.utc)
            evidence = builder.build(run_id, "test_integration", envelopes, started_at)

        # Verify evidence pack
        assert evidence.version == "1.0"
        assert evidence.run_id == run_id
        assert evidence.pack_name == "test_integration"
        assert len(evidence.test_results) == 2
        assert evidence.fault_domain is not None

        # Save and reload
        store = EvidenceStore(tmp_path / "evidence")
        path = store.save(evidence)
        assert path.exists()

        reloaded = store.load(run_id)
        assert reloaded is not None
        assert reloaded.run_id == run_id
        assert len(reloaded.test_results) == 2
