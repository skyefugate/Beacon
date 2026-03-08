"""Tests for metrics API routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from beacon.api.app import create_app


class TestMetricsRoutes:
    """Test metrics API routes."""

    @pytest.fixture
    def mock_influx_storage(self):
        """Mock InfluxDB storage."""
        storage = MagicMock()
        storage.query.return_value = []
        storage.close.return_value = None
        return storage

    @pytest.fixture
    def client(self, mock_influx_storage):
        """Create test client with mocked InfluxDB."""
        app = create_app()
        with patch(
            "beacon.api.routes.metrics.get_influx_storage", return_value=mock_influx_storage
        ):
            yield TestClient(app)

    def test_query_metrics_success(self, client, mock_influx_storage):
        """Test successful metrics query."""
        mock_results = [
            {"_measurement": "cpu", "_field": "usage", "_value": 50.0},
            {"_measurement": "memory", "_field": "usage", "_value": 75.0},
        ]
        mock_influx_storage.query.return_value = mock_results

        response = client.post("/metrics/query", json={"query": 'from(bucket: "test")'})

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert data["results"] == mock_results
        mock_influx_storage.query.assert_called_once_with('from(bucket: "test")')
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_empty_results(self, client, mock_influx_storage):
        """Test metrics query with empty results."""
        mock_influx_storage.query.return_value = []

        response = client.post("/metrics/query", json={"query": 'from(bucket: "empty")'})

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        mock_influx_storage.query.assert_called_once_with('from(bucket: "empty")')
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_influx_unavailable(self, client):
        """Test metrics query when InfluxDB is unavailable."""
        with patch("beacon.api.routes.metrics.get_influx_storage", return_value=None):
            response = client.post("/metrics/query", json={"query": 'from(bucket: "test")'})

            assert response.status_code == 503
            assert "InfluxDB is not available" in response.json()["detail"]

    def test_query_metrics_influx_error(self, client, mock_influx_storage):
        """Test metrics query when InfluxDB raises an error."""
        mock_influx_storage.query.side_effect = Exception("Query failed")

        response = client.post("/metrics/query", json={"query": "invalid query"})

        assert response.status_code == 400
        assert "Query failed" in response.json()["detail"]
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_invalid_json(self, client):
        """Test metrics query with invalid JSON payload."""
        response = client.post("/metrics/query", data="invalid json")

        assert response.status_code == 422  # Unprocessable Entity

    def test_query_metrics_missing_query_field(self, client):
        """Test metrics query with missing query field."""
        response = client.post("/metrics/query", json={})

        assert response.status_code == 422  # Validation error

    def test_query_metrics_invalid_query_type(self, client):
        """Test metrics query with invalid query type."""
        response = client.post("/metrics/query", json={"query": 123})

        assert response.status_code == 422  # Validation error

    def test_query_metrics_empty_query(self, client, mock_influx_storage):
        """Test metrics query with empty query string."""
        response = client.post("/metrics/query", json={"query": ""})

        assert response.status_code == 200
        mock_influx_storage.query.assert_called_once_with("")
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_complex_query(self, client, mock_influx_storage):
        """Test metrics query with complex Flux query."""
        complex_query = """
        from(bucket: "beacon_telemetry")
        |> range(start: -1h)
        |> filter(fn: (r) => r._measurement == "cpu")
        |> aggregateWindow(every: 5m, fn: mean)
        """
        mock_results = [{"_time": "2025-01-15T10:00:00Z", "_value": 45.2}]
        mock_influx_storage.query.return_value = mock_results

        response = client.post("/metrics/query", json={"query": complex_query})

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == mock_results
        mock_influx_storage.query.assert_called_once_with(complex_query)
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_close_exception(self, client, mock_influx_storage):
        """Test metrics query when close() raises exception."""
        mock_influx_storage.close.side_effect = Exception("Close failed")

        # The exception in close() should propagate and cause a 500 error
        with pytest.raises(Exception):
            client.post("/metrics/query", json={"query": 'from(bucket: "test")'})

    def test_query_metrics_large_results(self, client, mock_influx_storage):
        """Test metrics query with large result set."""
        large_results = [{"_measurement": f"metric_{i}", "_value": float(i)} for i in range(1000)]
        mock_influx_storage.query.return_value = large_results

        response = client.post("/metrics/query", json={"query": 'from(bucket: "large")'})

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1000
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_special_characters(self, client, mock_influx_storage):
        """Test metrics query with special characters."""
        query_with_special_chars = (
            'from(bucket: "test") |> filter(fn: (r) => r.tag == "special/chars@#$%")'
        )

        response = client.post("/metrics/query", json={"query": query_with_special_chars})

        assert response.status_code == 200
        mock_influx_storage.query.assert_called_once_with(query_with_special_chars)
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_unicode(self, client, mock_influx_storage):
        """Test metrics query with Unicode characters."""
        unicode_query = 'from(bucket: "测试") |> filter(fn: (r) => r.tag == "🚀")'

        response = client.post("/metrics/query", json={"query": unicode_query})

        assert response.status_code == 200
        mock_influx_storage.query.assert_called_once_with(unicode_query)
        mock_influx_storage.close.assert_called_once()

    def test_query_metrics_concurrent_requests(self, client):
        """Test concurrent metrics queries."""
        import threading

        results = []

        def make_query(query_id):
            mock_storage = MagicMock()
            mock_storage.query.return_value = [{"query_id": query_id}]

            with patch("beacon.api.routes.metrics.get_influx_storage", return_value=mock_storage):
                response = client.post("/metrics/query", json={"query": f"query_{query_id}"})
                results.append(response.status_code)

        threads = [threading.Thread(target=make_query, args=(i,)) for i in range(5)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert all(status == 200 for status in results)
        assert len(results) == 5

    def test_flux_query_model_validation(self, client):
        """Test FluxQuery model validation."""
        # Test valid query
        response = client.post("/metrics/query", json={"query": "valid query"})
        assert response.status_code in [200, 503]  # 503 if no InfluxDB mock

        # Test extra fields are ignored
        response = client.post(
            "/metrics/query", json={"query": "valid query", "extra_field": "ignored"}
        )
        assert response.status_code in [200, 503]

        # Test null query
        response = client.post("/metrics/query", json={"query": None})
        assert response.status_code == 422
