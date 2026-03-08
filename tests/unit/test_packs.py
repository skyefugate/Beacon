"""Unit tests for the pack system — schema, loader, registry, executor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4
import concurrent.futures

import pytest
import httpx

from beacon.models.envelope import PluginEnvelope
from beacon.packs.schema import PackDefinition, StepConfig
from beacon.packs.loader import PackLoader
from beacon.packs.registry import PackRegistry, PluginRegistry
from beacon.packs.executor import PackExecutor


class TestStepConfig:
    def test_defaults(self):
        step = StepConfig(plugin="ping")
        assert step.type == "runner"
        assert step.enabled is True
        assert step.privileged is False
        assert step.config == {}

    def test_privileged_collector(self):
        step = StepConfig(plugin="wifi", type="collector", privileged=True)
        assert step.type == "collector"
        assert step.privileged is True


class TestPackDefinition:
    def test_create_pack(self):
        pack = PackDefinition(
            name="test_pack",
            description="A test pack",
            steps=[
                StepConfig(plugin="device", type="collector"),
                StepConfig(plugin="ping", type="runner"),
                StepConfig(plugin="wifi", type="collector", privileged=True),
                StepConfig(plugin="disabled", type="runner", enabled=False),
            ],
        )
        assert pack.name == "test_pack"
        assert len(pack.steps) == 4

    def test_collector_steps(self):
        pack = PackDefinition(
            name="test",
            steps=[
                StepConfig(plugin="device", type="collector"),
                StepConfig(plugin="ping", type="runner"),
                StepConfig(plugin="lan", type="collector"),
                StepConfig(plugin="off", type="collector", enabled=False),
            ],
        )
        collectors = pack.collector_steps()
        assert len(collectors) == 2

    def test_runner_steps(self):
        pack = PackDefinition(
            name="test",
            steps=[
                StepConfig(plugin="device", type="collector"),
                StepConfig(plugin="ping", type="runner"),
                StepConfig(plugin="dns", type="runner"),
            ],
        )
        runners = pack.runner_steps()
        assert len(runners) == 2

    def test_privileged_steps(self):
        pack = PackDefinition(
            name="test",
            steps=[
                StepConfig(plugin="wifi", type="collector", privileged=True),
                StepConfig(plugin="path", type="collector", privileged=True),
                StepConfig(plugin="device", type="collector"),
            ],
        )
        priv = pack.privileged_steps()
        assert len(priv) == 2


class TestPackLoader:
    def test_load_file(self, tmp_path):
        pack_file = tmp_path / "test.yaml"
        pack_file.write_text(
            "name: test_pack\ndescription: Test\nsteps:\n  - plugin: ping\n    type: runner\n"
        )
        pack = PackLoader.load_file(pack_file)
        assert pack.name == "test_pack"
        assert len(pack.steps) == 1

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            PackLoader.load_file("/nonexistent/pack.yaml")

    def test_load_empty_file(self, tmp_path):
        pack_file = tmp_path / "empty.yaml"
        pack_file.write_text("")
        with pytest.raises(ValueError):
            PackLoader.load_file(pack_file)

    def test_load_directory(self, tmp_path):
        for i in range(3):
            f = tmp_path / f"pack_{i}.yaml"
            f.write_text(f"name: pack_{i}\nsteps: []\n")

        packs = PackLoader.load_directory(tmp_path)
        assert len(packs) == 3

    def test_load_real_packs(self):
        packs_dir = Path(__file__).parent.parent.parent / "packs"
        if packs_dir.is_dir():
            packs = PackLoader.load_directory(packs_dir)
            assert len(packs) >= 3
            names = {p.name for p in packs}
            assert "full_diagnostic" in names
            assert "quick_health" in names
            assert "wifi_deep_dive" in names


class TestPluginRegistry:
    def test_list_collectors(self):
        registry = PluginRegistry()
        collectors = registry.list_collectors()
        assert "device" in collectors
        assert "lan" in collectors
        assert "wifi" in collectors
        assert "path" in collectors

    def test_list_runners(self):
        registry = PluginRegistry()
        runners = registry.list_runners()
        assert "ping" in runners
        assert "dns" in runners
        assert "http" in runners
        assert "traceroute" in runners

    def test_get_unknown_collector(self):
        registry = PluginRegistry()
        with pytest.raises(KeyError):
            registry.get_collector("nonexistent")

    def test_get_unknown_runner(self):
        registry = PluginRegistry()
        with pytest.raises(KeyError):
            registry.get_runner("nonexistent")


class TestPackRegistry:
    def test_register_and_get(self):
        registry = PackRegistry()
        pack = PackDefinition(name="test", steps=[])
        registry.register(pack)
        assert registry.get("test") is pack

    def test_get_missing(self):
        registry = PackRegistry()
        assert registry.get("nonexistent") is None

    def test_list_packs(self):
        registry = PackRegistry()
        for name in ["charlie", "alpha", "bravo"]:
            registry.register(PackDefinition(name=name, steps=[]))
        packs = registry.list_packs()
        assert [p.name for p in packs] == ["alpha", "bravo", "charlie"]


class TestPackExecutor:
    def test_execute_local_steps(self):
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_collector = MagicMock()
        mock_runner = MagicMock()

        run_id = uuid4()
        now_dt = PluginEnvelope(
            plugin_name="device",
            plugin_version="0.1.0",
            run_id=run_id,
            started_at="2024-01-01T00:00:00Z",
            completed_at="2024-01-01T00:00:01Z",
        )
        mock_collector.collect.return_value = now_dt
        mock_runner.run.return_value = now_dt
        mock_registry.get_collector.return_value = mock_collector
        mock_registry.get_runner.return_value = mock_runner

        pack = PackDefinition(
            name="test",
            steps=[
                StepConfig(plugin="device", type="collector"),
                StepConfig(plugin="ping", type="runner"),
            ],
        )

        executor = PackExecutor(mock_registry)
        envelopes = executor.execute(pack, run_id)

        assert len(envelopes) == 2
        mock_collector.collect.assert_called_once()
        mock_runner.run.assert_called_once()

    def test_disabled_steps_skipped(self):
        mock_registry = MagicMock(spec=PluginRegistry)
        pack = PackDefinition(
            name="test",
            steps=[
                StepConfig(plugin="ping", type="runner", enabled=False),
            ],
        )

        executor = PackExecutor(mock_registry)
        envelopes = executor.execute(pack)
        assert len(envelopes) == 0

    def test_failed_step_continues(self):
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_registry.get_collector.side_effect = Exception("boom")

        run_id = uuid4()
        mock_runner = MagicMock()
        mock_runner.run.return_value = PluginEnvelope(
            plugin_name="ping",
            plugin_version="0.1.0",
            run_id=run_id,
            started_at="2024-01-01T00:00:00Z",
            completed_at="2024-01-01T00:00:01Z",
        )
        mock_registry.get_runner.return_value = mock_runner

        pack = PackDefinition(
            name="test",
            steps=[
                StepConfig(plugin="device", type="collector"),
                StepConfig(plugin="ping", type="runner"),
            ],
        )

        executor = PackExecutor(mock_registry)
        envelopes = executor.execute(pack, run_id)

        # First step fails, second succeeds
        assert len(envelopes) == 1

    @patch('httpx.post')
    def test_collector_fallback_on_connect_error(self, mock_post):
        """Test fallback to local execution when collector is unreachable."""
        mock_post.side_effect = httpx.ConnectError("Connection refused")
        
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_collector = MagicMock()
        run_id = uuid4()
        envelope = PluginEnvelope(
            plugin_name="wifi", plugin_version="0.1.0", run_id=run_id,
            started_at="2024-01-01T00:00:00Z", completed_at="2024-01-01T00:00:01Z"
        )
        mock_collector.collect.return_value = envelope
        mock_registry.get_collector.return_value = mock_collector

        pack = PackDefinition(name="test", steps=[
            StepConfig(plugin="wifi", type="collector", privileged=True)
        ])

        executor = PackExecutor(mock_registry)
        envelopes = executor.execute(pack, run_id)
        
        assert len(envelopes) == 1
        mock_collector.collect.assert_called_once()

    @patch('httpx.post')
    def test_step_timeout_handling(self, mock_post):
        """Test timeout handling during HTTP calls to collector."""
        mock_post.side_effect = httpx.TimeoutException("Request timeout")
        
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_collector = MagicMock()
        run_id = uuid4()
        envelope = PluginEnvelope(
            plugin_name="wifi", plugin_version="0.1.0", run_id=run_id,
            started_at="2024-01-01T00:00:00Z", completed_at="2024-01-01T00:00:01Z"
        )
        mock_collector.collect.return_value = envelope
        mock_registry.get_collector.return_value = mock_collector

        pack = PackDefinition(name="test", steps=[
            StepConfig(plugin="wifi", type="collector", privileged=True)
        ])

        executor = PackExecutor(mock_registry, collector_timeout=1)
        envelopes = executor.execute(pack, run_id)
        
        assert len(envelopes) == 1
        mock_collector.collect.assert_called_once()

    def test_evidence_storage_failures(self):
        """Test handling of evidence storage failures during execution."""
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_collector = MagicMock()
        mock_collector.collect.side_effect = OSError("Disk full")
        mock_registry.get_collector.return_value = mock_collector

        pack = PackDefinition(name="test", steps=[
            StepConfig(plugin="device", type="collector"),
            StepConfig(plugin="lan", type="collector")
        ])

        executor = PackExecutor(mock_registry)
        envelopes = executor.execute(pack)
        
        # Both steps fail due to storage issues
        assert len(envelopes) == 0

    def test_partial_pack_execution_with_failed_steps(self):
        """Test pack continues execution after step failures."""
        mock_registry = MagicMock(spec=PluginRegistry)
        
        # Both collectors fail
        mock_registry.get_collector.side_effect = Exception("Fail")
        
        # Runner succeeds
        mock_runner = MagicMock()
        run_id = uuid4()
        envelope = PluginEnvelope(
            plugin_name="ping", plugin_version="0.1.0", run_id=run_id,
            started_at="2024-01-01T00:00:00Z", completed_at="2024-01-01T00:00:01Z"
        )
        mock_runner.run.return_value = envelope
        mock_registry.get_runner.return_value = mock_runner

        pack = PackDefinition(name="test", steps=[
            StepConfig(plugin="device", type="collector"),
            StepConfig(plugin="lan", type="collector"), 
            StepConfig(plugin="ping", type="runner")
        ])

        executor = PackExecutor(mock_registry)
        envelopes = executor.execute(pack, run_id)
        
        # Only runner step succeeds
        assert len(envelopes) == 1

    def test_concurrent_pack_execution(self):
        """Test concurrent execution of multiple packs."""
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_collector = MagicMock()
        run_id = uuid4()
        envelope = PluginEnvelope(
            plugin_name="device", plugin_version="0.1.0", run_id=run_id,
            started_at="2024-01-01T00:00:00Z", completed_at="2024-01-01T00:00:01Z"
        )
        mock_collector.collect.return_value = envelope
        mock_registry.get_collector.return_value = mock_collector

        pack = PackDefinition(name="test", steps=[
            StepConfig(plugin="device", type="collector")
        ])

        executor = PackExecutor(mock_registry)
        
        def execute_pack():
            return executor.execute(pack, uuid4())

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(execute_pack) for _ in range(3)]
            results = [f.result() for f in futures]
        
        # All executions complete successfully
        assert all(len(r) == 1 for r in results)
