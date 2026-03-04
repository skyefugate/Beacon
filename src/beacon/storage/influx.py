"""InfluxDB 2.x client wrapper for metric storage.

Provides a thin wrapper around the influxdb-client library with
synchronous writes (sufficient for MVP-0 throughput). The async
client dependency is installed for future migration.
"""

from __future__ import annotations

import logging
from typing import Any

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from beacon.config import BeaconSettings
from beacon.models.envelope import Metric

logger = logging.getLogger(__name__)


class InfluxStorage:
    """Synchronous InfluxDB 2.x client wrapper."""

    def __init__(self, settings: BeaconSettings) -> None:
        self._settings = settings
        self._client = InfluxDBClient(
            url=settings.influxdb.url,
            token=settings.influxdb.token,
            org=settings.influxdb.org,
        )
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self._query_api = self._client.query_api()
        self._bucket = settings.influxdb.bucket
        self._org = settings.influxdb.org

    def write_metric(self, metric: Metric, run_id: str | None = None) -> None:
        """Write a single Metric to InfluxDB."""
        point = self._metric_to_point(metric, run_id)
        self._write_api.write(bucket=self._bucket, org=self._org, record=point)

    def write_metrics(self, metrics: list[Metric], run_id: str | None = None) -> None:
        """Write a batch of Metrics to InfluxDB."""
        points = [self._metric_to_point(m, run_id) for m in metrics]
        if points:
            self._write_api.write(bucket=self._bucket, org=self._org, record=points)

    def query(self, flux_query: str) -> list[dict[str, Any]]:
        """Execute a Flux query and return results as dicts."""
        tables = self._query_api.query(flux_query, org=self._org)
        results: list[dict[str, Any]] = []
        for table in tables:
            for record in table.records:
                results.append(record.values)
        return results

    def health_check(self) -> bool:
        """Check if InfluxDB is reachable."""
        try:
            health = self._client.health()
            return health.status == "pass"
        except Exception:
            logger.warning("InfluxDB health check failed", exc_info=True)
            return False

    def close(self) -> None:
        """Close the client connection."""
        self._client.close()

    @staticmethod
    def _metric_to_point(metric: Metric, run_id: str | None = None) -> Point:
        """Convert a Beacon Metric to an InfluxDB Point."""
        point = Point(metric.measurement)
        for key, value in metric.tags.items():
            point = point.tag(key, str(value))  # type: ignore[assignment]
        if run_id:
            point = point.tag("run_id", run_id)  # type: ignore[assignment]
        for key, value in metric.fields.items():
            point = point.field(key, value)  # type: ignore[assignment]
        point = point.time(metric.timestamp, WritePrecision.MS)  # type: ignore[assignment]
        return point

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
