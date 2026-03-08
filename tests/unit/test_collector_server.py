"""Tests for collector server.py FastAPI application."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from beacon.collectors.server import app


class TestCollectorServer:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert data["role"] == "collector"

    def test_collect_unknown_plugin(self, client):
        run_id = str(uuid4())
        response = client.post(
            "/collect/unknown_plugin",
            json={"run_id": run_id, "config": {}}
        )

        assert response.status_code == 404
        assert "Unknown plugin" in response.json()["detail"]

    @patch("beacon.collectors.server._COLLECTORS")
    @patch("beacon.collectors.server._RUNNERS")
    def test_collect_device_success(self, mock_runners, mock_collectors, client):
        # Mock the collector
        mock_collector_instance = MagicMock()
        mock_envelope = MagicMock()
        mock_envelope.model_dump.return_value = {"plugin_name": "device", "metrics": []}
        mock_collector_instance.collect.return_value = mock_envelope
        
        mock_collector_class = MagicMock(return_value=mock_collector_instance)
        mock_collectors.__getitem__.return_value = mock_collector_class
        mock_collectors.__contains__.return_value = True
        mock_runners.__contains__.return_value = False

        run_id = str(uuid4())
        response = client.post(
            "/collect/device",
            json={"run_id": run_id, "config": {}}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["plugin_name"] == "device"

    @patch("beacon.collectors.server._COLLECTORS")
    @patch("beacon.collectors.server._RUNNERS")
    def test_collect_runner_success(self, mock_runners, mock_collectors, client):
        # Mock the runner
        mock_runner_instance = MagicMock()
        mock_envelope = MagicMock()
        mock_envelope.model_dump.return_value = {"plugin_name": "ping", "metrics": []}
        mock_runner_instance.run.return_value = mock_envelope
        
        mock_runner_class = MagicMock(return_value=mock_runner_instance)
        mock_collectors.__contains__.return_value = False
        mock_runners.__contains__.return_value = True
        mock_runners.__getitem__.return_value = mock_runner_class

        run_id = str(uuid4())
        response = client.post(
            "/collect/ping",
            json={"run_id": run_id, "config": {"target": "8.8.8.8"}}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["plugin_name"] == "ping"

    @patch("beacon.collectors.server._COLLECTORS")
    @patch("beacon.collectors.server._RUNNERS")
    def test_collect_runner_empty_config(self, mock_runners, mock_collectors, client):
        # Mock the runner
        mock_runner_instance = MagicMock()
        mock_envelope = MagicMock()
        mock_envelope.model_dump.return_value = {"plugin_name": "ping", "metrics": []}
        mock_runner_instance.run.return_value = mock_envelope
        
        mock_runner_class = MagicMock(return_value=mock_runner_instance)
        mock_collectors.__contains__.return_value = False
        mock_runners.__contains__.return_value = True
        mock_runners.__getitem__.return_value = mock_runner_class

        run_id = str(uuid4())
        response = client.post(
            "/collect/ping",
            json={"run_id": run_id, "config": {}}
        )

        assert response.status_code == 200

    @patch("beacon.collectors.server._COLLECTORS")
    @patch("beacon.collectors.server._RUNNERS")
    def test_collect_runner_no_config(self, mock_runners, mock_collectors, client):
        # Mock the runner
        mock_runner_instance = MagicMock()
        mock_envelope = MagicMock()
        mock_envelope.model_dump.return_value = {"plugin_name": "ping", "metrics": []}
        mock_runner_instance.run.return_value = mock_envelope
        
        mock_runner_class = MagicMock(return_value=mock_runner_instance)
        mock_collectors.__contains__.return_value = False
        mock_runners.__contains__.return_value = True
        mock_runners.__getitem__.return_value = mock_runner_class

        run_id = str(uuid4())
        response = client.post(
            "/collect/ping",
            json={"run_id": run_id}
        )

        assert response.status_code == 200