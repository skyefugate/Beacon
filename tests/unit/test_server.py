"""Unit tests for collectors/server.py FastAPI application."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from beacon.collectors.server import app, CollectRequest


class TestCollectorServer:
    def setup_method(self):
        self.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["role"] == "collector"
        assert "version" in data

    def test_collect_device_collector(self):
        with patch("beacon.collectors.server.DeviceCollector") as mock_collector_class:
            mock_collector = MagicMock()
            mock_envelope = MagicMock()
            mock_envelope.model_dump.return_value = {"test": "data"}
            mock_collector.collect.return_value = mock_envelope
            mock_collector_class.return_value = mock_collector

            run_id = str(uuid4())
            response = self.client.post("/collect/device", json={"run_id": run_id, "config": {}})

            assert response.status_code == 200
            assert response.json() == {"test": "data"}
            mock_collector.collect.assert_called_once()

    def test_collect_ping_runner(self):
        with (
            patch("beacon.collectors.server.PingRunner") as mock_runner_class,
            patch("beacon.collectors.server.RunnerConfig") as mock_config_class,
        ):
            mock_runner = MagicMock()
            mock_envelope = MagicMock()
            mock_envelope.model_dump.return_value = {"runner": "result"}
            mock_runner.run.return_value = mock_envelope
            mock_runner_class.return_value = mock_runner
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config

            run_id = str(uuid4())
            config = {"target": "8.8.8.8"}
            response = self.client.post("/collect/ping", json={"run_id": run_id, "config": config})

            assert response.status_code == 200
            assert response.json() == {"runner": "result"}
            mock_config_class.assert_called_once_with(**config)
            mock_runner.run.assert_called_once()

    def test_collect_runner_no_config(self):
        with (
            patch("beacon.collectors.server.TracerouteRunner") as mock_runner_class,
            patch("beacon.collectors.server.RunnerConfig") as mock_config_class,
        ):
            mock_runner = MagicMock()
            mock_envelope = MagicMock()
            mock_envelope.model_dump.return_value = {"trace": "data"}
            mock_runner.run.return_value = mock_envelope
            mock_runner_class.return_value = mock_runner
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config

            run_id = str(uuid4())
            response = self.client.post("/collect/traceroute", json={"run_id": run_id})

            assert response.status_code == 200
            mock_config_class.assert_called_once_with()

    def test_collect_unknown_plugin(self):
        run_id = str(uuid4())
        response = self.client.post("/collect/unknown", json={"run_id": run_id})

        assert response.status_code == 404
        assert "Unknown plugin: unknown" in response.json()["detail"]

    def test_collect_request_model(self):
        # Test with config
        request = CollectRequest(run_id="test-id", config={"key": "value"})
        assert request.run_id == "test-id"
        assert request.config == {"key": "value"}

        # Test without config (default)
        request = CollectRequest(run_id="test-id")
        assert request.config == {}
