"""Tests for the telemetry dashboard API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from beacon.api.app import create_app
from beacon.config import BeaconSettings


def _make_agg_record(measurement: str, field: str, value: float) -> dict:
    """Create a mock InfluxDB record dict."""
    return {
        "_measurement": measurement,
        "_field": field,
        "_value": value,
        "_time": datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc),
        "result": "_result",
        "table": 0,
    }


@pytest.fixture
def mock_settings():
    settings = BeaconSettings()
    settings.telemetry.export_influx_bucket = "beacon_telemetry"
    return settings


@pytest.fixture
def mock_influx():
    influx = MagicMock()
    influx.health_check.return_value = True
    influx.query.return_value = []
    influx.close.return_value = None
    return influx


@pytest.fixture
def client(mock_settings, mock_influx):
    """Create a test client with mocked dependencies."""
    app = create_app()
    with (
        patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
        patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
    ):
        yield TestClient(app)


@pytest.fixture
def client_no_influx(mock_settings):
    """Test client where InfluxDB is unavailable."""
    app = create_app()
    with (
        patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
        patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=None),
    ):
        yield TestClient(app)


class TestOverviewEndpoint:
    """GET /api/telemetry/overview"""

    def test_overview_returns_bxi_and_metrics(self, mock_influx, mock_settings):
        mock_influx.query.return_value = [
            _make_agg_record("t_internet_rtt_agg", "rtt_avg_ms_p95", 22.3),
            _make_agg_record("t_internet_rtt_agg", "rtt_avg_ms_mean", 19.5),
            _make_agg_record("t_internet_rtt_agg", "loss_pct_mean", 0.0),
            _make_agg_record("t_dns_latency_agg", "latency_ms_p95", 8.2),
            _make_agg_record("t_http_timing_agg", "total_ms_p95", 120.0),
            _make_agg_record("t_device_health_agg", "cpu_percent_mean", 0.3),
            _make_agg_record("t_device_health_agg", "memory_percent_mean", 11.3),
        ]

        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
        ):
            client = TestClient(app)
            resp = client.get("/api/telemetry/overview")

        assert resp.status_code == 200
        data = resp.json()

        # BXI section
        assert "bxi" in data
        assert data["bxi"]["score"] >= 0
        assert data["bxi"]["score"] <= 100
        assert data["bxi"]["label"] in ("Excellent", "Good", "Fair", "Poor", "Critical")
        assert "components" in data["bxi"]

        # Metrics section — uses short names
        assert "internet_rtt" in data["metrics"]
        assert "dns_latency" in data["metrics"]
        assert "http_timing" in data["metrics"]
        assert "device_health" in data["metrics"]

        # Context section
        assert "context" in data

        # Agent section
        assert data["agent"]["probe_id"] == "beacon-01"
        assert data["agent"]["version"] == "0.1.0"

        # Escalation section
        assert data["escalation"]["state"] == "BASELINE"

    def test_overview_empty_data(self, mock_influx, mock_settings):
        """No data → BXI 0 (unmeasurable = all max penalties)."""
        mock_influx.query.return_value = []

        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
        ):
            client = TestClient(app)
            resp = client.get("/api/telemetry/overview")

        assert resp.status_code == 200
        data = resp.json()
        assert data["bxi"]["score"] == 0
        assert data["bxi"]["label"] == "Critical"
        assert "context" in data
        assert data["context"] == {}

    def test_overview_influx_unavailable(self, client_no_influx):
        resp = client_no_influx.get("/api/telemetry/overview")
        assert resp.status_code == 503

    def test_overview_influx_query_fails(self, mock_influx, mock_settings):
        mock_influx.query.side_effect = Exception("connection reset")

        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
        ):
            client = TestClient(app)
            resp = client.get("/api/telemetry/overview")

        assert resp.status_code == 503
        mock_influx.close.assert_called_once()


class TestSeriesEndpoint:
    """GET /api/telemetry/series"""

    def test_series_valid_params(self, mock_influx, mock_settings):
        mock_influx.query.return_value = [
            {
                "_measurement": "t_internet_rtt_agg",
                "_field": "rtt_avg_ms_mean",
                "_value": 19.5,
                "_time": datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
            },
            {
                "_measurement": "t_internet_rtt_agg",
                "_field": "rtt_avg_ms_mean",
                "_value": 21.0,
                "_time": datetime(2025, 1, 15, 14, 1, 0, tzinfo=timezone.utc),
            },
        ]

        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
        ):
            client = TestClient(app)
            resp = client.get(
                "/api/telemetry/series",
                params={"measurement": "internet_rtt", "field": "rtt_avg_ms_mean", "range": "1h"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["measurement"] == "internet_rtt"
        assert data["field"] == "rtt_avg_ms_mean"
        assert data["range"] == "1h"
        assert len(data["points"]) == 2
        assert "time" in data["points"][0]
        assert "value" in data["points"][0]

    def test_series_invalid_measurement(self, client):
        resp = client.get(
            "/api/telemetry/series",
            params={"measurement": "'; DROP TABLE users;--", "field": "rtt_avg_ms_mean"},
        )
        assert resp.status_code == 400

    def test_series_invalid_field(self, client):
        resp = client.get(
            "/api/telemetry/series",
            params={"measurement": "internet_rtt", "field": "evil_injection"},
        )
        assert resp.status_code == 400

    def test_series_invalid_range(self, client):
        resp = client.get(
            "/api/telemetry/series",
            params={"measurement": "internet_rtt", "field": "rtt_avg_ms_mean", "range": "999d"},
        )
        assert resp.status_code == 400

    def test_series_influx_unavailable(self, mock_settings):
        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=None),
        ):
            client = TestClient(app)
            resp = client.get(
                "/api/telemetry/series",
                params={"measurement": "internet_rtt", "field": "rtt_avg_ms_mean"},
            )
        assert resp.status_code == 503

    def test_series_uses_alias(self, mock_influx, mock_settings):
        """Short alias 'internet_rtt' resolves to 't_internet_rtt_agg'."""
        mock_influx.query.return_value = []

        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
        ):
            client = TestClient(app)
            resp = client.get(
                "/api/telemetry/series",
                params={"measurement": "internet_rtt", "field": "rtt_avg_ms_mean"},
            )

        assert resp.status_code == 200
        # Verify the Flux query used the full measurement name
        flux_query = mock_influx.query.call_args[0][0]
        assert "t_internet_rtt_agg" in flux_query


class TestSparklinesEndpoint:
    """GET /api/telemetry/sparklines"""

    def test_sparklines_returns_all_keys(self, mock_influx, mock_settings):
        mock_influx.query.return_value = [
            {
                "_value": 19.5,
                "_time": datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
            },
        ]

        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
        ):
            client = TestClient(app)
            resp = client.get("/api/telemetry/sparklines", params={"range": "1h"})

        assert resp.status_code == 200
        data = resp.json()
        assert "sparklines" in data
        expected_keys = {"internet_rtt", "dns_latency", "http_timing", "packet_loss", "cpu", "memory"}
        assert set(data["sparklines"].keys()) == expected_keys
        assert data["range"] == "1h"
        assert data["window_seconds"] > 0

    def test_sparklines_invalid_range(self, client):
        resp = client.get("/api/telemetry/sparklines", params={"range": "30d"})
        assert resp.status_code == 400

    def test_sparklines_influx_unavailable(self, client_no_influx):
        resp = client_no_influx.get("/api/telemetry/sparklines")
        assert resp.status_code == 503

    def test_sparklines_downsampling_window(self, mock_influx, mock_settings):
        """Verify window_seconds scales with range."""
        mock_influx.query.return_value = []

        app = create_app()
        with (
            patch("beacon.api.routes.telemetry_api.get_beacon_settings", return_value=mock_settings),
            patch("beacon.api.routes.telemetry_api.get_influx_storage", return_value=mock_influx),
        ):
            client = TestClient(app)

            resp_1h = client.get("/api/telemetry/sparklines", params={"range": "1h"})
            resp_24h = client.get("/api/telemetry/sparklines", params={"range": "24h"})

        # 24h window should be larger than 1h window
        assert resp_24h.json()["window_seconds"] > resp_1h.json()["window_seconds"]


class TestFluxInjectionPrevention:
    """Verify that untrusted input cannot alter Flux queries."""

    def test_measurement_injection(self, client):
        resp = client.get(
            "/api/telemetry/series",
            params={
                "measurement": 'internet_rtt") |> drop(columns: ["_value',
                "field": "rtt_avg_ms_mean",
            },
        )
        assert resp.status_code == 400

    def test_field_injection(self, client):
        resp = client.get(
            "/api/telemetry/series",
            params={
                "measurement": "internet_rtt",
                "field": 'rtt") |> yield(name: "evil',
            },
        )
        assert resp.status_code == 400

    def test_range_injection(self, client):
        resp = client.get(
            "/api/telemetry/series",
            params={
                "measurement": "internet_rtt",
                "field": "rtt_avg_ms_mean",
                "range": "1h) |> drop(",
            },
        )
        assert resp.status_code == 400
