"""Tests for BufferbloatSampler with mocked subprocess calls."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from beacon.telemetry.samplers.bufferbloat import BufferbloatSampler


class TestBufferbloatSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    @patch("beacon.telemetry.samplers.bufferbloat.asyncio")
    async def test_macos_network_quality_success(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Darwin"
        sampler = BufferbloatSampler()

        network_quality_output = {
            "dl_throughput": 50_000_000,
            "ul_throughput": 10_000_000,
            "dl_responsiveness": 150,
            "interface_name": "en0"
        }

        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(json.dumps(network_quality_output).encode(), b""))
        proc.returncode = 0

        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=proc)
        mock_asyncio.wait_for = AsyncMock(return_value=(json.dumps(network_quality_output).encode(), b""))

        metrics = await sampler.sample()
        assert len(metrics) == 1
        assert metrics[0].measurement == "t_bufferbloat"
        assert metrics[0].fields["dl_throughput_mbps"] == 50.0
        assert metrics[0].fields["ul_throughput_mbps"] == 10.0
        assert metrics[0].fields["responsiveness_rpm"] == 150
        assert metrics[0].fields["interface"] == "en0"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    @patch("beacon.telemetry.samplers.bufferbloat.asyncio")
    async def test_macos_network_quality_failure(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Darwin"
        sampler = BufferbloatSampler()

        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b"error"))
        proc.returncode = 1

        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=proc)
        mock_asyncio.wait_for = AsyncMock(return_value=(b"", b"error"))

        metrics = await sampler.sample()
        assert len(metrics) == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    @patch("beacon.telemetry.samplers.bufferbloat.asyncio")
    async def test_macos_network_quality_timeout(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Darwin"
        sampler = BufferbloatSampler()

        mock_asyncio.create_subprocess_exec = AsyncMock()
        mock_asyncio.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())

        metrics = await sampler.sample()
        assert len(metrics) == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    @patch("beacon.telemetry.samplers.bufferbloat.asyncio")
    async def test_macos_network_quality_file_not_found(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Darwin"
        sampler = BufferbloatSampler()

        mock_asyncio.create_subprocess_exec = AsyncMock(side_effect=FileNotFoundError())

        metrics = await sampler.sample()
        assert len(metrics) == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    @patch("beacon.telemetry.samplers.bufferbloat.asyncio")
    async def test_linux_iperf3_success(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Linux"
        sampler = BufferbloatSampler(iperf3_server="test.server.com")

        iperf3_output = {
            "end": {
                "sum_sent": {
                    "bits_per_second": 20_000_000,
                    "jitter_ms": 5.2
                },
                "sum_received": {
                    "bits_per_second": 45_000_000
                }
            }
        }

        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(json.dumps(iperf3_output).encode(), b""))
        proc.returncode = 0

        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=proc)
        mock_asyncio.wait_for = AsyncMock(return_value=(json.dumps(iperf3_output).encode(), b""))

        metrics = await sampler.sample()
        assert len(metrics) == 1
        assert metrics[0].fields["ul_throughput_mbps"] == 20.0
        assert metrics[0].fields["dl_throughput_mbps"] == 45.0
        assert metrics[0].fields["jitter_ms"] == 5.2

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    async def test_linux_no_iperf3_server(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        sampler = BufferbloatSampler()  # No server specified

        metrics = await sampler.sample()
        assert len(metrics) == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    @patch("beacon.telemetry.samplers.bufferbloat.asyncio")
    async def test_linux_iperf3_failure(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Linux"
        sampler = BufferbloatSampler(iperf3_server="test.server.com")

        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b"connection failed"))
        proc.returncode = 1

        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=proc)
        mock_asyncio.wait_for = AsyncMock(return_value=(b"", b"connection failed"))

        metrics = await sampler.sample()
        assert len(metrics) == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    async def test_unsupported_platform(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        sampler = BufferbloatSampler()

        metrics = await sampler.sample()
        assert len(metrics) == 0

    def test_parse_network_quality_minimal(self):
        output = json.dumps({"dl_throughput": 1_000_000})
        fields = BufferbloatSampler._parse_network_quality(output)
        assert fields["dl_throughput_mbps"] == 1.0

    def test_parse_network_quality_responsiveness_fallback(self):
        output = json.dumps({"responsiveness": 100})
        fields = BufferbloatSampler._parse_network_quality(output)
        assert fields["responsiveness_rpm"] == 100

    def test_parse_network_quality_invalid_json(self):
        fields = BufferbloatSampler._parse_network_quality("invalid json")
        assert fields == {}

    def test_parse_iperf3_minimal(self):
        output = json.dumps({
            "end": {
                "sum_sent": {"bits_per_second": 5_000_000}
            }
        })
        fields = BufferbloatSampler._parse_iperf3(output)
        assert fields["ul_throughput_mbps"] == 5.0

    def test_parse_iperf3_invalid_json(self):
        fields = BufferbloatSampler._parse_iperf3("invalid json")
        assert fields == {}

    def test_parse_iperf3_missing_keys(self):
        output = json.dumps({"start": {}})
        fields = BufferbloatSampler._parse_iperf3(output)
        assert fields == {}

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.bufferbloat.platform")
    @patch("beacon.telemetry.samplers.bufferbloat.asyncio")
    async def test_exception_handling(self, mock_asyncio, mock_platform):
        mock_platform.system.return_value = "Darwin"
        sampler = BufferbloatSampler()

        mock_asyncio.create_subprocess_exec = AsyncMock(side_effect=Exception("Unexpected error"))

        metrics = await sampler.sample()
        assert len(metrics) == 0