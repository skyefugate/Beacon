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
