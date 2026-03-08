"""Tests for HTTP runner - focusing on error paths and edge cases."""

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from beacon.runners.base import RunnerConfig
from beacon.runners.http import HTTPRunner


class TestHTTPRunner:
    def test_successful_request(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"<html>ok</html>"
            mock_response.elapsed = timedelta(milliseconds=150)
            mock_response.extensions = {}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            assert envelope.plugin_name == "http"
            assert len(envelope.metrics) == 1
            assert envelope.metrics[0].fields["status_code"] == 200
            assert envelope.metrics[0].fields["success"] is True
            assert envelope.metrics[0].fields["content_length"] == 15

    def test_default_targets(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"ok"
            mock_response.elapsed = timedelta(milliseconds=100)
            mock_response.extensions = {}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig()  # No targets specified
            envelope = runner.run(uuid4(), config)

            # Should use default targets
            assert len(envelope.metrics) == 2  # google.com and cloudflare.com

    def test_http_4xx_error(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.content = b"Not Found"
            mock_response.elapsed = timedelta(milliseconds=50)
            mock_response.extensions = {}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com/notfound"])
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            http_events = [e for e in envelope.events if e.event_type == "http_error"]
            assert len(http_events) == 1
            assert http_events[0].severity.value == "warning"

    def test_http_5xx_error(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.content = b"Service Unavailable"
            mock_response.elapsed = timedelta(milliseconds=50)
            mock_response.extensions = {}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            http_events = [e for e in envelope.events if e.event_type == "http_error"]
            assert len(http_events) == 1
            assert http_events[0].severity.value == "critical"

    def test_slow_response_event(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient, \
             patch("beacon.runners.http.time.monotonic") as mock_time:
            
            # Mock time to simulate slow response
            mock_time.side_effect = [0, 3.0]  # 3 second response
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"ok"
            mock_response.elapsed = timedelta(milliseconds=2800)
            mock_response.extensions = {}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            slow_events = [e for e in envelope.events if e.event_type == "slow_http"]
            assert len(slow_events) == 1

    def test_connect_timeout(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.ConnectTimeout("Connection timed out")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            assert envelope.metrics[0].fields["error"] == "connect_timeout"
            
            timeout_events = [e for e in envelope.events if e.event_type == "http_timeout"]
            assert len(timeout_events) == 1

    def test_read_timeout(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.ReadTimeout("Read timed out")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            assert envelope.metrics[0].fields["error"] == "read_timeout"
            
            timeout_events = [e for e in envelope.events if e.event_type == "http_timeout"]
            assert len(timeout_events) == 1

    def test_connect_error(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            assert envelope.metrics[0].fields["error"] == "connect_error"
            
            connect_events = [e for e in envelope.events if e.event_type == "http_connect_error"]
            assert len(connect_events) == 1

    def test_generic_exception(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = Exception("Unexpected error")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            assert any("failed" in note for note in envelope.notes)

    def test_network_stream_extension(self):
        """Test handling of network_stream extension (currently no-op)."""
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"ok"
            mock_response.elapsed = timedelta(milliseconds=100)
            mock_response.extensions = {"network_stream": {"some": "data"}}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            # Should still work normally
            assert envelope.metrics[0].fields["success"] is True

    def test_multiple_targets(self):
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"ok"
            mock_response.elapsed = timedelta(milliseconds=100)
            mock_response.extensions = {}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=[
                "https://example.com",
                "https://test.com",
                "https://demo.com"
            ])
            envelope = runner.run(uuid4(), config)

            assert len(envelope.metrics) == 3
            assert all(m.fields["success"] for m in envelope.metrics)

    def test_redirect_handling(self):
        """Test that follow_redirects=True is set in client."""
        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"redirected content"
            mock_response.elapsed = timedelta(milliseconds=200)
            mock_response.extensions = {}
            
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"], timeout_seconds=30)
            envelope = runner.run(uuid4(), config)

            # Verify client was created with correct parameters
            MockClient.assert_called_with(timeout=30, follow_redirects=True)
            assert envelope.metrics[0].fields["success"] is True