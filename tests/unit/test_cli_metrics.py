"""Tests for beacon metrics CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from beacon.cli.app import app
from beacon.config import reset_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_beacon_settings():
    """Reset settings singleton after each test."""
    yield
    reset_settings()


class TestMetricsQuery:
    def test_query_locally_success(self):
        """Test successful local Flux query."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'
        mock_results = [{"_time": "2024-01-01T12:00:00Z", "_value": 42}]

        with patch("beacon.storage.influx.InfluxStorage") as MockInflux:
            mock_influx = MockInflux.return_value.__enter__.return_value
            mock_influx.query.return_value = mock_results

            result = runner.invoke(app, ["metrics", "query", flux_query])

            assert result.exit_code == 0
            assert '"results"' in result.output
            assert "42" in result.output
            mock_influx.query.assert_called_once_with(flux_query)

    def test_query_locally_failure(self):
        """Test local Flux query failure."""
        flux_query = "invalid flux query"

        with patch("beacon.storage.influx.InfluxStorage") as MockInflux:
            mock_influx = MockInflux.return_value.__enter__.return_value
            mock_influx.query.side_effect = Exception("Query syntax error")

            result = runner.invoke(app, ["metrics", "query", flux_query])

            assert result.exit_code == 1
            assert "Query failed" in result.output
            assert "Query syntax error" in result.output

    def test_query_via_api_success(self):
        """Test successful API query."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'
        server_url = "http://localhost:8000"
        mock_response = {"results": [{"_time": "2024-01-01T12:00:00Z", "_value": 42}]}

        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_post.return_value = mock_resp

            result = runner.invoke(app, ["metrics", "query", flux_query, "--server", server_url])

            assert result.exit_code == 0
            assert '"results"' in result.output
            assert "42" in result.output
            mock_post.assert_called_once_with(
                f"{server_url}/metrics/query",
                json={"query": flux_query},
                timeout=30,
            )

    def test_query_via_api_http_error(self):
        """Test API query with HTTP error."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'
        server_url = "http://localhost:8000"

        with patch("httpx.post") as mock_post:
            import httpx

            mock_post.side_effect = httpx.HTTPError("Connection refused")

            result = runner.invoke(app, ["metrics", "query", flux_query, "--server", server_url])

            assert result.exit_code == 1
            assert "Query failed" in result.output

    def test_query_via_api_server_error(self):
        """Test API query with server error response."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'
        server_url = "http://localhost:8000"

        with patch("httpx.post") as mock_post:
            import httpx

            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPError("500 Internal Server Error")
            mock_post.return_value = mock_resp

            result = runner.invoke(app, ["metrics", "query", flux_query, "--server", server_url])

            assert result.exit_code == 1
            assert "Query failed" in result.output

    def test_query_server_url_normalization(self):
        """Test that server URL is properly normalized (trailing slash removed)."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'
        server_url = "http://localhost:8000/"

        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_post.return_value = mock_resp

            runner.invoke(app, ["metrics", "query", flux_query, "--server", server_url])

            # Should call without trailing slash
            mock_post.assert_called_once_with(
                "http://localhost:8000/metrics/query",
                json={"query": flux_query},
                timeout=30,
            )

    @patch("beacon.config.get_settings")
    def test_query_locally_uses_settings(self, mock_settings):
        """Test that local query uses settings for InfluxDB configuration."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'
        mock_settings.return_value = MagicMock()

        with patch("beacon.storage.influx.InfluxStorage") as MockInflux:
            mock_influx = MockInflux.return_value.__enter__.return_value
            mock_influx.query.return_value = []

            runner.invoke(app, ["metrics", "query", flux_query])

            MockInflux.assert_called_once_with(mock_settings.return_value)

    def test_query_short_server_option(self):
        """Test query with short server option (-s)."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'
        server_url = "http://localhost:8000"

        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_post.return_value = mock_resp

            result = runner.invoke(app, ["metrics", "query", flux_query, "-s", server_url])

            assert result.exit_code == 0
            mock_post.assert_called_once()

    def test_query_empty_results(self):
        """Test query with empty results."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'

        with patch("beacon.storage.influx.InfluxStorage") as MockInflux:
            mock_influx = MockInflux.return_value.__enter__.return_value
            mock_influx.query.return_value = []

            result = runner.invoke(app, ["metrics", "query", flux_query])

            assert result.exit_code == 0
            assert '"results": []' in result.output

    def test_query_complex_flux(self):
        """Test query with complex Flux query."""
        flux_query = """
        from(bucket:"telemetry")
          |> range(start:-1h)
          |> filter(fn: (r) => r._measurement == "network_latency")
          |> aggregateWindow(every: 5m, fn: mean)
        """

        with patch("beacon.storage.influx.InfluxStorage") as MockInflux:
            mock_influx = MockInflux.return_value.__enter__.return_value
            mock_influx.query.return_value = []

            result = runner.invoke(app, ["metrics", "query", flux_query])

            assert result.exit_code == 0
            mock_influx.query.assert_called_once_with(flux_query)


class TestMetricsCommandErrors:
    def test_missing_flux_argument(self):
        """Test query command without Flux query argument."""
        result = runner.invoke(app, ["metrics", "query"])

        assert result.exit_code != 0
        # Typer should show usage/help

    def test_invalid_metrics_subcommand(self):
        """Test invalid metrics subcommand."""
        result = runner.invoke(app, ["metrics", "invalid"])

        assert result.exit_code != 0

    def test_influx_storage_initialization_error(self):
        """Test handling of InfluxDB storage initialization errors."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'

        with patch("beacon.storage.influx.InfluxStorage") as MockInflux:
            MockInflux.side_effect = Exception("InfluxDB connection failed")

            result = runner.invoke(app, ["metrics", "query", flux_query])

            assert result.exit_code == 1
            assert "Query failed" in result.output

    def test_context_manager_error(self):
        """Test handling of context manager errors."""
        flux_query = 'from(bucket:"test") |> range(start:-1h)'

        with patch("beacon.storage.influx.InfluxStorage") as MockInflux:
            MockInflux.return_value.__enter__.side_effect = Exception("Context error")

            result = runner.invoke(app, ["metrics", "query", flux_query])

            assert result.exit_code == 1
            assert "Query failed" in result.output
