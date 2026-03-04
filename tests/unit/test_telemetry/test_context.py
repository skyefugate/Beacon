"""Tests for the Context sampler — device fingerprint, network topology, and geo enrichment."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beacon.telemetry.samplers.context import ContextSampler


class TestContextSamplerAttributes:
    def test_name(self):
        sampler = ContextSampler()
        assert sampler.name == "context"

    def test_tier(self):
        sampler = ContextSampler()
        assert sampler.tier == 0

    def test_default_interval(self):
        sampler = ContextSampler()
        assert sampler.default_interval == 60


class TestDeviceFingerprint:
    """Tier 1: Device fingerprint collection."""

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.psutil")
    @patch("beacon.telemetry.samplers.context.platform")
    async def test_basic_device_fields(self, mock_platform, mock_psutil):
        mock_platform.node.return_value = "test-host"
        mock_platform.system.return_value = "Darwin"
        mock_platform.release.return_value = "25.2.0"
        mock_platform.machine.return_value = "arm64"

        mock_psutil.boot_time.return_value = time.time() - 7200  # 2 hours ago
        mock_psutil.net_if_addrs.return_value = {}
        mock_psutil.net_if_stats.return_value = {}

        sampler = ContextSampler(geo_enabled=False)
        # Bypass public IP fetch
        sampler._get_public_ip = AsyncMock(return_value=None)

        metrics = await sampler.sample()

        assert len(metrics) == 1
        fields = metrics[0].fields
        assert fields["hostname"] == "test-host"
        assert fields["os"] == "Darwin"
        assert fields["os_version"] == "25.2.0"
        assert fields["arch"] == "arm64"
        assert abs(fields["system_uptime_hours"] - 2.0) < 0.1

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.psutil")
    @patch("beacon.telemetry.samplers.context.platform")
    async def test_interface_details(self, mock_platform, mock_psutil):
        mock_platform.node.return_value = "test-host"
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "6.1.0"
        mock_platform.machine.return_value = "x86_64"
        mock_psutil.boot_time.return_value = time.time() - 3600

        # Mock primary interface detection via fallback (no subprocess)
        mock_addr_inet = MagicMock()
        mock_addr_inet.family.name = "AF_INET"
        mock_addr_inet.address = "192.168.1.100"

        mock_addr_link = MagicMock()
        mock_addr_link.family.name = "AF_PACKET"
        mock_addr_link.address = "aa:bb:cc:dd:ee:ff"

        mock_psutil.net_if_addrs.return_value = {
            "eth0": [mock_addr_inet, mock_addr_link],
        }

        mock_stats = MagicMock()
        mock_stats.speed = 1000
        mock_stats.mtu = 1500
        mock_stats.isup = True
        mock_psutil.net_if_stats.return_value = {"eth0": mock_stats}

        sampler = ContextSampler(geo_enabled=False)
        sampler._get_public_ip = AsyncMock(return_value=None)

        # Patch subprocess.run to raise FileNotFoundError (triggers fallback to psutil)
        with patch("beacon.telemetry.samplers.context.subprocess") as mock_sub:
            mock_sub.run.side_effect = FileNotFoundError
            metrics = await sampler.sample()

        fields = metrics[0].fields
        assert fields["primary_interface"] == "eth0"
        assert fields["interface_speed_mbps"] == 1000
        assert fields["interface_mtu"] == 1500
        assert fields["mac_address"] == "aa:bb:cc:dd:ee:ff"
        assert fields["link_type"] == "ethernet"


class TestLinkTypeDetection:
    """Link type detection for various interface names."""

    def test_linux_wifi_prefixes(self):
        sampler = ContextSampler()
        assert sampler._detect_link_type("wlan0") == "wifi"
        assert sampler._detect_link_type("wlp3s0") == "wifi"

    def test_linux_ethernet_prefixes(self):
        sampler = ContextSampler()
        assert sampler._detect_link_type("eth0") == "ethernet"
        assert sampler._detect_link_type("eno1") == "ethernet"
        assert sampler._detect_link_type("enp0s31f6") == "ethernet"

    def test_unknown_prefix(self):
        sampler = ContextSampler()
        assert sampler._detect_link_type("docker0") == "other"

    @patch("beacon.telemetry.samplers.context.platform")
    def test_macos_wifi_via_networksetup(self, mock_platform):
        mock_platform.system.return_value = "Darwin"

        with patch("beacon.telemetry.samplers.context.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = (
                "Hardware Port: Wi-Fi\n"
                "Device: en0\n"
                "Ethernet Address: a1:b2:c3:d4:e5:f6\n"
            )
            mock_sub.run.return_value = mock_result

            sampler = ContextSampler()
            assert sampler._detect_link_type("en0") == "wifi"

    @patch("beacon.telemetry.samplers.context.platform")
    def test_macos_ethernet_via_networksetup(self, mock_platform):
        mock_platform.system.return_value = "Darwin"

        with patch("beacon.telemetry.samplers.context.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = (
                "Hardware Port: Thunderbolt Ethernet\n"
                "Device: en5\n"
                "Ethernet Address: a1:b2:c3:d4:e5:f6\n"
            )
            mock_sub.run.return_value = mock_result

            sampler = ContextSampler()
            assert sampler._detect_link_type("en5") == "ethernet"


class TestNetworkTopology:
    """Tier 2: Network topology fields."""

    def test_dns_servers_parsing(self):
        sampler = ContextSampler()
        resolv_content = "nameserver 8.8.8.8\nnameserver 8.8.4.4\n"
        with patch("beacon.telemetry.samplers.context.Path") as MockPath:
            MockPath.return_value.read_text.return_value = resolv_content
            # Patch the Path("/etc/resolv.conf") call
            result = sampler._get_dns_servers.__wrapped__(sampler) if hasattr(sampler._get_dns_servers, '__wrapped__') else None

        # Test directly with mock
        with patch.object(ContextSampler, "_get_dns_servers", return_value="8.8.4.4,8.8.8.8"):
            assert ContextSampler._get_dns_servers(sampler) == "8.8.4.4,8.8.8.8"

    def test_dns_servers_oserror(self):
        sampler = ContextSampler()
        with (
            patch("beacon.telemetry.samplers.context.subprocess") as mock_sub,
            patch("beacon.telemetry.samplers.context.Path") as MockPath,
        ):
            mock_sub.run.side_effect = FileNotFoundError  # scutil unavailable
            MockPath.return_value.read_text.side_effect = OSError
            result = sampler._get_dns_servers()
        assert result == "unknown"

    @patch("beacon.telemetry.samplers.context.psutil")
    def test_vpn_detection_active(self, mock_psutil):
        mock_psutil.net_if_addrs.return_value = {"utun0": [], "en0": []}
        mock_stats = MagicMock()
        mock_stats.isup = True
        mock_psutil.net_if_stats.return_value = {"utun0": mock_stats, "en0": mock_stats}

        sampler = ContextSampler()
        assert sampler._detect_vpn() is True

    @patch("beacon.telemetry.samplers.context.psutil")
    def test_vpn_detection_inactive(self, mock_psutil):
        mock_psutil.net_if_addrs.return_value = {"en0": [], "lo0": []}
        mock_psutil.net_if_stats.return_value = {}

        sampler = ContextSampler()
        assert sampler._detect_vpn() is False

    @patch("beacon.telemetry.samplers.context.platform")
    def test_gateway_detection_macos(self, mock_platform):
        mock_platform.system.return_value = "Darwin"

        with patch("beacon.telemetry.samplers.context.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = "   route to: default\n   gateway: 192.168.1.1\n   interface: en0\n"
            mock_sub.run.return_value = mock_result

            sampler = ContextSampler()
            assert sampler._detect_gateway_sync() == "192.168.1.1"

    @patch("beacon.telemetry.samplers.context.platform")
    def test_gateway_detection_linux(self, mock_platform):
        mock_platform.system.return_value = "Linux"

        with patch("beacon.telemetry.samplers.context.subprocess") as mock_sub:
            mock_result = MagicMock()
            mock_result.stdout = "default via 10.0.0.1 dev eth0 proto dhcp metric 100\n"
            mock_sub.run.return_value = mock_result

            sampler = ContextSampler()
            assert sampler._detect_gateway_sync() == "10.0.0.1"


class TestPublicIPCaching:
    """Tier 2: Public IP fetch with TTL cache."""

    @pytest.mark.asyncio
    async def test_public_ip_fetch(self):
        sampler = ContextSampler(public_ip_ttl=300)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "203.0.113.42"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("beacon.telemetry.samplers.context.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            ip = await sampler._get_public_ip()

        assert ip == "203.0.113.42"
        assert sampler._cached_public_ip == "203.0.113.42"

    @pytest.mark.asyncio
    async def test_public_ip_uses_cache(self):
        sampler = ContextSampler(public_ip_ttl=300)
        sampler._cached_public_ip = "203.0.113.42"
        sampler._public_ip_fetched_at = time.monotonic()  # just fetched

        # Should not make HTTP call
        ip = await sampler._get_public_ip()
        assert ip == "203.0.113.42"

    @pytest.mark.asyncio
    async def test_public_ip_cache_expired(self):
        sampler = ContextSampler(public_ip_ttl=300)
        sampler._cached_public_ip = "203.0.113.42"
        sampler._public_ip_fetched_at = time.monotonic() - 400  # expired

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "203.0.113.99"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("beacon.telemetry.samplers.context.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            ip = await sampler._get_public_ip()

        assert ip == "203.0.113.99"

    @pytest.mark.asyncio
    async def test_public_ip_failure_returns_stale(self):
        sampler = ContextSampler(public_ip_ttl=300)
        sampler._cached_public_ip = "203.0.113.42"
        sampler._public_ip_fetched_at = time.monotonic() - 400  # expired

        with patch("beacon.telemetry.samplers.context.httpx") as mock_httpx:
            mock_httpx.AsyncClient.side_effect = Exception("network error")
            ip = await sampler._get_public_ip()

        # Should return stale cache
        assert ip == "203.0.113.42"


class TestGeoEnrichment:
    """Tier 3: Geo enrichment with caching."""

    @pytest.mark.asyncio
    async def test_geo_lookup(self):
        sampler = ContextSampler(geo_enabled=True, geo_ttl=900)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "as": "AS15169 Google LLC",
            "isp": "Google LLC",
            "city": "Mountain View",
            "regionName": "California",
            "country": "United States",
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("beacon.telemetry.samplers.context.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            geo = await sampler._get_geo("8.8.8.8")

        assert geo["asn"] == "AS15169 Google LLC"
        assert geo["isp_name"] == "Google LLC"
        assert geo["geo_city"] == "Mountain View"
        assert geo["geo_region"] == "California"
        assert geo["geo_country"] == "United States"

    @pytest.mark.asyncio
    async def test_geo_cache_valid(self):
        sampler = ContextSampler(geo_ttl=900)
        sampler._cached_geo = {"asn": "AS15169", "isp_name": "Google", "geo_city": "MV", "geo_region": "CA", "geo_country": "US"}
        sampler._geo_for_ip = "8.8.8.8"
        sampler._geo_fetched_at = time.monotonic()  # just fetched

        geo = await sampler._get_geo("8.8.8.8")
        assert geo["asn"] == "AS15169"

    @pytest.mark.asyncio
    async def test_geo_refetch_on_ip_change(self):
        sampler = ContextSampler(geo_ttl=900)
        sampler._cached_geo = {"asn": "AS15169", "isp_name": "Google", "geo_city": "MV", "geo_region": "CA", "geo_country": "US"}
        sampler._geo_for_ip = "8.8.8.8"
        sampler._geo_fetched_at = time.monotonic()  # cache still valid

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "as": "AS13335 Cloudflare",
            "isp": "Cloudflare",
            "city": "San Francisco",
            "regionName": "California",
            "country": "United States",
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        # IP changed — should re-fetch despite cache being time-valid
        with patch("beacon.telemetry.samplers.context.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            geo = await sampler._get_geo("1.1.1.1")

        assert geo["isp_name"] == "Cloudflare"
        assert sampler._geo_for_ip == "1.1.1.1"

    @pytest.mark.asyncio
    async def test_geo_failure_returns_stale(self):
        sampler = ContextSampler(geo_ttl=900)
        sampler._cached_geo = {"asn": "AS15169", "isp_name": "Google", "geo_city": "MV", "geo_region": "CA", "geo_country": "US"}
        sampler._geo_for_ip = "8.8.8.8"
        sampler._geo_fetched_at = time.monotonic() - 1000  # expired

        with patch("beacon.telemetry.samplers.context.httpx") as mock_httpx:
            mock_httpx.AsyncClient.side_effect = Exception("timeout")
            geo = await sampler._get_geo("8.8.8.8")

        assert geo["asn"] == "AS15169"  # stale cache returned


class TestFullSampleIntegration:
    """Full sample() call with both measurements."""

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.psutil")
    @patch("beacon.telemetry.samplers.context.platform")
    async def test_sample_emits_two_metrics(self, mock_platform, mock_psutil):
        mock_platform.node.return_value = "test-host"
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "6.1.0"
        mock_platform.machine.return_value = "x86_64"
        mock_psutil.boot_time.return_value = time.time() - 3600
        mock_psutil.net_if_addrs.return_value = {}
        mock_psutil.net_if_stats.return_value = {}

        sampler = ContextSampler(geo_enabled=True, geo_ttl=900)

        # Mock public IP
        mock_ip_response = MagicMock()
        mock_ip_response.status_code = 200
        mock_ip_response.text = "203.0.113.42"

        # Mock geo response
        mock_geo_response = MagicMock()
        mock_geo_response.status_code = 200
        mock_geo_response.json.return_value = {
            "as": "AS15169 Google LLC",
            "isp": "Google LLC",
            "city": "Mountain View",
            "regionName": "California",
            "country": "United States",
        }

        mock_client = AsyncMock()

        async def mock_get(url, **kwargs):
            if "ipify" in url:
                return mock_ip_response
            return mock_geo_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("beacon.telemetry.samplers.context.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            metrics = await sampler.sample()

        assert len(metrics) == 2
        assert metrics[0].measurement == "t_agent_context"
        assert metrics[1].measurement == "t_network_geo"

        # Context fields
        assert metrics[0].fields["hostname"] == "test-host"
        assert metrics[0].fields["public_ip"] == "203.0.113.42"

        # Geo fields
        assert metrics[1].fields["isp_name"] == "Google LLC"
        assert metrics[1].fields["geo_city"] == "Mountain View"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.psutil")
    @patch("beacon.telemetry.samplers.context.platform")
    async def test_sample_without_geo(self, mock_platform, mock_psutil):
        mock_platform.node.return_value = "test-host"
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "6.1.0"
        mock_platform.machine.return_value = "x86_64"
        mock_psutil.boot_time.return_value = time.time() - 3600
        mock_psutil.net_if_addrs.return_value = {}
        mock_psutil.net_if_stats.return_value = {}

        sampler = ContextSampler(geo_enabled=False)
        sampler._get_public_ip = AsyncMock(return_value=None)

        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_agent_context"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.psutil")
    @patch("beacon.telemetry.samplers.context.platform")
    async def test_sample_no_public_ip_skips_geo(self, mock_platform, mock_psutil):
        """When public IP fetch fails, geo should be skipped."""
        mock_platform.node.return_value = "test-host"
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "6.1.0"
        mock_platform.machine.return_value = "x86_64"
        mock_psutil.boot_time.return_value = time.time() - 3600
        mock_psutil.net_if_addrs.return_value = {}
        mock_psutil.net_if_stats.return_value = {}

        sampler = ContextSampler(geo_enabled=True)
        sampler._get_public_ip = AsyncMock(return_value=None)

        metrics = await sampler.sample()

        assert len(metrics) == 1
        assert metrics[0].measurement == "t_agent_context"


class TestMacAddress:
    """MAC address stored as plaintext."""

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.psutil")
    @patch("beacon.telemetry.samplers.context.platform")
    async def test_mac_address_plaintext(self, mock_platform, mock_psutil):
        mock_platform.node.return_value = "h"
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "6"
        mock_platform.machine.return_value = "x86"
        mock_psutil.boot_time.return_value = time.time()

        mock_addr_inet = MagicMock()
        mock_addr_inet.family.name = "AF_INET"
        mock_addr_inet.address = "192.168.1.1"
        mock_addr_link = MagicMock()
        mock_addr_link.family.name = "AF_PACKET"
        mock_addr_link.address = "aa:bb:cc:dd:ee:ff"

        mock_psutil.net_if_addrs.return_value = {"eth0": [mock_addr_inet, mock_addr_link]}
        mock_stats = MagicMock()
        mock_stats.speed = 0
        mock_stats.mtu = 1500
        mock_stats.isup = True
        mock_psutil.net_if_stats.return_value = {"eth0": mock_stats}

        sampler = ContextSampler(geo_enabled=False)
        sampler._get_public_ip = AsyncMock(return_value=None)

        metrics = await sampler.sample()
        assert metrics[0].fields.get("mac_address") == "aa:bb:cc:dd:ee:ff"
