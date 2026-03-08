"""Unit tests for telemetry scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch
import pytest

from beacon.telemetry.scheduler import TelemetryScheduler, _SLEEP_WAKE_GAP_MULTIPLIER
from beacon.telemetry.sampler import BaseSampler
from beacon.telemetry.buffer import SQLiteBuffer
from beacon.telemetry.export.base import BaseExporter
from beacon.telemetry.aggregator import WindowAggregator
from beacon.telemetry.escalation import EscalationAction
from beacon.models.envelope import Metric
from beacon.config import BeaconSettings, TelemetrySettings


@pytest.fixture
def mock_settings():
    return BeaconSettings(
        telemetry=TelemetrySettings(
            window_seconds=60,
            export_flush_interval=30,
            escalation_pack="quick_health",
        )
    )


@pytest.fixture
def mock_sampler():
    sampler = Mock(spec=BaseSampler)
    sampler.name = "test_sampler"
    sampler.default_interval = 30
    sampler.sample = AsyncMock(return_value=[
        Metric(
            measurement="test",
            fields={"value": 1.0},
            tags={"source": "test"},
            timestamp=datetime.now(timezone.utc),
        )
    ])
    return sampler


@pytest.fixture
def mock_buffer():
    buffer = Mock(spec=SQLiteBuffer)
    buffer.open = Mock()
    buffer.close = Mock()
    buffer.write_points = AsyncMock()
    return buffer


@pytest.fixture
def mock_exporter():
    exporter = Mock(spec=BaseExporter)
    exporter.name = "test_exporter"
    exporter.export = AsyncMock()
    exporter.close = AsyncMock()
    exporter.flush_buffer = AsyncMock()
    return exporter


class TestTelemetryScheduler:
    def test_init(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(
            mock_settings,
            [mock_sampler],
            mock_buffer,
        )
        
        assert scheduler._settings == mock_settings
        assert scheduler._samplers == [mock_sampler]
        assert scheduler._buffer == mock_buffer
        assert scheduler._exporters == []
        assert isinstance(scheduler._aggregator, WindowAggregator)
        assert scheduler._tasks == []
        assert scheduler._running is False
        assert scheduler._interval_overrides == {}

    def test_init_with_exporters(self, mock_settings, mock_sampler, mock_buffer, mock_exporter):
        scheduler = TelemetryScheduler(
            mock_settings,
            [mock_sampler],
            mock_buffer,
            [mock_exporter],
        )
        
        assert scheduler._exporters == [mock_exporter]

    def test_running_property(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        assert scheduler.running is False
        scheduler._running = True
        assert scheduler.running is True

    def test_aggregator_property(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        assert isinstance(scheduler.aggregator, WindowAggregator)

    @pytest.mark.asyncio
    async def test_start(self, mock_settings, mock_sampler, mock_buffer, mock_exporter):
        scheduler = TelemetryScheduler(
            mock_settings,
            [mock_sampler],
            mock_buffer,
            [mock_exporter],
        )
        
        with patch("asyncio.create_task") as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await scheduler.start()
        
        assert scheduler._running is True
        mock_buffer.open.assert_called_once()
        assert mock_create_task.call_count == 3  # sampler, aggregation, export
        assert len(scheduler._tasks) == 3

    @pytest.mark.asyncio
    async def test_start_already_running(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        with patch("asyncio.create_task") as mock_create_task:
            await scheduler.start()
        
        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_no_exporters(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        with patch("asyncio.create_task") as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            await scheduler.start()
        
        # Should create sampler and aggregation tasks, but no export task
        assert mock_create_task.call_count == 2

    @pytest.mark.asyncio
    async def test_stop(self, mock_settings, mock_sampler, mock_buffer, mock_exporter):
        scheduler = TelemetryScheduler(
            mock_settings,
            [mock_sampler],
            mock_buffer,
            [mock_exporter],
        )
        
        # Mock tasks
        mock_task1 = Mock()
        mock_task2 = Mock()
        scheduler._tasks = [mock_task1, mock_task2]
        scheduler._running = True
        
        with patch("asyncio.gather") as mock_gather:
            mock_gather.return_value = []
            
            await scheduler.stop()
        
        assert scheduler._running is False
        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()
        mock_gather.assert_called_once()
        assert scheduler._tasks == []
        mock_exporter.close.assert_called_once()
        mock_buffer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_with_final_flush(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        # Mock aggregator with pending windows
        mock_window = Mock()
        scheduler._aggregator.flush = Mock(return_value=[mock_window])
        
        with patch.object(scheduler, "_export_windows") as mock_export:
            with patch("asyncio.gather"):
                await scheduler.stop()
        
        scheduler._aggregator.flush.assert_called_once()
        mock_export.assert_called_once_with([mock_window])

    @pytest.mark.asyncio
    async def test_stop_flush_exception(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        scheduler._aggregator.flush = Mock(side_effect=Exception("Flush error"))
        
        with patch("asyncio.gather"):
            # Should not raise exception
            await scheduler.stop()

    def test_set_interval(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        scheduler.set_interval("test_sampler", 60)
        
        assert scheduler._interval_overrides["test_sampler"] == 60

    def test_clear_interval_override(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._interval_overrides["test_sampler"] = 60
        
        scheduler.clear_interval_override("test_sampler")
        
        assert "test_sampler" not in scheduler._interval_overrides

    def test_clear_interval_override_nonexistent(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        # Should not raise exception
        scheduler.clear_interval_override("nonexistent")

    def test_add_sampler(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [], mock_buffer)
        
        scheduler.add_sampler(mock_sampler)
        
        assert mock_sampler in scheduler._samplers

    def test_add_sampler_while_running(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [], mock_buffer)
        scheduler._running = True
        
        with patch("asyncio.create_task") as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task
            
            scheduler.add_sampler(mock_sampler)
        
        assert mock_sampler in scheduler._samplers
        mock_create_task.assert_called_once()
        assert mock_task in scheduler._tasks

    def test_remove_sampler(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        scheduler.remove_sampler("test_sampler")
        
        assert mock_sampler not in scheduler._samplers

    def test_remove_sampler_nonexistent(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        scheduler.remove_sampler("nonexistent")
        
        # Original sampler should still be there
        assert mock_sampler in scheduler._samplers

    @pytest.mark.asyncio
    async def test_apply_actions_trigger_pack(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        with patch.object(scheduler, "_trigger_pack"):
            with patch("asyncio.create_task") as mock_create_task:
                scheduler.apply_actions([EscalationAction.TRIGGER_PACK])
        
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_pack_success(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        mock_pack = Mock()
        mock_executor = Mock()
        
        with patch("beacon.packs.loader.PackLoader") as mock_loader:
            with patch("beacon.packs.executor.PackExecutor") as mock_executor_class:
                with patch("beacon.packs.registry.PluginRegistry"):
                    with patch("asyncio.get_event_loop") as mock_loop:
                        mock_loop.return_value.run_in_executor = AsyncMock()
                        mock_loader.load_file.return_value = mock_pack
                        mock_executor_class.return_value = mock_executor
                        
                        await scheduler._trigger_pack()

    @pytest.mark.asyncio
    async def test_trigger_pack_exception(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        with patch("beacon.packs.loader.PackLoader") as mock_loader:
            mock_loader.load_file.side_effect = Exception("Pack load failed")
            
            # Should not raise exception
            await scheduler._trigger_pack()

    @pytest.mark.asyncio
    async def test_emit_sleep_wake_gap(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        
        await scheduler._emit_sleep_wake_gap("test_sampler", 120.0, 30.0)
        
        # Should write to buffer
        mock_buffer.write_points.assert_called_once()
        metrics = mock_buffer.write_points.call_args[0][0]
        assert len(metrics) == 1
        assert metrics[0].measurement == "t_system_event"
        assert metrics[0].fields["gap_seconds"] == 120.0
        assert metrics[0].fields["expected_interval"] == 30.0
        assert metrics[0].tags["event_type"] == "sleep_wake_gap"
        assert metrics[0].tags["sampler"] == "test_sampler"

    @pytest.mark.asyncio
    async def test_emit_sleep_wake_gap_exception(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        mock_buffer.write_points.side_effect = Exception("Write failed")
        
        # Should not raise exception
        await scheduler._emit_sleep_wake_gap("test_sampler", 120.0, 30.0)

    @pytest.mark.asyncio
    async def test_sampler_loop_normal_operation(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        # Mock time to avoid sleep/wake detection
        with patch("time.monotonic", side_effect=[100.0, 130.0, 160.0]):
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
                await scheduler._sampler_loop(mock_sampler)
        
        # Should have sampled once before cancellation
        mock_sampler.sample.assert_called_once()
        mock_buffer.write_points.assert_called_once()

    @pytest.mark.asyncio
    async def test_sampler_loop_with_interval_override(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        scheduler._interval_overrides["test_sampler"] = 60
        
        with patch("time.monotonic", return_value=100.0):
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError()) as mock_sleep:
                await scheduler._sampler_loop(mock_sampler)
        
        # Should use override interval
        mock_sleep.assert_called_with(60)

    @pytest.mark.asyncio
    async def test_sampler_loop_sleep_wake_detection(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        # Simulate a large gap (sleep/wake)
        gap_seconds = 30 * _SLEEP_WAKE_GAP_MULTIPLIER + 10
        with patch("time.monotonic", side_effect=[100.0, 100.0 + gap_seconds]):
            with patch.object(scheduler, "_emit_sleep_wake_gap") as mock_emit:
                with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
                    await scheduler._sampler_loop(mock_sampler)
        
        mock_emit.assert_called_once_with("test_sampler", gap_seconds, 30.0)

    @pytest.mark.asyncio
    async def test_sampler_loop_sampler_exception(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        mock_sampler.sample.side_effect = Exception("Sampler error")
        
        with patch("time.monotonic", return_value=100.0):
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
                await scheduler._sampler_loop(mock_sampler)
        
        # Should continue despite sampler error
        mock_sampler.sample.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregation_loop(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        mock_window = Mock()
        scheduler._aggregator.flush = Mock(return_value=[mock_window])
        
        with patch.object(scheduler, "_export_windows") as mock_export:
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
                await scheduler._aggregation_loop()
        
        scheduler._aggregator.flush.assert_called_once()
        mock_export.assert_called_once_with([mock_window])

    @pytest.mark.asyncio
    async def test_aggregation_loop_no_windows(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        scheduler._aggregator.flush = Mock(return_value=[])
        
        with patch.object(scheduler, "_export_windows") as mock_export:
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
                await scheduler._aggregation_loop()
        
        mock_export.assert_not_called()

    @pytest.mark.asyncio
    async def test_aggregation_loop_exception(self, mock_settings, mock_sampler, mock_buffer):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer)
        scheduler._running = True
        
        scheduler._aggregator.flush = Mock(side_effect=Exception("Aggregation error"))
        
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
            # Should not raise exception
            await scheduler._aggregation_loop()

    @pytest.mark.asyncio
    async def test_export_loop(self, mock_settings, mock_sampler, mock_buffer, mock_exporter):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer, [mock_exporter])
        scheduler._running = True
        
        with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
            await scheduler._export_loop()
        
        mock_exporter.flush_buffer.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_loop_exporter_exception(self, mock_settings, mock_sampler, mock_buffer, mock_exporter):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer, [mock_exporter])
        scheduler._running = True
        mock_exporter.flush_buffer.side_effect = Exception("Export error")
        
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
            # Should not raise exception
            await scheduler._export_loop()

    @pytest.mark.asyncio
    async def test_export_loop_exporter_without_flush_buffer(self, mock_settings, mock_sampler, mock_buffer):
        # Exporter without flush_buffer method
        exporter = Mock(spec=BaseExporter)
        exporter.name = "simple_exporter"
        # Don't add flush_buffer method
        
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer, [exporter])
        scheduler._running = True
        
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
            # Should not raise exception
            await scheduler._export_loop()

    @pytest.mark.asyncio
    async def test_export_windows(self, mock_settings, mock_sampler, mock_buffer, mock_exporter):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer, [mock_exporter])
        
        # Mock window
        mock_window = Mock()
        mock_window.measurement = "ping"
        mock_window.field_name = "rtt_ms"
        mock_window.p50 = 10.0
        mock_window.p95 = 20.0
        mock_window.p99 = 25.0
        mock_window.min = 5.0
        mock_window.max = 30.0
        mock_window.mean = 12.5
        mock_window.jitter = 2.5
        mock_window.count = 100
        mock_window.tags = {"target": "8.8.8.8"}
        mock_window.window_end = datetime.now(timezone.utc)
        
        await scheduler._export_windows([mock_window])
        
        mock_exporter.export.assert_called_once()
        metrics = mock_exporter.export.call_args[0][0]
        assert len(metrics) == 1
        assert metrics[0].measurement == "ping_agg"
        assert "rtt_ms_p50" in metrics[0].fields
        assert metrics[0].fields["rtt_ms_p50"] == 10.0

    @pytest.mark.asyncio
    async def test_export_windows_exporter_exception(self, mock_settings, mock_sampler, mock_buffer, mock_exporter):
        scheduler = TelemetryScheduler(mock_settings, [mock_sampler], mock_buffer, [mock_exporter])
        mock_exporter.export.side_effect = Exception("Export error")
        
        mock_window = Mock()
        mock_window.measurement = "ping"
        mock_window.field_name = "rtt_ms"
        mock_window.p50 = 10.0
        mock_window.p95 = 20.0
        mock_window.p99 = 25.0
        mock_window.min = 5.0
        mock_window.max = 30.0
        mock_window.mean = 12.5
        mock_window.jitter = 2.5
        mock_window.count = 100
        mock_window.tags = {}
        mock_window.window_end = datetime.now(timezone.utc)
        
        # Should not raise exception
        await scheduler._export_windows([mock_window])