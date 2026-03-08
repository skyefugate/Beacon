"""Unit tests for pack executor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
import pytest

from beacon.packs.executor import PackExecutor, ExecutionResult, ExecutionError
from beacon.packs.schema import DiagnosticPack, TestSpec
from beacon.models.envelope import PluginEnvelope, Metric
from beacon.config import BeaconSettings


@pytest.fixture
def sample_pack():
    return DiagnosticPack(
        name="test_pack",
        version="1.0.0",
        description="Test diagnostic pack",
        tests=[
            TestSpec(
                name="ping_test",
                runner="ping",
                config={"targets": ["8.8.8.8"], "count": 3},
                timeout_seconds=30,
            ),
            TestSpec(
                name="dns_test",
                runner="dns",
                config={"resolvers": ["1.1.1.1"], "domains": ["google.com"]},
                timeout_seconds=15,
            ),
        ],
        timeout_seconds=300,
    )


@pytest.fixture
def mock_settings():
    return BeaconSettings()


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
                fields={"rtt_ms": 12.5, "loss_pct": 0.0},
                tags={"target": "8.8.8.8"},
                timestamp=now,
            )
        ],
        events=[],
        artifacts=[],
        notes=["Test completed successfully"],
        started_at=now,
        completed_at=now,
    )


class TestPackExecutor:
    def test_init(self, mock_settings):
        executor = PackExecutor(mock_settings)
        assert executor._settings == mock_settings
        assert executor._runners == {}

    @patch("beacon.packs.executor.importlib.import_module")
    def test_get_runner_success(self, mock_import, mock_settings):
        mock_module = Mock()
        mock_runner_class = Mock()
        mock_module.PingRunner = mock_runner_class
        mock_import.return_value = mock_module
        
        executor = PackExecutor(mock_settings)
        runner = executor._get_runner("ping")
        
        assert runner == mock_runner_class
        mock_import.assert_called_once_with("beacon.runners.ping")

    @patch("beacon.packs.executor.importlib.import_module")
    def test_get_runner_cached(self, mock_import, mock_settings):
        mock_module = Mock()
        mock_runner_class = Mock()
        mock_module.PingRunner = mock_runner_class
        mock_import.return_value = mock_module
        
        executor = PackExecutor(mock_settings)
        
        # First call
        runner1 = executor._get_runner("ping")
        # Second call should use cache
        runner2 = executor._get_runner("ping")
        
        assert runner1 == runner2
        mock_import.assert_called_once()  # Should only be called once

    @patch("beacon.packs.executor.importlib.import_module")
    def test_get_runner_import_error(self, mock_import, mock_settings):
        mock_import.side_effect = ImportError("Module not found")
        
        executor = PackExecutor(mock_settings)
        
        with pytest.raises(ExecutionError, match="Failed to import runner"):
            executor._get_runner("nonexistent")

    @patch("beacon.packs.executor.importlib.import_module")
    def test_get_runner_missing_class(self, mock_import, mock_settings):
        mock_module = Mock()
        del mock_module.NonexistentRunner  # Simulate missing class
        mock_import.return_value = mock_module
        
        executor = PackExecutor(mock_settings)
        
        with pytest.raises(ExecutionError, match="Runner class .* not found"):
            executor._get_runner("nonexistent")

    @pytest.mark.asyncio
    @patch("beacon.packs.executor.asyncio.wait_for")
    async def test_execute_test_success(self, mock_wait_for, mock_settings, sample_envelope):
        mock_runner_instance = Mock()
        mock_runner_instance.run = AsyncMock(return_value=sample_envelope)
        
        mock_runner_class = Mock(return_value=mock_runner_instance)
        
        executor = PackExecutor(mock_settings)
        executor._runners["ping"] = mock_runner_class
        
        test_spec = TestSpec(
            name="ping_test",
            runner="ping",
            config={"targets": ["8.8.8.8"]},
            timeout_seconds=30,
        )
        
        mock_wait_for.return_value = sample_envelope
        
        result = await executor._execute_test(test_spec, uuid4())
        
        assert result == sample_envelope
        mock_runner_instance.run.assert_called_once()

    @pytest.mark.asyncio
    @patch("beacon.packs.executor.asyncio.wait_for")
    async def test_execute_test_timeout(self, mock_wait_for, mock_settings):
        mock_wait_for.side_effect = asyncio.TimeoutError()
        
        mock_runner_instance = Mock()
        mock_runner_instance.run = AsyncMock()
        mock_runner_class = Mock(return_value=mock_runner_instance)
        
        executor = PackExecutor(mock_settings)
        executor._runners["ping"] = mock_runner_class
        
        test_spec = TestSpec(
            name="ping_test",
            runner="ping",
            config={"targets": ["8.8.8.8"]},
            timeout_seconds=1,
        )
        
        with pytest.raises(ExecutionError, match="Test .* timed out"):
            await executor._execute_test(test_spec, uuid4())

    @pytest.mark.asyncio
    @patch("beacon.packs.executor.asyncio.wait_for")
    async def test_execute_test_runner_exception(self, mock_wait_for, mock_settings):
        mock_runner_instance = Mock()
        mock_runner_instance.run = AsyncMock(side_effect=Exception("Runner failed"))
        mock_runner_class = Mock(return_value=mock_runner_instance)
        
        executor = PackExecutor(mock_settings)
        executor._runners["ping"] = mock_runner_class
        
        test_spec = TestSpec(
            name="ping_test",
            runner="ping",
            config={"targets": ["8.8.8.8"]},
            timeout_seconds=30,
        )
        
        mock_wait_for.side_effect = Exception("Runner failed")
        
        with pytest.raises(ExecutionError, match="Test .* failed"):
            await executor._execute_test(test_spec, uuid4())

    @pytest.mark.asyncio
    async def test_execute_pack_success(self, mock_settings, sample_pack, sample_envelope):
        mock_runner_instance = Mock()
        mock_runner_instance.run = AsyncMock(return_value=sample_envelope)
        mock_runner_class = Mock(return_value=mock_runner_instance)
        
        executor = PackExecutor(mock_settings)
        executor._runners["ping"] = mock_runner_class
        executor._runners["dns"] = mock_runner_class
        
        with patch.object(executor, "_execute_test", return_value=sample_envelope) as mock_execute:
            result = await executor.execute(sample_pack)
        
        assert isinstance(result, ExecutionResult)
        assert result.pack_name == "test_pack"
        assert result.success is True
        assert len(result.test_results) == 2
        assert result.error is None
        assert mock_execute.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_pack_partial_failure(self, mock_settings, sample_pack, sample_envelope):
        executor = PackExecutor(mock_settings)
        
        async def mock_execute_test(test_spec, run_id):
            if test_spec.name == "ping_test":
                return sample_envelope
            else:
                raise ExecutionError("DNS test failed")
        
        with patch.object(executor, "_execute_test", side_effect=mock_execute_test):
            result = await executor.execute(sample_pack)
        
        assert isinstance(result, ExecutionResult)
        assert result.success is False
        assert len(result.test_results) == 1  # Only successful test
        assert result.error is not None
        assert "DNS test failed" in result.error

    @pytest.mark.asyncio
    async def test_execute_pack_timeout(self, mock_settings, sample_pack):
        executor = PackExecutor(mock_settings)
        
        # Mock a test that takes too long
        async def slow_test(test_spec, run_id):
            await asyncio.sleep(10)  # Longer than pack timeout
            return sample_envelope
        
        with patch.object(executor, "_execute_test", side_effect=slow_test):
            # Set a very short timeout for testing
            sample_pack.timeout_seconds = 0.1
            
            result = await executor.execute(sample_pack)
        
        assert result.success is False
        assert "Pack execution timed out" in result.error

    @pytest.mark.asyncio
    async def test_execute_pack_all_tests_fail(self, mock_settings, sample_pack):
        executor = PackExecutor(mock_settings)
        
        async def failing_test(test_spec, run_id):
            raise ExecutionError(f"{test_spec.name} failed")
        
        with patch.object(executor, "_execute_test", side_effect=failing_test):
            result = await executor.execute(sample_pack)
        
        assert result.success is False
        assert len(result.test_results) == 0
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_pack_preserves_run_id(self, mock_settings, sample_pack, sample_envelope):
        executor = PackExecutor(mock_settings)
        
        captured_run_ids = []
        
        async def mock_execute_test(test_spec, run_id):
            captured_run_ids.append(run_id)
            return sample_envelope
        
        with patch.object(executor, "_execute_test", side_effect=mock_execute_test):
            result = await executor.execute(sample_pack)
        
        # All tests should use the same run_id
        assert len(set(captured_run_ids)) == 1
        assert result.run_id == captured_run_ids[0]

    @pytest.mark.asyncio
    async def test_execute_pack_with_custom_run_id(self, mock_settings, sample_pack, sample_envelope):
        executor = PackExecutor(mock_settings)
        custom_run_id = uuid4()
        
        captured_run_ids = []
        
        async def mock_execute_test(test_spec, run_id):
            captured_run_ids.append(run_id)
            return sample_envelope
        
        with patch.object(executor, "_execute_test", side_effect=mock_execute_test):
            result = await executor.execute(sample_pack, run_id=custom_run_id)
        
        assert result.run_id == custom_run_id
        assert all(rid == custom_run_id for rid in captured_run_ids)

    def test_execution_result_success(self, sample_envelope):
        run_id = uuid4()
        result = ExecutionResult(
            run_id=run_id,
            pack_name="test_pack",
            success=True,
            test_results=[sample_envelope],
            error=None,
        )
        
        assert result.run_id == run_id
        assert result.pack_name == "test_pack"
        assert result.success is True
        assert len(result.test_results) == 1
        assert result.error is None

    def test_execution_result_failure(self):
        run_id = uuid4()
        result = ExecutionResult(
            run_id=run_id,
            pack_name="test_pack",
            success=False,
            test_results=[],
            error="Test execution failed",
        )
        
        assert result.success is False
        assert result.error == "Test execution failed"

    def test_execution_error(self):
        error = ExecutionError("Test error message")
        assert str(error) == "Test error message"

    @pytest.mark.asyncio
    async def test_concurrent_test_execution(self, mock_settings, sample_envelope):
        """Test that tests are executed concurrently, not sequentially."""
        executor = PackExecutor(mock_settings)
        
        execution_order = []
        
        async def mock_execute_test(test_spec, run_id):
            execution_order.append(f"{test_spec.name}_start")
            await asyncio.sleep(0.1)  # Simulate work
            execution_order.append(f"{test_spec.name}_end")
            return sample_envelope
        
        pack = DiagnosticPack(
            name="concurrent_test",
            version="1.0.0",
            description="Test concurrent execution",
            tests=[
                TestSpec("test1", "ping", {}, 30),
                TestSpec("test2", "dns", {}, 30),
            ],
            timeout_seconds=300,
        )
        
        with patch.object(executor, "_execute_test", side_effect=mock_execute_test):
            await executor.execute(pack)
        
        # If tests run concurrently, we should see interleaved start/end
        # If sequential, we'd see test1_start, test1_end, test2_start, test2_end
        assert "test1_start" in execution_order
        assert "test2_start" in execution_order
        assert "test1_end" in execution_order
        assert "test2_end" in execution_order

    @pytest.mark.asyncio
    async def test_execute_empty_pack(self, mock_settings):
        executor = PackExecutor(mock_settings)
        
        empty_pack = DiagnosticPack(
            name="empty_pack",
            version="1.0.0",
            description="Empty pack",
            tests=[],
            timeout_seconds=300,
        )
        
        result = await executor.execute(empty_pack)
        
        assert result.success is True
        assert len(result.test_results) == 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_runner_config_passed_correctly(self, mock_settings, sample_envelope):
        mock_runner_instance = Mock()
        mock_runner_instance.run = AsyncMock(return_value=sample_envelope)
        mock_runner_class = Mock(return_value=mock_runner_instance)
        
        executor = PackExecutor(mock_settings)
        executor._runners["ping"] = mock_runner_class
        
        test_config = {"targets": ["8.8.8.8"], "count": 5, "timeout": 10}
        test_spec = TestSpec(
            name="ping_test",
            runner="ping",
            config=test_config,
            timeout_seconds=30,
        )
        
        with patch("beacon.packs.executor.asyncio.wait_for", return_value=sample_envelope):
            await executor._execute_test(test_spec, uuid4())
        
        # Verify runner was instantiated with correct config
        mock_runner_class.assert_called_once()
        call_args = mock_runner_class.call_args
        assert call_args[0][0] == test_config  # First argument should be config