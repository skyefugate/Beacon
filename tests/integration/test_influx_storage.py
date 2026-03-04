"""Integration tests for InfluxDB storage.

These tests are skipped unless a running InfluxDB instance is available.
Run with: INFLUXDB_URL=http://localhost:8086 pytest tests/integration/test_influx_storage.py
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from beacon.config import BeaconSettings, InfluxDBSettings
from beacon.models.envelope import Metric
from beacon.storage.influx import InfluxStorage


@pytest.fixture
def influx_settings():
    url = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
    return BeaconSettings(influxdb=InfluxDBSettings(url=url))


@pytest.fixture
def influx(influx_settings):
    storage = InfluxStorage(influx_settings)
    if not storage.health_check():
        pytest.skip("InfluxDB not available")
    yield storage
    storage.close()


class TestInfluxStorage:
    def test_health_check(self, influx):
        assert influx.health_check() is True

    def test_write_and_query(self, influx):
        metric = Metric(
            measurement="test_beacon",
            fields={"value": 42.0},
            tags={"source": "integration_test"},
            timestamp=datetime.now(timezone.utc),
        )
        influx.write_metric(metric, run_id="test-run")

        # Query it back
        query = """
        from(bucket: "beacon")
            |> range(start: -1h)
            |> filter(fn: (r) => r._measurement == "test_beacon")
            |> filter(fn: (r) => r.source == "integration_test")
            |> last()
        """
        results = influx.query(query)
        assert len(results) >= 1

    def test_write_batch(self, influx):
        metrics = [
            Metric(
                measurement="test_batch",
                fields={"value": float(i)},
                tags={"index": str(i)},
                timestamp=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]
        influx.write_metrics(metrics, run_id="batch-test")
        # No assertion — just verify no exception
