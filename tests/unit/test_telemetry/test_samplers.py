"""Tests for Tier 0 telemetry samplers — all with mocked subprocess/network."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beacon.telemetry.samplers.device import DeviceSampler
from beacon.telemetry.samplers.dns import DNSSampler
from beacon.telemetry.samplers.http import HTTPSampler
from beacon.telemetry.samplers.ping import PingSampler
from beacon.telemetry.samplers.wifi import WiFiSampler


class TestWiFiSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.wifi.platform")
    @patch("beacon.telemetry.samplers.wifi.asyncio")
    async def test_macos_airport_success(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Darwin"
        WiFiSampler()

        airport_output = (
            "     agrCtlRSSI: -55\n"
            "     agrCtlNoise: -90\n"
            "     channel: 149\n"
            "     SSID: TestNetwork\n"
            "     BSSID: aa:bb:cc:dd:ee:ff\n"
        )

        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(airport_output.encode(), b""))
        proc.returncode = 0

        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=proc)
        mock_asyncio.subprocess = asyncio.subprocess
        mock_asyncio.wait_for = AsyncMock(
            return_value=(airport_output.encode(), b"")
        )

        # Directly test the parser reuse
        from beacon.collectors.wifi import WiFiCollector
        fields = WiFiCollector._parse_airport(airport_output)
        assert fields["rssi_dbm"] == -55
        assert fields["noise_dbm"] == -90
        assert fields["ssid"] == "TestNetwork"

class TestPingSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.ping.asyncio.create_subprocess_exec")
    async def test_ping_success(self, mock_exec):
        ping_output = (
            "PING 8.8.8.8 (8.8.8.8): 56 data bytes\n"
            "64 bytes from 8.8.8.8: icmp_seq=0 ttl=118 time=12.3 ms\n"
            "64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=11.8 ms\n"
            "64 bytes from 8.8.8.8: icmp_seq=2 ttl=118 time=13.1 ms\n"
            "\n"
            "--- 8.8.8.8 ping statistics ---\n"
            "3 packets transmitted, 3 packets received, 0.0% packet loss\n"
            "round-trip min/avg/max/stddev = 11.8/12.4/13.1/0.5 ms\n"
        )

        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(ping_output.encode(), b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        sampler = PingSampler(targets=["8.8.8.8"], ping_gateway=False, count=3)
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_internet_rtt"
        assert metrics[0].fields["reachable"] is True
        assert metrics[0].fields["rtt_avg_ms"] == 12.4

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.ping.asyncio.create_subprocess_exec")
    async def test_ping_timeout(self, mock_exec):
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_exec.return_value = proc

        sampler = PingSampler(targets=["8.8.8.8"], ping_gateway=False)
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].fields["reachable"] is False

    @pytest.mark.asyncio
    async def test_gateway_detection(self):
        sampler = PingSampler(ping_gateway=True)
        assert sampler._ping_gateway is True


class TestDNSSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dns.dns.resolver.Resolver")
    async def test_dns_success(self, MockResolver):
        mock_res = MagicMock()
        MockResolver.return_value = mock_res

        mock_answer = MagicMock()
        mock_answer.__iter__ = MagicMock(return_value=iter([mock_answer]))
        mock_answer.address = "142.250.80.46"
        mock_res.resolve.return_value = mock_answer

        sampler = DNSSampler(resolvers=["8.8.8.8"], domains=["google.com"])
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_dns_latency"
        assert metrics[0].fields["success"] is True

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dns.dns.resolver.Resolver")
    async def test_dns_failure(self, MockResolver):
        import dns.exception
        mock_res = MagicMock()
        MockResolver.return_value = mock_res
        mock_res.resolve.side_effect = dns.exception.Timeout()

        sampler = DNSSampler(resolvers=["8.8.8.8"], domains=["google.com"])
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].fields["success"] is False


class TestHTTPSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.http.httpx.AsyncClient")
    async def test_http_success(self, MockClient):
        from datetime import timedelta

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.elapsed = timedelta(milliseconds=150)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        MockClient.return_value = mock_client

        sampler = HTTPSampler(targets=["https://example.com"])
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_http_timing"
        assert metrics[0].fields["success"] is True
        assert metrics[0].fields["status_code"] == 200

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.http.httpx.AsyncClient")
    async def test_http_timeout(self, MockClient):
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        MockClient.return_value = mock_client

        sampler = HTTPSampler(targets=["https://example.com"])
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].fields["success"] is False
        assert metrics[0].fields["error"] == "timeout"


class TestDeviceSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.device.psutil")
    async def test_device_sample(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 25.0
        mock_psutil.getloadavg.return_value = (1.0, 0.8, 0.6)
        mock_mem = MagicMock()
        mock_mem.percent = 55.0
        mock_mem.available = 4 * 1024 * 1024 * 1024  # 4 GB
        mock_psutil.virtual_memory.return_value = mock_mem

        sampler = DeviceSampler()
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_device_health"
        assert metrics[0].fields["cpu_percent"] == 25.0
        assert metrics[0].fields["memory_percent"] == 55.0
        assert metrics[0].fields["load_avg_1m"] == 1.0
