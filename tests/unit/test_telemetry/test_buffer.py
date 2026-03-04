"""Tests for SQLiteBuffer — write, read, compact, size cap."""

from datetime import datetime, timezone

import pytest

from beacon.models.envelope import Metric
from beacon.telemetry.buffer import SQLiteBuffer


def _make_metric(measurement: str = "t_ping", value: float = 10.0) -> Metric:
    return Metric(
        measurement=measurement,
        fields={"rtt_ms": value},
        tags={"target": "8.8.8.8"},
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def buffer(tmp_path):
    buf = SQLiteBuffer(path=tmp_path / "test_telemetry.db")
    buf.open()
    yield buf
    buf.close()


class TestSQLiteBuffer:
    @pytest.mark.asyncio
    async def test_write_and_read(self, buffer):
        metrics = [_make_metric(value=i) for i in range(5)]
        await buffer.write_points(metrics)

        results = await buffer.read_unexported(batch_size=10)
        assert len(results) == 5
        # Each result is (id, Metric)
        for row_id, metric in results:
            assert isinstance(row_id, int)
            assert metric.measurement == "t_ping"

    @pytest.mark.asyncio
    async def test_mark_exported(self, buffer):
        await buffer.write_points([_make_metric()])
        results = await buffer.read_unexported()
        assert len(results) == 1

        await buffer.mark_exported([results[0][0]])

        # Should be empty now
        results2 = await buffer.read_unexported()
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_batch_size_limit(self, buffer):
        metrics = [_make_metric(value=i) for i in range(10)]
        await buffer.write_points(metrics)

        results = await buffer.read_unexported(batch_size=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_compact_removes_old_exported(self, buffer):
        await buffer.write_points([_make_metric()])
        results = await buffer.read_unexported()
        await buffer.mark_exported([results[0][0]])

        # Compact with retention — won't delete recent
        deleted = await buffer.compact()
        # Points created just now won't be old enough to delete
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_check_size(self, buffer):
        size = await buffer.check_size()
        assert isinstance(size, float)
        assert size >= 0.0

    @pytest.mark.asyncio
    async def test_count_unexported(self, buffer):
        assert await buffer.count_unexported() == 0
        await buffer.write_points([_make_metric(), _make_metric()])
        assert await buffer.count_unexported() == 2

    @pytest.mark.asyncio
    async def test_empty_mark_exported(self, buffer):
        # Should not raise
        await buffer.mark_exported([])

    @pytest.mark.asyncio
    async def test_context_manager(self, tmp_path):
        with SQLiteBuffer(path=tmp_path / "ctx.db") as buf:
            buf._write_points_sync([_make_metric()])
            count = buf._count_unexported_sync()
            assert count == 1
