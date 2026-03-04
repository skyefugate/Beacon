"""Async InfluxDB exporter — reads from SQLiteBuffer, batch-writes to InfluxDB.

Uses influxdb_client.client.influxdb_client_async.InfluxDBClientAsync for
non-blocking writes with exponential backoff on failure.
"""

from __future__ import annotations

import asyncio
import logging

from influxdb_client import Point, WritePrecision
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

from beacon.config import BeaconSettings
from beacon.models.envelope import Metric
from beacon.telemetry.buffer import SQLiteBuffer
from beacon.telemetry.export.base import BaseExporter

logger = logging.getLogger(__name__)


class InfluxExporter(BaseExporter):
    """Async InfluxDB exporter with buffer-backed retry and gzip compression."""

    name = "influx"

    def __init__(self, settings: BeaconSettings, buffer: SQLiteBuffer) -> None:
        self._settings = settings
        self._buffer = buffer
        self._bucket = settings.telemetry.export_influx_bucket
        self._org = settings.influxdb.org
        self._batch_size = settings.telemetry.export_batch_size
        self._client: InfluxDBClientAsync | None = None
        self._backoff = 1.0  # exponential backoff seconds
        self._max_backoff = 60.0
        self._consecutive_failures = 0
        # Export metrics
        self.total_exported = 0
        self.total_failures = 0

    async def start(self) -> None:
        """Initialize the async InfluxDB client with gzip enabled."""
        self._client = InfluxDBClientAsync(
            url=self._settings.influxdb.url,
            token=self._settings.influxdb.token,
            org=self._org,
            enable_gzip=True,
        )

    async def export(self, metrics: list[Metric]) -> int:
        """Write metrics directly (bypassing buffer). Used for aggregated windows."""
        if not self._client:
            await self.start()

        points = [self._metric_to_point(m) for m in metrics]
        try:
            write_api = self._client.write_api()
            await write_api.write(bucket=self._bucket, org=self._org, record=points)
            self._consecutive_failures = 0
            self._backoff = 1.0
            self.total_exported += len(points)
            return len(points)
        except Exception as e:
            logger.warning("InfluxDB export failed: %s", e)
            self._consecutive_failures += 1
            self.total_failures += 1
            return 0

    async def flush_buffer(self) -> int:
        """Read unexported points from buffer, write to InfluxDB, mark exported."""
        if not self._client:
            await self.start()

        batch = await self._buffer.read_unexported(self._batch_size)
        if not batch:
            return 0

        ids = [row_id for row_id, _ in batch]
        points = [self._metric_to_point(m) for _, m in batch]

        try:
            write_api = self._client.write_api()
            await write_api.write(bucket=self._bucket, org=self._org, record=points)
            await self._buffer.mark_exported(ids)
            self._consecutive_failures = 0
            self._backoff = 1.0
            self.total_exported += len(points)
            logger.debug("Exported %d points to InfluxDB", len(points))
            return len(points)
        except Exception as e:
            logger.warning(
                "InfluxDB buffer flush failed (attempt %d): %s",
                self._consecutive_failures + 1,
                e,
            )
            self._consecutive_failures += 1
            self.total_failures += 1
            self._backoff = min(self._backoff * 2, self._max_backoff)
            await asyncio.sleep(self._backoff)
            return 0

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    @staticmethod
    def _metric_to_point(metric: Metric) -> Point:
        """Convert a Beacon Metric to an InfluxDB Point."""
        point = Point(metric.measurement)
        for key, value in metric.tags.items():
            point = point.tag(key, value)
        for key, value in metric.fields.items():
            point = point.field(key, value)
        point = point.time(metric.timestamp, WritePrecision.MS)
        return point
