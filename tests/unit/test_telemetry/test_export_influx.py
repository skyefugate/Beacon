"""Tests for async InfluxDB exporter with mocked client."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beacon.config import BeaconSettings
from beacon.models.envelope import Metric
from beacon.telemetry.buffer import SQLiteBuffer
from beacon.telemetry.export.influx import InfluxExporter


def _make_metric(value: float = 10.0) -> Metric:
    return Metric(
        measurement="t_ping",
        fields={"rtt_ms": value},
        tags={"target": "8.8.8.8"},
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def settings():
    return BeaconSettings()


@pytest.fixture
def buffer(tmp_path):
    buf = SQLiteBuffer(path=tmp_path / "test.db")
    buf.open()
    yield buf
    buf.close()


class TestInfluxExporter:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.export.influx.InfluxDBClientAsync")
    async def test_export_direct(self, MockClient, settings, buffer):
        mock_client = MagicMock()
        mock_write = MagicMock()
        mock_write.write = AsyncMock()
        mock_client.write_api = MagicMock(return_value=mock_write)
        mock_client.close = AsyncMock()
        MockClient.return_value = mock_client

        exporter = InfluxExporter(settings, buffer)
        exporter._client = mock_client

        count = await exporter.export([_make_metric()])
        assert count == 1
        mock_write.write.assert_called_once()

    @pytest.mark.asyncio
    @patch("beacon.telemetry.export.influx.InfluxDBClientAsync")
    async def test_export_failure_increments_backoff(self, MockClient, settings, buffer):
        mock_client = MagicMock()
        mock_write = MagicMock()
        mock_write.write = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.write_api = MagicMock(return_value=mock_write)
        mock_client.close = AsyncMock()
        MockClient.return_value = mock_client

        exporter = InfluxExporter(settings, buffer)
        exporter._client = mock_client

        count = await exporter.export([_make_metric()])
        assert count == 0
        assert exporter._consecutive_failures == 1

    @pytest.mark.asyncio
    @patch("beacon.telemetry.export.influx.InfluxDBClientAsync")
    async def test_flush_buffer(self, MockClient, settings, buffer):
        # Write some points to buffer
        await buffer.write_points([_make_metric(1.0), _make_metric(2.0)])

        mock_client = MagicMock()
        mock_write = MagicMock()
        mock_write.write = AsyncMock()
        mock_client.write_api = MagicMock(return_value=mock_write)
        mock_client.close = AsyncMock()
        MockClient.return_value = mock_client

        exporter = InfluxExporter(settings, buffer)
        exporter._client = mock_client

        count = await exporter.flush_buffer()
        assert count == 2

        # Buffer should be empty now
        remaining = await buffer.read_unexported()
        assert len(remaining) == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.export.influx.InfluxDBClientAsync")
    async def test_close(self, MockClient, settings, buffer):
        mock_client = AsyncMock()
        MockClient.return_value = mock_client

        exporter = InfluxExporter(settings, buffer)
        exporter._client = mock_client
        await exporter.close()

        mock_client.close.assert_called_once()

    def test_metric_to_point(self):
        metric = _make_metric(42.0)
        point = InfluxExporter._metric_to_point(metric)
        # Verify point was created (basic check)
        line = point.to_line_protocol()
        assert "t_ping" in line
        assert "rtt_ms" in line
