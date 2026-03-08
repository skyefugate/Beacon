"""Tests for WiFi beacon frame loss monitoring (issue #62).

Tests that beaconLostCount from airport -I is parsed and surfaced
in the t_wifi_link measurement as beacon_lost_count.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from beacon.collectors.wifi import WiFiCollector
from beacon.telemetry.samplers.wifi import WiFiSampler


AIRPORT_OUTPUT_WITH_BEACON_LOSS = (
    "     agrCtlRSSI: -55"
    + chr(10)
    + "     agrCtlNoise: -90"
    + chr(10)
    + "     channel: 149"
    + chr(10)
    + "     SSID: TestNetwork"
    + chr(10)
    + "     beaconLostCount: 12"
    + chr(10)
)

AIRPORT_OUTPUT_WITHOUT_BEACON_LOSS = (
    "     agrCtlRSSI: -55"
    + chr(10)
    + "     agrCtlNoise: -90"
    + chr(10)
    + "     SSID: TestNetwork"
    + chr(10)
)


class TestParseAirportBeaconLostCount:
    """Unit tests for _parse_airport parsing beaconLostCount field."""

    def test_beacon_lost_count_parsed(self):
        """beaconLostCount is parsed and stored as beacon_lost_count integer."""
        fields = WiFiCollector._parse_airport(AIRPORT_OUTPUT_WITH_BEACON_LOSS)
        assert fields["beacon_lost_count"] == 12

    def test_beacon_lost_count_zero(self):
        """beaconLostCount of 0 is parsed correctly."""
        output = "     agrCtlRSSI: -65" + chr(10) + "     beaconLostCount: 0" + chr(10)
        fields = WiFiCollector._parse_airport(output)
        assert fields["beacon_lost_count"] == 0

    def test_beacon_lost_count_large_value(self):
        """beaconLostCount with a large integer value is parsed correctly."""
        output = "     agrCtlRSSI: -70" + chr(10) + "     beaconLostCount: 9999" + chr(10)
        fields = WiFiCollector._parse_airport(output)
        assert fields["beacon_lost_count"] == 9999

    def test_beacon_lost_count_missing(self):
        """When beaconLostCount is absent, beacon_lost_count is not in fields."""
        fields = WiFiCollector._parse_airport(AIRPORT_OUTPUT_WITHOUT_BEACON_LOSS)
        assert "beacon_lost_count" not in fields

    def test_beacon_lost_count_with_all_other_fields(self):
        """beaconLostCount coexists with all other airport -I fields."""
        nl = chr(10)
        output = (
            "     agrCtlRSSI: -55"
            + nl
            + "     agrCtlNoise: -90"
            + nl
            + "     channel: 36"
            + nl
            + "     lastAssocStatus: 0"
            + nl
            + "     SSID: HomeWiFi"
            + nl
            + "     BSSID: aa:bb:cc:dd:ee:ff"
            + nl
            + "     beaconLostCount: 7"
            + nl
        )
        fields = WiFiCollector._parse_airport(output)
        assert fields["rssi_dbm"] == -55
        assert fields["noise_dbm"] == -90
        assert fields["channel"] == "36"
        assert fields["last_assoc_status"] == 0
        assert fields["ssid"] == "HomeWiFi"
        assert fields["bssid"] == "aa:bb:cc:dd:ee:ff"
        assert fields["beacon_lost_count"] == 7


class TestWiFiCollectorBeaconLostCount:
    """Integration tests for WiFiCollector surfacing beacon_lost_count in metrics."""

    def test_beacon_lost_count_in_metric_fields(self):
        """beacon_lost_count appears in wifi_link metric when airport reports it."""
        nl = chr(10)
        stdout = (
            "     agrCtlRSSI: -60"
            + nl
            + "     agrCtlNoise: -92"
            + nl
            + "     channel: 11"
            + nl
            + "     SSID: OfficeNet"
            + nl
            + "     beaconLostCount: 3"
            + nl
        )
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=stdout)

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert len(envelope.metrics) >= 1
            assert envelope.metrics[0].fields["beacon_lost_count"] == 3

    def test_no_beacon_lost_count_when_absent(self):
        """beacon_lost_count is absent from metric fields when not reported."""
        nl = chr(10)
        stdout = (
            "     agrCtlRSSI: -65" + nl + "     agrCtlNoise: -91" + nl + "     SSID: HomeNet" + nl
        )
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=stdout)

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert len(envelope.metrics) >= 1
            assert "beacon_lost_count" not in envelope.metrics[0].fields


class TestWiFiSamplerBeaconLostCount:
    """Tests for WiFiSampler surfacing beacon_lost_count in t_wifi_link metrics."""

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.wifi.platform")
    @patch("beacon.telemetry.samplers.wifi.asyncio.create_subprocess_exec")
    async def test_beacon_lost_count_in_t_wifi_link(self, mock_exec, mock_platform):
        """beacon_lost_count from airport -I appears in t_wifi_link measurement."""
        mock_platform.system.return_value = "Darwin"
        nl = chr(10)
        airport_output = (
            "     agrCtlRSSI: -58"
            + nl
            + "     agrCtlNoise: -93"
            + nl
            + "     channel: 6"
            + nl
            + "     SSID: MyNetwork"
            + nl
            + "     beaconLostCount: 12"
            + nl
        )
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(airport_output.encode(), b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        sampler = WiFiSampler()
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_wifi_link"
        assert metrics[0].fields["beacon_lost_count"] == 12

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.wifi.platform")
    @patch("beacon.telemetry.samplers.wifi.asyncio.create_subprocess_exec")
    async def test_beacon_lost_count_zero_in_t_wifi_link(self, mock_exec, mock_platform):
        """beacon_lost_count of 0 is correctly included in t_wifi_link."""
        mock_platform.system.return_value = "Darwin"
        nl = chr(10)
        airport_output = (
            "     agrCtlRSSI: -50"
            + nl
            + "     agrCtlNoise: -95"
            + nl
            + "     SSID: StrongSignal"
            + nl
            + "     beaconLostCount: 0"
            + nl
        )
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(airport_output.encode(), b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        sampler = WiFiSampler()
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].fields["beacon_lost_count"] == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.wifi.platform")
    @patch("beacon.telemetry.samplers.wifi.asyncio.create_subprocess_exec")
    async def test_snr_and_beacon_lost_count_coexist(self, mock_exec, mock_platform):
        """SNR calculation and beacon_lost_count both appear in t_wifi_link."""
        mock_platform.system.return_value = "Darwin"
        nl = chr(10)
        airport_output = (
            "     agrCtlRSSI: -60"
            + nl
            + "     agrCtlNoise: -90"
            + nl
            + "     SSID: TestNet"
            + nl
            + "     beaconLostCount: 5"
            + nl
        )
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(airport_output.encode(), b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        sampler = WiFiSampler()
        metrics = await sampler.sample()

        assert len(metrics) == 1
        fields = metrics[0].fields
        assert fields["snr_db"] == 30
        assert fields["beacon_lost_count"] == 5
