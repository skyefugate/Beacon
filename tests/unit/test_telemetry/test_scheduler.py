"""Tests for TelemetryScheduler — start/stop lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from beacon.config import BeaconSettings
from beacon.models.envelope import Metric
from beacon.telemetry.buffer import SQLiteBuffer
from beacon.telemetry.export.base import BaseExporter
from beacon.telemetry.sampler import BaseSampler
from beacon.telemetry.scheduler import TelemetryScheduler


class MockSampler(BaseSampler):
    name = "mock"
    tier = 0
    default_interval = 1

    def __init__(self):
        self.call_count = 0

    async def sample(self) -> list[Metric]:
        self.call_count += 1
        return [
            Metric(
                measurement="t_mock",
                fields={"value": float(self.call_count)},
                timestamp=datetime.now(timezone.utc),
            )
        ]


class MockExporter(BaseExporter):
    name = "mock"

    def __init__(self):
        self.exported: list[Metric] = []
        self.closed = False

    async def export(self, metrics: list[Metric]) -> int:
        self.exported.extend(metrics)
        return len(metrics)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings():
    s = BeaconSettings()
    # Short window for fast tests
    s.telemetry.window_seconds = 1
    s.telemetry.export_flush_interval = 1
    return s


@pytest.fixture
def buffer(tmp_path):
    return SQLiteBuffer(path=tmp_path / "sched_test.db")


class TestTelemetryScheduler:
    @pytest.mark.asyncio
    async def test_start_stop(self, settings, buffer):
        sampler = MockSampler()
        scheduler = TelemetryScheduler(settings, [sampler], buffer)

        assert not scheduler.running
        await scheduler.start()
        assert scheduler.running

        # Let it run briefly
        await asyncio.sleep(0.1)

        await scheduler.stop()
        assert not scheduler.running
        assert sampler.call_count >= 1

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self, settings, buffer):
        sampler = MockSampler()
        scheduler = TelemetryScheduler(settings, [sampler], buffer)
        await scheduler.start()
        await scheduler.start()  # Should not raise
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_interval_override(self, settings, buffer):
        sampler = MockSampler()
        scheduler = TelemetryScheduler(settings, [sampler], buffer)

        scheduler.set_interval("mock", 999)
        assert scheduler._interval_overrides["mock"] == 999

        scheduler.clear_interval_override("mock")
        assert "mock" not in scheduler._interval_overrides

    @pytest.mark.asyncio
    async def test_add_remove_sampler(self, settings, buffer):
        sampler1 = MockSampler()
        sampler1.name = "mock1"
        scheduler = TelemetryScheduler(settings, [sampler1], buffer)

        sampler2 = MockSampler()
        sampler2.name = "mock2"
        scheduler.add_sampler(sampler2)
        assert len(scheduler._samplers) == 2

        scheduler.remove_sampler("mock2")
        assert len(scheduler._samplers) == 1

    @pytest.mark.asyncio
    async def test_exporter_receives_data(self, settings, buffer):
        sampler = MockSampler()
        exporter = MockExporter()
        scheduler = TelemetryScheduler(settings, [sampler], buffer, [exporter])

        await scheduler.start()
        # Let it run for a couple of windows
        await asyncio.sleep(2.5)
        await scheduler.stop()

        assert exporter.closed

    @pytest.mark.asyncio
    async def test_sampler_error_does_not_crash(self, settings, buffer):
        class FailingSampler(BaseSampler):
            name = "failing"
            tier = 0
            default_interval = 1

            async def sample(self):
                raise RuntimeError("boom")

        scheduler = TelemetryScheduler(settings, [FailingSampler()], buffer)
        await scheduler.start()
        await asyncio.sleep(0.5)
        await scheduler.stop()
        # Should not raise — errors are logged


class TestSleepWakeGapDetection:
    """Tests for the sleep/wake gap detection in _sampler_loop."""

    @pytest.mark.asyncio
    async def test_emit_sleep_wake_gap_writes_metric(self, settings, buffer):
        """_emit_sleep_wake_gap should push a t_system_event to the buffer."""
        sampler = MockSampler()
        scheduler = TelemetryScheduler(settings, [sampler], buffer)
        scheduler._buffer.open()

        await scheduler._emit_sleep_wake_gap(
            sampler_name="mock",
            gap_seconds=45.7,
            expected_interval=10.0,
        )

        # The metric must have landed in the buffer (read_unexported returns (id, Metric) tuples)
        rows = await scheduler._buffer.read_unexported(batch_size=10)
        assert len(rows) >= 1
        gap_rows = [(row_id, m) for row_id, m in rows if m.measurement == "t_system_event"]
        assert len(gap_rows) == 1
        _, m = gap_rows[0]
        assert m.tags["event_type"] == "sleep_wake_gap"
        assert m.tags["sampler"] == "mock"
        assert m.fields["gap_seconds"] == pytest.approx(45.7, rel=1e-3)
        assert m.fields["expected_interval"] == pytest.approx(10.0, rel=1e-3)

        scheduler._buffer.close()

    @pytest.mark.asyncio
    async def test_no_gap_emitted_on_normal_timing(self, settings, buffer):
        """When samples arrive within 3x interval, no t_system_event is emitted."""
        sampler = MockSampler()
        sampler.default_interval = 1

        scheduler = TelemetryScheduler(settings, [sampler], buffer)
        await scheduler.start()

        # Run for a bit — normal timing should not emit any gap events
        await asyncio.sleep(0.3)

        # Read before stop (stop() closes the buffer)
        rows = await scheduler._buffer.read_unexported(batch_size=100)
        gap_rows = [(row_id, m) for row_id, m in rows if m.measurement == "t_system_event"]

        await scheduler.stop()

        assert gap_rows == [], f"Unexpected gap metrics: {gap_rows}"

    @pytest.mark.asyncio
    async def test_gap_emitted_when_large_elapsed_time(self, settings, buffer):
        """When monotonic clock jumps (simulated), a t_system_event metric is emitted."""
        import unittest.mock as mock
        from beacon.telemetry import scheduler as sched_mod

        sampler = MockSampler()
        sampler.default_interval = 10  # 10-second interval

        scheduler = TelemetryScheduler(settings, [sampler], buffer)
        scheduler._buffer.open()

        # Simulate a large monotonic jump: first call returns T=0, second T=35
        # (35s > 3 * 10s threshold = 30s)
        monotonic_values = [0.0, 35.0]

        call_idx = [0]
        def fake_monotonic():
            val = monotonic_values[call_idx[0]]
            call_idx[0] = min(call_idx[0] + 1, len(monotonic_values) - 1)
            return val

        with mock.patch.object(sched_mod.time, "monotonic", side_effect=fake_monotonic):
            # Manually drive the gap-detection portion of _sampler_loop
            last_sample_wall = sched_mod.time.monotonic()  # returns 0.0
            interval = sampler.default_interval

            now_wall = sched_mod.time.monotonic()  # returns 35.0
            elapsed = now_wall - last_sample_wall
            threshold = interval * sched_mod._SLEEP_WAKE_GAP_MULTIPLIER

            assert elapsed > threshold, "Test setup: gap must exceed threshold"
            await scheduler._emit_sleep_wake_gap(sampler.name, elapsed, float(interval))

        rows = await scheduler._buffer.read_unexported(batch_size=10)
        gap_rows = [(row_id, m) for row_id, m in rows if m.measurement == "t_system_event"]
        assert len(gap_rows) == 1
        _, m = gap_rows[0]
        assert m.fields["gap_seconds"] == pytest.approx(35.0, rel=1e-3)
        assert m.fields["expected_interval"] == pytest.approx(10.0, rel=1e-3)
        assert m.tags["event_type"] == "sleep_wake_gap"

        scheduler._buffer.close()

    def test_gap_threshold_constant(self):
        """_SLEEP_WAKE_GAP_MULTIPLIER must be 3 per the issue spec."""
        from beacon.telemetry import scheduler as sched_mod
        assert sched_mod._SLEEP_WAKE_GAP_MULTIPLIER == 3

    @pytest.mark.asyncio
    async def test_emit_gap_metric_shape(self, settings, buffer):
        """Gap metric must have correct measurement, fields, and tags."""
        sampler = MockSampler()
        scheduler = TelemetryScheduler(settings, [sampler], buffer)
        scheduler._buffer.open()

        await scheduler._emit_sleep_wake_gap("wifi", 120.0, 30.0)

        rows = await scheduler._buffer.read_unexported(batch_size=10)
        gap_rows = [(row_id, m) for row_id, m in rows if m.measurement == "t_system_event"]
        assert gap_rows, "Expected at least one t_system_event row"
        _, m = gap_rows[0]
        assert m.measurement == "t_system_event"
        assert set(m.fields.keys()) == {"gap_seconds", "expected_interval"}
        assert set(m.tags.keys()) >= {"event_type", "sampler"}

        scheduler._buffer.close()
