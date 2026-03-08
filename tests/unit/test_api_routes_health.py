"""Tests for health API routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from beacon import __version__
from beacon.api.app import create_app


class TestHealthRoutes:
    """Test health API routes."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_app()
        return TestClient(app)

    def test_health_endpoint(self, client):
        """Test health endpoint returns OK status."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == __version__

    def test_health_endpoint_structure(self, client):
        """Test health endpoint response structure."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data
        assert "version" in data
        assert len(data) == 2  # Only status and version

    def test_ready_endpoint_all_services_ok(self, client):
        """Test ready endpoint when all services are healthy."""
        mock_influx = MagicMock()
        mock_influx.close.return_value = None
        
        with patch("beacon.api.deps.get_influx_storage", return_value=mock_influx):
            response = client.get("/ready")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["checks"]["influxdb"] == "ok"
            mock_influx.close.assert_called_once()

    def test_ready_endpoint_influx_unavailable(self, client):
        """Test ready endpoint when InfluxDB is unavailable."""
        with patch("beacon.api.deps.get_influx_storage", return_value=None):
            response = client.get("/ready")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["checks"]["influxdb"] == "unavailable"

    def test_ready_endpoint_structure(self, client):
        """Test ready endpoint response structure."""
        with patch("beacon.api.deps.get_influx_storage", return_value=None):
            response = client.get("/ready")
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, dict)
            assert "status" in data
            assert "checks" in data
            assert isinstance(data["checks"], dict)
            assert "influxdb" in data["checks"]

    def test_health_always_available(self, client):
        """Test that health endpoint is always available regardless of dependencies."""
        # Health should work even if other systems are down
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == __version__

    def test_ready_status_logic(self, client):
        """Test ready endpoint status determination logic."""
        # Test with healthy service
        mock_influx = MagicMock()
        with patch("beacon.api.deps.get_influx_storage", return_value=mock_influx):
            response = client.get("/ready")
            data = response.json()
            assert data["status"] == "ready"
        
        # Test with unhealthy service
        with patch("beacon.api.deps.get_influx_storage", return_value=None):
            response = client.get("/ready")
            data = response.json()
            assert data["status"] == "degraded"

    def test_multiple_health_calls(self, client):
        """Test multiple calls to health endpoint."""
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["version"] == __version__

    def test_multiple_ready_calls(self, client):
        """Test multiple calls to ready endpoint."""
        mock_influx = MagicMock()
        
        with patch("beacon.api.deps.get_influx_storage", return_value=mock_influx):
            for _ in range(3):
                response = client.get("/ready")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ready"
                assert data["checks"]["influxdb"] == "ok"
        
        # Verify close was called for each request
        assert mock_influx.close.call_count == 3

    def test_concurrent_health_requests(self, client):
        """Test concurrent health requests don't interfere."""
        import threading
        
        results = []
        
        def make_request():
            response = client.get("/health")
            results.append(response.status_code)
        
        threads = [threading.Thread(target=make_request) for _ in range(10)]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        assert all(status == 200 for status in results)
        assert len(results) == 10