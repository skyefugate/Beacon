"""Comprehensive unit tests for runners."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
import pytest

from beacon.runners.ping import PingRunner
from beacon.runners.dns import DNSRunner
from beacon.runners.http import HTTPRunner
from beacon.runners.traceroute import TracerouteRunner
from beacon.runners.throughput import ThroughputRunner
from beacon.runners.base import RunnerConfig


class TestRunnerConfig:
    def test_defaults(self):
        config = RunnerConfig()
        assert config.targets == []
        assert config.count == 10
        assert config.timeout_seconds == 10
        assert config.interval == 0.5
        assert config.extra == {}

    def test_custom_values(self):
        config = RunnerConfig(
            targets=["8.8.8.8", "1.1.1.1"],
            count=5,
            timeout_seconds=30,
            interval=1.0,
            extra={"custom": "value"},
        )
        assert config.targets == ["8.8.8.8", "1.1.1.1"]
        assert config.count == 5
        assert config.timeout_seconds == 30
        assert config.interval == 1.0
        assert config.extra == {"custom": "value"}

    def test_from_dict(self):
        data = {
            "targets": ["test.com"],
            "count": 3,
            "timeout_seconds": 15,
            "custom_field": "value",
        }
        config = RunnerConfig(**data)
        assert config.targets == ["test.com"]
        assert config.count == 3
        assert config.timeout_seconds == 15
        assert config.extra.get("custom_field") == "value"


class TestPingRunner:
    @pytest.mark.asyncio
    @patch("beacon.runners.ping.subprocess")
    @patch("beacon.runners.ping.platform")
    async def test_run_linux_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Linux"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
            "64 bytes from 8.8.8.8: icmp_seq=1 time=12.5 ms\n"
            "64 bytes from 8.8.8.8: icmp_seq=2 time=13.2 ms\n"
            "64 bytes from 8.8.8.8: icmp_seq=3 time=11.8 ms\n"
            "--- 8.8.8.8 ping statistics ---\n"
            "3 packets transmitted, 3 received, 0% packet loss, time 2003ms\n"
            "rtt min/avg/max/mdev = 11.8/12.5/13.2/0.7 ms\n"
        )
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["8.8.8.8"], "count": 3}
        runner = PingRunner(config)
        envelope = await runner.run(uuid4())
        
        assert envelope.plugin_name == "ping"
        assert len(envelope.metrics) == 1
        
        metric = envelope.metrics[0]
        assert metric.measurement == "ping"
        assert metric.fields["rtt_ms"] == 12.5
        assert metric.fields["loss_pct"] == 0.0
        assert metric.fields["min_rtt_ms"] == 11.8
        assert metric.fields["max_rtt_ms"] == 13.2
        assert metric.tags["target"] == "8.8.8.8"

    @pytest.mark.asyncio
    @patch("beacon.runners.ping.subprocess")
    @patch("beacon.runners.ping.platform")
    async def test_run_macos_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Darwin"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "PING 8.8.8.8 (8.8.8.8): 56 data bytes\n"
            "64 bytes from 8.8.8.8: icmp_seq=0 ttl=118 time=12.345 ms\n"
            "64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=13.456 ms\n"
            "--- 8.8.8.8 ping statistics ---\n"
            "2 packets transmitted, 2 packets received, 0.0% packet loss\n"
            "round-trip min/avg/max/stddev = 12.345/12.901/13.456/0.556 ms\n"
        )
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["8.8.8.8"], "count": 2}
        runner = PingRunner(config)
        envelope = await runner.run(uuid4())
        
        metric = envelope.metrics[0]
        assert metric.fields["rtt_ms"] == 12.901
        assert metric.fields["loss_pct"] == 0.0

    @pytest.mark.asyncio
    @patch("beacon.runners.ping.subprocess")
    @patch("beacon.runners.ping.platform")
    async def test_run_packet_loss(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Linux"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
            "64 bytes from 8.8.8.8: icmp_seq=1 time=12.5 ms\n"
            "--- 8.8.8.8 ping statistics ---\n"
            "3 packets transmitted, 1 received, 66% packet loss, time 2003ms\n"
            "rtt min/avg/max/mdev = 12.5/12.5/12.5/0.0 ms\n"
        )
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["8.8.8.8"], "count": 3}
        runner = PingRunner(config)
        envelope = await runner.run(uuid4())
        
        metric = envelope.metrics[0]
        assert metric.fields["loss_pct"] == 66.0

    @pytest.mark.asyncio
    @patch("beacon.runners.ping.subprocess")
    async def test_run_command_failure(self, mock_subprocess):
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "ping: cannot resolve 8.8.8.8: Unknown host"
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["8.8.8.8"]}
        runner = PingRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.events) == 1
        assert envelope.events[0].severity.name == "ERROR"
        assert "ping failed" in envelope.events[0].message.lower()

    @pytest.mark.asyncio
    @patch("beacon.runners.ping.subprocess")
    async def test_run_exception(self, mock_subprocess):
        mock_subprocess.run.side_effect = Exception("Command execution failed")
        
        config = {"targets": ["8.8.8.8"]}
        runner = PingRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.events) == 1
        assert envelope.events[0].severity.name == "ERROR"

    @pytest.mark.asyncio
    async def test_run_multiple_targets(self):
        config = {"targets": ["8.8.8.8", "1.1.1.1"]}
        runner = PingRunner(config)
        
        with patch.object(runner, "_ping_target") as mock_ping:
            mock_ping.return_value = (12.5, 0.0, 10.0, 15.0)
            envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 2
        assert mock_ping.call_count == 2

    @pytest.mark.asyncio
    async def test_run_no_targets(self):
        config = {"targets": []}
        runner = PingRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 0
        assert len(envelope.events) == 1
        assert "No targets" in envelope.events[0].message


class TestDNSRunner:
    @pytest.mark.asyncio
    @patch("beacon.runners.dns.dns.resolver.Resolver")
    @patch("beacon.runners.dns.time")
    async def test_run_success(self, mock_time, mock_resolver_class):
        mock_time.time.side_effect = [1000.0, 1000.05]  # 50ms
        
        mock_answer = Mock()
        mock_answer.rrset = [Mock(address="1.2.3.4")]
        
        mock_resolver = Mock()
        mock_resolver.resolve.return_value = mock_answer
        mock_resolver_class.return_value = mock_resolver
        
        config = {
            "resolvers": ["8.8.8.8"],
            "domains": ["google.com"],
            "record_types": ["A"],
        }
        runner = DNSRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 1
        metric = envelope.metrics[0]
        assert metric.measurement == "dns"
        assert metric.fields["response_time_ms"] == 50.0
        assert metric.fields["success"] == 1
        assert metric.tags["resolver"] == "8.8.8.8"
        assert metric.tags["domain"] == "google.com"
        assert metric.tags["record_type"] == "A"

    @pytest.mark.asyncio
    @patch("beacon.runners.dns.dns.resolver.Resolver")
    async def test_run_dns_failure(self, mock_resolver_class):
        mock_resolver = Mock()
        mock_resolver.resolve.side_effect = Exception("DNS resolution failed")
        mock_resolver_class.return_value = mock_resolver
        
        config = {
            "resolvers": ["8.8.8.8"],
            "domains": ["nonexistent.example"],
        }
        runner = DNSRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 1
        metric = envelope.metrics[0]
        assert metric.fields["success"] == 0
        assert metric.fields["response_time_ms"] == 0.0

    @pytest.mark.asyncio
    async def test_run_multiple_combinations(self):
        config = {
            "resolvers": ["8.8.8.8", "1.1.1.1"],
            "domains": ["google.com", "cloudflare.com"],
            "record_types": ["A", "AAAA"],
        }
        runner = DNSRunner(config)
        
        with patch.object(runner, "_resolve_dns") as mock_resolve:
            mock_resolve.return_value = (50.0, True, "1.2.3.4")
            envelope = await runner.run(uuid4())
        
        # 2 resolvers × 2 domains × 2 record types = 8 combinations
        assert len(envelope.metrics) == 8
        assert mock_resolve.call_count == 8

    @pytest.mark.asyncio
    async def test_run_default_config(self):
        runner = DNSRunner({})
        
        with patch.object(runner, "_resolve_dns") as mock_resolve:
            mock_resolve.return_value = (50.0, True, "1.2.3.4")
            envelope = await runner.run(uuid4())
        
        # Should use default values
        assert len(envelope.metrics) > 0


class TestHTTPRunner:
    @pytest.mark.asyncio
    @patch("beacon.runners.http.httpx.AsyncClient")
    async def test_run_success(self, mock_client_class):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.headers = {"content-type": "text/html"}
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        config = {"targets": ["https://google.com"]}
        runner = HTTPRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 1
        metric = envelope.metrics[0]
        assert metric.measurement == "http"
        assert metric.fields["response_time_ms"] == 500.0
        assert metric.fields["status_code"] == 200
        assert metric.fields["success"] == 1
        assert metric.tags["target"] == "https://google.com"

    @pytest.mark.asyncio
    @patch("beacon.runners.http.httpx.AsyncClient")
    async def test_run_http_error(self, mock_client_class):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.elapsed.total_seconds.return_value = 0.2
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        config = {"targets": ["https://example.com/notfound"]}
        runner = HTTPRunner(config)
        envelope = await runner.run(uuid4())
        
        metric = envelope.metrics[0]
        assert metric.fields["status_code"] == 404
        assert metric.fields["success"] == 0

    @pytest.mark.asyncio
    @patch("beacon.runners.http.httpx.AsyncClient")
    async def test_run_network_error(self, mock_client_class):
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        config = {"targets": ["https://unreachable.example"]}
        runner = HTTPRunner(config)
        envelope = await runner.run(uuid4())
        
        metric = envelope.metrics[0]
        assert metric.fields["success"] == 0
        assert metric.fields["status_code"] == 0
        assert metric.fields["response_time_ms"] == 0.0

    @pytest.mark.asyncio
    async def test_run_multiple_targets(self):
        config = {"targets": ["https://google.com", "https://cloudflare.com"]}
        runner = HTTPRunner(config)
        
        with patch.object(runner, "_fetch_url") as mock_fetch:
            mock_fetch.return_value = (200, 500.0, True)
            envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 2
        assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_run_custom_timeout(self):
        config = {"targets": ["https://google.com"], "timeout_seconds": 30}
        runner = HTTPRunner(config)
        
        with patch("beacon.runners.http.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            await runner.run(uuid4())
        
        # Verify timeout was passed to httpx
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args[1]
        assert call_kwargs["timeout"] == 30


class TestTracerouteRunner:
    @pytest.mark.asyncio
    @patch("beacon.runners.traceroute.subprocess")
    @patch("beacon.runners.traceroute.platform")
    async def test_run_linux_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Linux"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets\n"
            " 1  192.168.1.1 (192.168.1.1)  1.234 ms  1.456 ms  1.678 ms\n"
            " 2  10.0.0.1 (10.0.0.1)  5.123 ms  5.234 ms  5.345 ms\n"
            " 3  8.8.8.8 (8.8.8.8)  12.345 ms  12.456 ms  12.567 ms\n"
        )
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["8.8.8.8"]}
        runner = TracerouteRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 3  # 3 hops
        
        # Check first hop
        hop1 = envelope.metrics[0]
        assert hop1.measurement == "traceroute"
        assert hop1.fields["hop"] == 1
        assert hop1.fields["rtt_ms"] == 1.456  # Average of 3 measurements
        assert hop1.tags["target"] == "8.8.8.8"
        assert hop1.tags["hop_ip"] == "192.168.1.1"

    @pytest.mark.asyncio
    @patch("beacon.runners.traceroute.subprocess")
    @patch("beacon.runners.traceroute.platform")
    async def test_run_macos_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Darwin"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "traceroute to 8.8.8.8 (8.8.8.8), 64 hops max, 52 byte packets\n"
            " 1  192.168.1.1 (192.168.1.1)  1.234 ms  1.456 ms  1.678 ms\n"
            " 2  * * *\n"
            " 3  8.8.8.8 (8.8.8.8)  12.345 ms  12.456 ms  12.567 ms\n"
        )
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["8.8.8.8"]}
        runner = TracerouteRunner(config)
        envelope = await runner.run(uuid4())
        
        # Should have 2 metrics (hop 2 is timeout, so skipped)
        assert len(envelope.metrics) == 2

    @pytest.mark.asyncio
    @patch("beacon.runners.traceroute.subprocess")
    async def test_run_command_failure(self, mock_subprocess):
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "traceroute: unknown host 8.8.8.8"
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["8.8.8.8"]}
        runner = TracerouteRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.events) == 1
        assert envelope.events[0].severity.name == "ERROR"

    @pytest.mark.asyncio
    async def test_run_multiple_targets(self):
        config = {"targets": ["8.8.8.8", "1.1.1.1"]}
        runner = TracerouteRunner(config)
        
        with patch.object(runner, "_traceroute_target") as mock_trace:
            mock_trace.return_value = [
                (1, "192.168.1.1", 1.5),
                (2, "8.8.8.8", 12.5),
            ]
            envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 4  # 2 hops × 2 targets
        assert mock_trace.call_count == 2

    @pytest.mark.asyncio
    async def test_run_custom_max_hops(self):
        config = {"targets": ["8.8.8.8"], "max_hops": 15}
        runner = TracerouteRunner(config)
        
        with patch("beacon.runners.traceroute.subprocess") as mock_subprocess:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "traceroute output"
            mock_subprocess.run.return_value = mock_result
            
            await runner.run(uuid4())
        
        # Verify max_hops was used in command
        call_args = mock_subprocess.run.call_args[0][0]
        assert "15" in call_args


class TestThroughputRunner:
    @pytest.mark.asyncio
    @patch("beacon.runners.throughput.subprocess")
    async def test_run_iperf3_success(self, mock_subprocess):
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """{
            "end": {
                "sum_sent": {
                    "bits_per_second": 100000000
                },
                "sum_received": {
                    "bits_per_second": 95000000
                }
            }
        }"""
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["iperf3.example.com"]}
        runner = ThroughputRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 1
        metric = envelope.metrics[0]
        assert metric.measurement == "throughput"
        assert metric.fields["upload_mbps"] == 100.0  # 100Mbps
        assert metric.fields["download_mbps"] == 95.0  # 95Mbps
        assert metric.tags["target"] == "iperf3.example.com"

    @pytest.mark.asyncio
    @patch("beacon.runners.throughput.subprocess")
    async def test_run_iperf3_failure(self, mock_subprocess):
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "iperf3: error - unable to connect to server"
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["unreachable.example.com"]}
        runner = ThroughputRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.events) == 1
        assert envelope.events[0].severity.name == "ERROR"

    @pytest.mark.asyncio
    @patch("beacon.runners.throughput.subprocess")
    async def test_run_invalid_json(self, mock_subprocess):
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "invalid json output"
        mock_subprocess.run.return_value = mock_result
        
        config = {"targets": ["iperf3.example.com"]}
        runner = ThroughputRunner(config)
        envelope = await runner.run(uuid4())
        
        assert len(envelope.events) == 1
        assert "JSON parsing" in envelope.events[0].message

    @pytest.mark.asyncio
    async def test_run_multiple_targets(self):
        config = {"targets": ["server1.example.com", "server2.example.com"]}
        runner = ThroughputRunner(config)
        
        with patch.object(runner, "_test_throughput") as mock_test:
            mock_test.return_value = (100.0, 95.0)
            envelope = await runner.run(uuid4())
        
        assert len(envelope.metrics) == 2
        assert mock_test.call_count == 2

    @pytest.mark.asyncio
    async def test_run_custom_duration(self):
        config = {"targets": ["iperf3.example.com"], "duration": 30}
        runner = ThroughputRunner(config)
        
        with patch("beacon.runners.throughput.subprocess") as mock_subprocess:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = '{"end": {"sum_sent": {"bits_per_second": 100000000}, "sum_received": {"bits_per_second": 95000000}}}'
            mock_subprocess.run.return_value = mock_result
            
            await runner.run(uuid4())
        
        # Verify duration was used in command
        call_args = mock_subprocess.run.call_args[0][0]
        assert "-t" in call_args
        assert "30" in call_args


class TestRunnerIntegration:
    """Integration tests for runner base functionality."""
    
    @pytest.mark.asyncio
    async def test_envelope_structure(self):
        """Test that all runners return properly structured envelopes."""
        config = {"targets": ["8.8.8.8"]}
        runner = PingRunner(config)
        
        with patch.object(runner, "_ping_target", return_value=(12.5, 0.0, 10.0, 15.0)):
            envelope = await runner.run(uuid4())
        
        # Verify envelope structure
        assert envelope.plugin_name == "ping"
        assert envelope.plugin_version is not None
        assert envelope.run_id is not None
        assert envelope.started_at is not None
        assert envelope.completed_at is not None
        assert envelope.started_at <= envelope.completed_at
        assert isinstance(envelope.metrics, list)
        assert isinstance(envelope.events, list)
        assert isinstance(envelope.artifacts, list)
        assert isinstance(envelope.notes, list)

    @pytest.mark.asyncio
    async def test_concurrent_execution(self):
        """Test that runners can handle concurrent execution."""
        config = {"targets": ["8.8.8.8", "1.1.1.1"]}
        runner = PingRunner(config)
        
        # Run multiple instances concurrently
        tasks = []
        for _ in range(3):
            with patch.object(runner, "_ping_target", return_value=(12.5, 0.0, 10.0, 15.0)):
                task = asyncio.create_task(runner.run(uuid4()))
                tasks.append(task)
        
        envelopes = await asyncio.gather(*tasks)
        
        # All should complete successfully
        assert len(envelopes) == 3
        for envelope in envelopes:
            assert envelope.plugin_name == "ping"
            assert len(envelope.metrics) == 2  # 2 targets

    @pytest.mark.asyncio
    async def test_error_handling_consistency(self):
        """Test that all runners handle errors consistently."""
        runners = [
            PingRunner({"targets": ["8.8.8.8"]}),
            DNSRunner({"resolvers": ["8.8.8.8"], "domains": ["google.com"]}),
            HTTPRunner({"targets": ["https://google.com"]}),
        ]
        
        for runner in runners:
            # Mock a failure for each runner type
            if isinstance(runner, PingRunner):
                with patch("beacon.runners.ping.subprocess") as mock_subprocess:
                    mock_subprocess.run.side_effect = Exception("Test error")
                    envelope = await runner.run(uuid4())
            elif isinstance(runner, DNSRunner):
                with patch("beacon.runners.dns.dns.resolver.Resolver") as mock_resolver_class:
                    mock_resolver_class.side_effect = Exception("Test error")
                    envelope = await runner.run(uuid4())
            elif isinstance(runner, HTTPRunner):
                with patch("beacon.runners.http.httpx.AsyncClient") as mock_client_class:
                    mock_client_class.side_effect = Exception("Test error")
                    envelope = await runner.run(uuid4())
            
            # All should handle errors gracefully
            assert envelope is not None
            assert envelope.plugin_name == runner.__class__.__name__.replace("Runner", "").lower()
            # Should have error events or failure metrics
            assert len(envelope.events) > 0 or any(
                m.fields.get("success", 1) == 0 for m in envelope.metrics
            )