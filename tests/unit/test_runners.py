"""Unit tests for runners — using mocks to avoid actual network calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4


from beacon.runners.base import RunnerConfig
from beacon.runners.ping import PingRunner
from beacon.runners.dns import DNSRunner
from beacon.runners.http import HTTPRunner
from beacon.runners.traceroute import TracerouteRunner
from beacon.runners.throughput import ThroughputRunner


class TestRunnerConfig:
    def test_defaults(self):
        config = RunnerConfig()
        assert config.targets == []
        assert config.count == 10
        assert config.timeout_seconds == 10
        assert config.interval == 0.5

    def test_custom_config(self):
        config = RunnerConfig(
            targets=["8.8.8.8"],
            count=5,
            timeout_seconds=30,
            extra={"resolvers": ["1.1.1.1"]},
        )
        assert config.targets == ["8.8.8.8"]
        assert config.extra["resolvers"] == ["1.1.1.1"]


class TestPingRunner:
    def test_returns_valid_envelope(self):
        with patch("beacon.runners.ping.subprocess") as mock_subprocess, \
             patch("beacon.runners.ping.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
                    "--- 8.8.8.8 ping statistics ---\n"
                    "10 packets transmitted, 10 received, 0% packet loss, time 9013ms\n"
                    "rtt min/avg/max/mdev = 10.1/15.5/25.3/4.2 ms\n"
                ),
            )

            runner = PingRunner()
            config = RunnerConfig(targets=["8.8.8.8"], count=10)
            envelope = runner.run(uuid4(), config)

            assert envelope.plugin_name == "ping"
            assert len(envelope.metrics) == 1
            assert envelope.metrics[0].fields["rtt_avg_ms"] == 15.5
            assert envelope.metrics[0].fields["loss_pct"] == 0.0

    def test_packet_loss_generates_event(self):
        with patch("beacon.runners.ping.subprocess") as mock_subprocess, \
             patch("beacon.runners.ping.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout="10 packets transmitted, 7 received, 30% packet loss\nrtt min/avg/max/mdev = 10/20/30/5 ms\n",
            )

            runner = PingRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            loss_events = [e for e in envelope.events if e.event_type == "packet_loss"]
            assert len(loss_events) == 1

    def test_high_latency_generates_event(self):
        with patch("beacon.runners.ping.subprocess") as mock_subprocess, \
             patch("beacon.runners.ping.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout="10 packets transmitted, 10 received, 0% packet loss\nrtt min/avg/max/mdev = 80/150/300/50 ms\n",
            )

            runner = PingRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            latency_events = [e for e in envelope.events if e.event_type == "high_latency"]
            assert len(latency_events) == 1

    def test_parse_ping_output(self):
        output = (
            "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
            "--- 8.8.8.8 ping statistics ---\n"
            "5 packets transmitted, 4 received, 20% packet loss, time 4005ms\n"
            "rtt min/avg/max/mdev = 10.1/15.5/25.3/4.2 ms\n"
        )
        fields = PingRunner._parse_ping_output(output, "8.8.8.8")
        assert fields["loss_pct"] == 20.0
        assert fields["rtt_min_ms"] == 10.1
        assert fields["rtt_avg_ms"] == 15.5
        assert fields["rtt_max_ms"] == 25.3
        assert fields["packets_sent"] == 5
        assert fields["packets_received"] == 4


class TestDNSRunner:
    def test_successful_resolution(self):
        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_answer = MagicMock()
            mock_answer.address = "142.250.80.46"
            mock_res.resolve.return_value = [mock_answer]

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["google.com"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.plugin_name == "dns"
            assert len(envelope.metrics) == 1
            assert envelope.metrics[0].fields["success"] is True

    def test_nxdomain(self):
        import dns.resolver

        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_res.resolve.side_effect = dns.resolver.NXDOMAIN()

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["nonexistent.invalid"],
                extra={"resolvers": ["8.8.8.8"]},
            )
            envelope = runner.run(uuid4(), config)

            assert envelope.metrics[0].fields["success"] is False
            dns_events = [e for e in envelope.events if e.event_type == "dns_failure"]
            assert len(dns_events) == 1

    def test_timeout(self):
        import dns.exception

        with patch("beacon.runners.dns.dns.resolver.Resolver") as MockResolver:
            mock_res = MagicMock()
            MockResolver.return_value = mock_res
            mock_res.resolve.side_effect = dns.exception.Timeout()

            runner = DNSRunner()
            config = RunnerConfig(
                targets=["google.com"],
                extra={"resolvers": ["10.0.0.1"]},
            )
            envelope = runner.run(uuid4(), config)

            timeout_events = [e for e in envelope.events if e.event_type == "dns_timeout"]
            assert len(timeout_events) == 1


class TestHTTPRunner:
    def test_successful_request(self):
        from datetime import timedelta

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

    def test_http_error_generates_event(self):
        from datetime import timedelta

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

    def test_connect_timeout(self):
        import httpx

        with patch("beacon.runners.http.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.ConnectTimeout("Connection timed out")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            runner = HTTPRunner()
            config = RunnerConfig(targets=["https://example.com"])
            envelope = runner.run(uuid4(), config)

            timeout_events = [e for e in envelope.events if e.event_type == "http_timeout"]
            assert len(timeout_events) == 1


class TestTracerouteRunner:
    def test_parse_traceroute(self):
        output = (
            "traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets\n"
            " 1  gateway (192.168.1.1)  1.234 ms  1.456 ms  1.789 ms\n"
            " 2  10.0.0.1 (10.0.0.1)  5.123 ms  5.456 ms  5.789 ms\n"
            " 3  * * *\n"
            " 4  dns.google (8.8.8.8)  10.123 ms  10.456 ms  10.789 ms\n"
        )
        hops = TracerouteRunner._parse_traceroute(output)
        assert len(hops) == 4
        assert hops[0]["ip"] == "192.168.1.1"
        assert hops[0]["all_timeouts"] is False
        assert hops[2]["all_timeouts"] is True
        assert hops[3]["ip"] == "8.8.8.8"

    def test_returns_valid_envelope(self):
        with patch("beacon.runners.traceroute.subprocess") as mock_subprocess, \
             patch("beacon.runners.traceroute.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "traceroute to 8.8.8.8, 30 hops max\n"
                    " 1  192.168.1.1 (192.168.1.1)  1.0 ms  1.0 ms  1.0 ms\n"
                    " 2  8.8.8.8 (8.8.8.8)  10.0 ms  10.0 ms  10.0 ms\n"
                ),
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            assert envelope.plugin_name == "traceroute"
            assert len(envelope.metrics) >= 1


class TestThroughputRunner:
    def test_no_server_configured(self):
        runner = ThroughputRunner()
        config = RunnerConfig()
        envelope = runner.run(uuid4(), config)

        assert "skipping" in envelope.notes[0].lower()

    def test_iperf3_not_installed(self):

        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("iperf3 not found")

            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)

            assert any("not installed" in n for n in envelope.notes)
