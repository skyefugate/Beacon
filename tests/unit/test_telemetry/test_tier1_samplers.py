"""Tests for Tier 1 telemetry samplers — wifi_quality, tls, vpn."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beacon.telemetry.samplers.tls import TLSSampler
from beacon.telemetry.samplers.vpn import VPNSampler
from beacon.telemetry.samplers.wifi_quality import WiFiQualitySampler


class TestWiFiQualitySampler:
    def test_parse_iw_station(self):
        output = (
            "Station aa:bb:cc:dd:ee:ff (on wlan0)\n"
            "        signal:          -55 dBm\n"
            "        tx bitrate:      866.7 MBit/s\n"
            "        rx bitrate:      780.0 MBit/s\n"
            "        tx retries:      123\n"
            "        tx failed:       5\n"
        )
        fields = WiFiQualitySampler._parse_iw_station(output)
        assert fields["rssi_dbm"] == -55
        assert fields["tx_rate_mbps"] == 866.7
        assert fields["rx_rate_mbps"] == 780.0
        assert fields["tx_retries"] == 123
        assert fields["tx_failed"] == 5

    def test_parse_wdutil_quality(self):
        output = (
            "WIFI:\n"
            "    RSSI: -50 dBm\n"
            "    Tx Rate: 1200.0 Mbps\n"
        )
        fields = WiFiQualitySampler._parse_wdutil_quality(output)
        assert fields["rssi_dbm"] == -50
        assert fields["tx_rate_mbps"] == 1200.0

    def test_tier(self):
        sampler = WiFiQualitySampler()
        assert sampler.tier == 1
        assert sampler.name == "wifi_quality"


class TestTLSSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tls.httpx.AsyncClient")
    async def test_tls_success(self, MockClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.extensions = {}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        MockClient.return_value = mock_client

        sampler = TLSSampler(targets=["https://example.com"])
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_tls_handshake"
        assert metrics[0].fields["success"] is True
        assert "handshake_ms" in metrics[0].fields

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tls.httpx.AsyncClient")
    async def test_tls_timeout(self, MockClient):
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        MockClient.return_value = mock_client

        sampler = TLSSampler(targets=["https://example.com"])
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].fields["success"] is False

    def test_tier(self):
        sampler = TLSSampler()
        assert sampler.tier == 1


class TestVPNSampler:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.vpn.psutil")
    async def test_no_vpn(self, mock_psutil):
        mock_psutil.net_if_addrs.return_value = {
            "en0": [MagicMock(family=MagicMock(name="AF_INET"))],
        }
        mock_psutil.net_if_stats.return_value = {
            "en0": MagicMock(isup=True),
        }
        mock_psutil.net_io_counters.return_value = {
            "en0": MagicMock(bytes_sent=1000, bytes_recv=2000),
        }

        sampler = VPNSampler()
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].fields["vpn_active"] is False
        assert metrics[0].fields["vpn_count"] == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.vpn.psutil")
    async def test_vpn_detected(self, mock_psutil):
        mock_psutil.net_if_addrs.return_value = {
            "en0": [MagicMock(family=MagicMock(name="AF_INET"))],
            "utun3": [MagicMock(family=MagicMock(name="AF_INET"))],
        }
        mock_psutil.net_if_stats.return_value = {
            "en0": MagicMock(isup=True),
            "utun3": MagicMock(isup=True),
        }
        mock_psutil.net_io_counters.return_value = {
            "en0": MagicMock(bytes_sent=1000, bytes_recv=2000),
            "utun3": MagicMock(bytes_sent=500, bytes_recv=800),
        }

        sampler = VPNSampler()
        metrics = await sampler.sample()

        assert metrics[0].fields["vpn_active"] is True
        assert metrics[0].fields["vpn_count"] == 1
        assert "utun3" in metrics[0].fields["vpn_interfaces"]

    def test_tier(self):
        sampler = VPNSampler()
        assert sampler.tier == 1
