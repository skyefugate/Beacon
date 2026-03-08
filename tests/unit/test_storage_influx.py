"""Unit tests for InfluxDB storage wrapper."""

from __future__ import annotations

from unittest.mock import Mock, patch
import pytest
from datetime import datetime, timezone

from beacon.storage.influx import InfluxStorage
from beacon.models.envelope import Metric
from beacon.config import BeaconSettings, InfluxDBSettings


@pytest.fixture
def mock_settings():
    return BeaconSettings(
        influxdb=InfluxDBSettings(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
            bucket="test-bucket",
        )
    )


@pytest.fixture
def mock_metric():
    return Metric(
        measurement="ping",
        fields={"rtt_ms": 12.5, "loss_pct": 0.0},
        tags={"target": "8.8.8.8"},
        timestamp=datetime.now(timezone.utc),
    )


class TestInfluxStorage:
    @patch("beacon.storage.influx.InfluxDBClient")
    def test_init(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_write_api = Mock()
        mock_query_api = Mock()
        mock_client.write_api.return_value = mock_write_api
        mock_client.query_api.return_value = mock_query_api
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)

        mock_client_class.assert_called_once_with(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
        )
        assert storage._client == mock_client
        assert storage._write_api == mock_write_api
        assert storage._query_api == mock_query_api
        assert storage._bucket == "test-bucket"
        assert storage._org == "test-org"

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_write_metric(self, mock_client_class, mock_settings, mock_metric):
        mock_client = Mock()
        mock_write_api = Mock()
        mock_client.write_api.return_value = mock_write_api
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        storage.write_metric(mock_metric)

        mock_write_api.write.assert_called_once()
        args = mock_write_api.write.call_args
        assert args[1]["bucket"] == "test-bucket"
        assert args[1]["org"] == "test-org"

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_write_metric_with_run_id(self, mock_client_class, mock_settings, mock_metric):
        mock_client = Mock()
        mock_write_api = Mock()
        mock_client.write_api.return_value = mock_write_api
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        storage.write_metric(mock_metric, "test-run-id")

        mock_write_api.write.assert_called_once()

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_write_metrics_empty_list(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_write_api = Mock()
        mock_client.write_api.return_value = mock_write_api
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        storage.write_metrics([])

        mock_write_api.write.assert_not_called()

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_write_metrics_batch(self, mock_client_class, mock_settings, mock_metric):
        mock_client = Mock()
        mock_write_api = Mock()
        mock_client.write_api.return_value = mock_write_api
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        metrics = [mock_metric, mock_metric]
        storage.write_metrics(metrics)

        mock_write_api.write.assert_called_once()
        args = mock_write_api.write.call_args
        assert len(args[1]["record"]) == 2

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_query(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_query_api = Mock()
        mock_client.query_api.return_value = mock_query_api
        mock_client_class.return_value = mock_client

        mock_record = Mock()
        mock_record.values = {"_time": "2023-01-01", "_value": 12.5}
        mock_table = Mock()
        mock_table.records = [mock_record]
        mock_query_api.query.return_value = [mock_table]

        storage = InfluxStorage(mock_settings)
        result = storage.query("from(bucket: \"test\")")

        assert len(result) == 1
        assert result[0] == {"_time": "2023-01-01", "_value": 12.5}
        mock_query_api.query.assert_called_once_with("from(bucket: \"test\")", org="test-org")

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_health_check_success(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        assert storage.health_check() is True

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_health_check_failure(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_client.ping.side_effect = Exception("Connection failed")
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        assert storage.health_check() is False

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_close(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        storage.close()

        mock_client.close.assert_called_once()

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_context_manager(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        with InfluxStorage(mock_settings) as storage:
            assert storage is not None

        mock_client.close.assert_called_once()

    def test_metric_to_point(self, mock_metric):
        point = InfluxStorage._metric_to_point(mock_metric)
        assert point is not None

    def test_metric_to_point_with_run_id(self, mock_metric):
        point = InfluxStorage._metric_to_point(mock_metric, "test-run-id")
        assert point is not None

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_write_api_exception_handling(self, mock_client_class, mock_settings, mock_metric):
        mock_client = Mock()
        mock_write_api = Mock()
        mock_write_api.write.side_effect = Exception("Write failed")
        mock_client.write_api.return_value = mock_write_api
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        
        with pytest.raises(Exception, match="Write failed"):
            storage.write_metric(mock_metric)

    @patch("beacon.storage.influx.InfluxDBClient")
    def test_query_exception_handling(self, mock_client_class, mock_settings):
        mock_client = Mock()
        mock_query_api = Mock()
        mock_query_api.query.side_effect = Exception("Query failed")
        mock_client.query_api.return_value = mock_query_api
        mock_client_class.return_value = mock_client

        storage = InfluxStorage(mock_settings)
        
        with pytest.raises(Exception, match="Query failed"):
            storage.query("invalid query")