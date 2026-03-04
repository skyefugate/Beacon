"""Tests for DhcpSampler -- DHCP lease tracking via mocked subprocess."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from beacon.telemetry.samplers.dhcp import DhcpSampler


class TestDhcpSamplerAttributes:
    def test_name(self):
        assert DhcpSampler.name == "dhcp"

    def test_tier(self):
        assert DhcpSampler.tier == 0

    def test_default_interval(self):
        assert DhcpSampler.default_interval == 60


IPCONFIG_SAMPLE = (
    "op = BOOTREPLY\n"
    "htype = 1\n"
    "ciaddr = 0.0.0.0\n"
    "yiaddr = 192.168.1.50\n"
    "siaddr = 192.168.1.1\n"
    "lease_time = 0x15180 (86400)\n"
    "renewal_time = 0xa8c0 (43200)\n"
    "rebinding_time = 0x12750 (75600)\n"
    "subnet_mask = 255.255.255.0\n"
    "router = 192.168.1.1\n"
    "domain_name_server = 8.8.8.8, 8.8.4.4\n"
)


class TestParseIpconfigOutput:
    def test_parses_lease_time(self):
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["lease_time_seconds"] == 86400

    def test_parses_ip_address(self):
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["ip_address"] == "192.168.1.50"

    def test_parses_router(self):
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["router"] == "192.168.1.1"

    def test_parses_dns_servers(self):
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["dns_servers"] == "8.8.8.8,8.8.4.4"

    def test_has_valid_lease(self):
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["has_valid_lease"] == 1

    def test_lease_age_from_renewal_time(self):
        # renewal_time=43200 => age = 86400 - 43200 = 43200
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["lease_age_seconds"] == 43200

    def test_lease_remaining_pct(self):
        # remaining = 43200 / 86400 * 100 = 50.0
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["lease_remaining_pct"] == 50.0

    def test_expiry_not_approaching_at_50pct(self):
        fields = DhcpSampler._parse_ipconfig_output(IPCONFIG_SAMPLE)
        assert fields["lease_expiry_approaching"] == 0

    def test_expiry_approaching_when_below_10pct(self):
        # renewal_time very small => lease almost expired (6.25%)
        low_renewal = IPCONFIG_SAMPLE.replace(
            "renewal_time = 0xa8c0 (43200)",
            "renewal_time = 0x1518 (5400)",
        )
        fields = DhcpSampler._parse_ipconfig_output(low_renewal)
        assert fields["lease_expiry_approaching"] == 1

    def test_no_lease_when_missing_ip(self):
        output = "op = BOOTREQUEST\nlease_time = 0x15180 (86400)\n"
        fields = DhcpSampler._parse_ipconfig_output(output)
        assert fields["has_valid_lease"] == 0

    def test_no_renewal_time_assumes_fresh_lease(self):
        no_renewal = IPCONFIG_SAMPLE.replace("renewal_time = 0xa8c0 (43200)\n", "")
        fields = DhcpSampler._parse_ipconfig_output(no_renewal)
        assert fields["lease_age_seconds"] == 0
        assert fields["lease_remaining_pct"] == 100.0


class TestCollectMacOS:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dhcp.platform")
    @patch("beacon.telemetry.samplers.dhcp.subprocess")
    @patch("beacon.telemetry.samplers.dhcp.psutil")
    async def test_sample_macos_success(self, mock_psutil, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"

        route_result = MagicMock()
        route_result.returncode = 0
        route_result.stdout = "interface: en0\n"

        ipconfig_result = MagicMock()
        ipconfig_result.returncode = 0
        ipconfig_result.stdout = IPCONFIG_SAMPLE

        mock_subprocess.run.side_effect = [route_result, ipconfig_result]
        mock_subprocess.TimeoutExpired = __import__("subprocess").TimeoutExpired

        sampler = DhcpSampler()
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_dhcp_health"
        assert metrics[0].fields["has_valid_lease"] == 1
        assert metrics[0].fields["ip_address"] == "192.168.1.50"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dhcp.platform")
    @patch("beacon.telemetry.samplers.dhcp.subprocess")
    @patch("beacon.telemetry.samplers.dhcp.psutil")
    async def test_sample_macos_no_lease(self, mock_psutil, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"

        route_result = MagicMock()
        route_result.returncode = 0
        route_result.stdout = "interface: en0\n"

        empty_result = MagicMock()
        empty_result.returncode = 1
        empty_result.stdout = ""

        mock_subprocess.run.side_effect = [route_result, empty_result]
        mock_subprocess.TimeoutExpired = __import__("subprocess").TimeoutExpired

        sampler = DhcpSampler()
        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].fields["has_valid_lease"] == 0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dhcp.platform")
    @patch("beacon.telemetry.samplers.dhcp.subprocess")
    @patch("beacon.telemetry.samplers.dhcp.psutil")
    async def test_sample_macos_no_interface(self, mock_psutil, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"

        route_result = MagicMock()
        route_result.returncode = 0
        route_result.stdout = ""

        mock_subprocess.run.return_value = route_result
        mock_subprocess.TimeoutExpired = __import__("subprocess").TimeoutExpired
        mock_psutil.net_if_addrs.return_value = {}

        sampler = DhcpSampler()
        metrics = await sampler.sample()

        assert metrics == []

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dhcp.platform")
    async def test_unsupported_platform_returns_empty(self, mock_platform):
        mock_platform.system.return_value = "Windows"
        sampler = DhcpSampler()
        metrics = await sampler.sample()
        assert metrics == []


class TestLinuxLeaseFileParsing:
    def test_parses_isc_dhclient_format(self):
        lease_content = (
            "lease {\n"
            "  interface eth0;\n"
            "  fixed-address 10.0.0.5;\n"
            "  default-lease-time 3600;\n"
            "  option routers 10.0.0.1;\n"
            "  option domain-name-servers 1.1.1.1, 1.0.0.1;\n"
            "\n"
        )
        fields = DhcpSampler._parse_linux_lease_file(lease_content)
        assert fields["has_valid_lease"] == 1
        assert fields["ip_address"] == "10.0.0.5"
        assert fields["lease_time_seconds"] == 3600
        assert fields["router"] == "10.0.0.1"
        assert fields["dns_servers"] == "1.1.1.1,1.0.0.1"

    def test_parses_dhcpcd_format_with_acquired_time(self):
        import time
        now = int(time.time())
        acquired = now - 1800
        lease_content = (
            "lease_time=3600\n"
            "ip_address=172.16.0.20\n"
            f"acquired={acquired}\n"
        )
        fields = DhcpSampler._parse_linux_lease_file(lease_content)
        assert fields["has_valid_lease"] == 1
        assert fields["ip_address"] == "172.16.0.20"
        assert abs(fields["lease_age_seconds"] - 1800) < 5
        assert abs(fields["lease_remaining_pct"] - 50.0) < 1.0

    def test_empty_content_returns_no_lease(self):
        fields = DhcpSampler._parse_linux_lease_file("")
        assert fields["has_valid_lease"] == 0


class TestNoLeaseFields:
    def test_no_lease_fields_structure(self):
        fields = DhcpSampler._no_lease_fields()
        assert fields["has_valid_lease"] == 0
        assert fields["lease_time_seconds"] == 0
        assert fields["lease_age_seconds"] == 0
        assert fields["lease_remaining_pct"] == 0.0
        assert fields["lease_expiry_approaching"] == 0
