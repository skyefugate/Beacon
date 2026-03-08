"""Unit tests for telemetry samplers."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch
import pytest

from beacon.telemetry.samplers.ping import PingSampler
from beacon.telemetry.samplers.dns import DNSSampler
from beacon.telemetry.samplers.http import HTTPSampler
from beacon.telemetry.samplers.device import DeviceSampler
from beacon.telemetry.samplers.context import ContextSampler
from beacon.telemetry.samplers.wifi import WiFiSampler
from beacon.telemetry.samplers.nic import NicSampler
from beacon.telemetry.samplers.tcp import TcpSampler
from beacon.telemetry.samplers.dhcp import DhcpSampler
from beacon.telemetry.samplers.change import ChangeDetector


class TestPingSampler:
    def test_init_default(self):
        sampler = PingSampler()
        assert sampler.name == "ping"
        assert sampler.default_interval == 60
        assert sampler._targets == ["8.8.8.8", "1.1.1.1"]
        assert sampler._ping_gateway is True

    def test_init_custom(self):
        sampler = PingSampler(
            targets=["192.168.1.1"],
            ping_gateway=False,
        )
        assert sampler._targets == ["192.168.1.1"]
        assert sampler._ping_gateway is False

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.ping.subprocess")
    @patch("beacon.telemetry.samplers.ping.platform")
    async def test_sample_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Linux"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
            "--- 8.8.8.8 ping statistics ---\n"
            "3 packets transmitted, 3 received, 0% packet loss, time 2003ms\n"
            "rtt min/avg/max/mdev = 10.1/15.5/25.3/4.2 ms\n"
        )
        mock_subprocess.run.return_value = mock_result
        
        sampler = PingSampler(targets=["8.8.8.8"], ping_gateway=False)
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "ping"
        assert metrics[0].fields["rtt_ms"] == 15.5
        assert metrics[0].fields["loss_pct"] == 0.0
        assert metrics[0].tags["target"] == "8.8.8.8"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.ping.subprocess")
    async def test_sample_failure(self, mock_subprocess):
        mock_result = Mock()
        mock_result.returncode = 1
        mock_subprocess.run.return_value = mock_result
        
        sampler = PingSampler(targets=["8.8.8.8"], ping_gateway=False)
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].fields["rtt_ms"] == 0.0
        assert metrics[0].fields["loss_pct"] == 100.0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.ping.subprocess")
    async def test_sample_exception(self, mock_subprocess):
        mock_subprocess.run.side_effect = Exception("Command failed")
        
        sampler = PingSampler(targets=["8.8.8.8"], ping_gateway=False)
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].fields["rtt_ms"] == 0.0
        assert metrics[0].fields["loss_pct"] == 100.0


class TestDNSSampler:
    def test_init_default(self):
        sampler = DNSSampler()
        assert sampler.name == "dns"
        assert sampler.default_interval == 120
        assert sampler._resolvers == ["8.8.8.8", "1.1.1.1"]
        assert sampler._domains == ["google.com", "cloudflare.com"]

    def test_init_custom(self):
        sampler = DNSSampler(
            resolvers=["192.168.1.1"],
            domains=["example.com"],
        )
        assert sampler._resolvers == ["192.168.1.1"]
        assert sampler._domains == ["example.com"]

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dns.time")
    @patch("beacon.telemetry.samplers.dns.socket")
    async def test_sample_success(self, mock_socket, mock_time):
        mock_time.time.side_effect = [1000.0, 1000.05]  # 50ms response
        mock_socket.getaddrinfo.return_value = [("family", "type", "proto", "canonname", ("1.2.3.4", 80))]
        
        sampler = DNSSampler(resolvers=["8.8.8.8"], domains=["google.com"])
        
        with patch("beacon.telemetry.samplers.dns.dns.resolver.Resolver") as mock_resolver_class:
            mock_resolver = Mock()
            mock_resolver.resolve.return_value = [Mock(address="1.2.3.4")]
            mock_resolver_class.return_value = mock_resolver
            
            metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "dns"
        assert metrics[0].fields["response_time_ms"] == 50.0
        assert metrics[0].fields["success"] == 1
        assert metrics[0].tags["resolver"] == "8.8.8.8"
        assert metrics[0].tags["domain"] == "google.com"

    @pytest.mark.asyncio
    async def test_sample_failure(self):
        sampler = DNSSampler(resolvers=["8.8.8.8"], domains=["google.com"])
        
        with patch("beacon.telemetry.samplers.dns.dns.resolver.Resolver") as mock_resolver_class:
            mock_resolver = Mock()
            mock_resolver.resolve.side_effect = Exception("DNS error")
            mock_resolver_class.return_value = mock_resolver
            
            metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].fields["success"] == 0


class TestHTTPSampler:
    def test_init_default(self):
        sampler = HTTPSampler()
        assert sampler.name == "http"
        assert sampler.default_interval == 300
        assert sampler._targets == ["https://www.google.com", "https://www.cloudflare.com"]

    def test_init_custom(self):
        sampler = HTTPSampler(targets=["https://example.com"])
        assert sampler._targets == ["https://example.com"]

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.http.httpx.AsyncClient")
    async def test_sample_success(self, mock_client_class):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        sampler = HTTPSampler(targets=["https://google.com"])
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "http"
        assert metrics[0].fields["response_time_ms"] == 500.0
        assert metrics[0].fields["status_code"] == 200
        assert metrics[0].fields["success"] == 1
        assert metrics[0].tags["target"] == "https://google.com"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.http.httpx.AsyncClient")
    async def test_sample_failure(self, mock_client_class):
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("HTTP error")
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        sampler = HTTPSampler(targets=["https://google.com"])
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].fields["success"] == 0
        assert metrics[0].fields["status_code"] == 0


class TestDeviceSampler:
    def test_init(self):
        sampler = DeviceSampler()
        assert sampler.name == "device"
        assert sampler.default_interval == 600

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.device.psutil")
    async def test_sample_success(self, mock_psutil):
        # Mock CPU
        mock_psutil.cpu_percent.return_value = 25.5
        mock_psutil.getloadavg.return_value = (1.2, 1.0, 0.8)
        mock_psutil.cpu_count.return_value = 4
        
        # Mock memory
        mock_memory = Mock()
        mock_memory.total = 8 * 1024 * 1024 * 1024  # 8GB
        mock_memory.available = 4 * 1024 * 1024 * 1024  # 4GB
        mock_memory.percent = 50.0
        mock_psutil.virtual_memory.return_value = mock_memory
        
        # Mock disk
        mock_disk = Mock()
        mock_disk.total = 256 * 1024 * 1024 * 1024  # 256GB
        mock_disk.free = 128 * 1024 * 1024 * 1024  # 128GB
        mock_disk.percent = 50.0
        mock_psutil.disk_usage.return_value = mock_disk
        
        sampler = DeviceSampler()
        metrics = await sampler.sample()
        
        assert len(metrics) >= 3  # CPU, memory, disk
        
        # Find CPU metric
        cpu_metric = next(m for m in metrics if m.measurement == "device_cpu")
        assert cpu_metric.fields["percent"] == 25.5
        assert cpu_metric.fields["load_avg_1m"] == 1.2

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.device.psutil")
    async def test_sample_exception(self, mock_psutil):
        mock_psutil.cpu_percent.side_effect = Exception("CPU error")
        
        sampler = DeviceSampler()
        metrics = await sampler.sample()
        
        # Should return empty list on exception
        assert metrics == []


class TestContextSampler:
    def test_init_default(self):
        sampler = ContextSampler()
        assert sampler.name == "context"
        assert sampler.default_interval == 3600
        assert sampler._public_ip_ttl == 3600
        assert sampler._geo_ttl == 86400
        assert sampler._geo_enabled is True

    def test_init_custom(self):
        sampler = ContextSampler(
            public_ip_ttl=1800,
            geo_ttl=43200,
            geo_enabled=False,
        )
        assert sampler._public_ip_ttl == 1800
        assert sampler._geo_ttl == 43200
        assert sampler._geo_enabled is False

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.httpx")
    async def test_sample_success(self, mock_httpx):
        # Mock public IP response
        mock_ip_response = Mock()
        mock_ip_response.status_code = 200
        mock_ip_response.text = "203.0.113.1"
        
        # Mock geo response
        mock_geo_response = Mock()
        mock_geo_response.status_code = 200
        mock_geo_response.json.return_value = {
            "country": "US",
            "region": "CA",
            "city": "San Francisco",
            "isp": "Example ISP",
        }
        
        mock_httpx.get.side_effect = [mock_ip_response, mock_geo_response]
        
        sampler = ContextSampler()
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "context"
        assert metrics[0].fields["public_ip"] == "203.0.113.1"
        assert metrics[0].fields["country"] == "US"
        assert metrics[0].fields["city"] == "San Francisco"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.httpx")
    async def test_sample_cached_values(self, mock_httpx):
        sampler = ContextSampler()
        
        # Set cached values
        sampler._public_ip_cache = ("203.0.113.1", 2000000000)  # Future timestamp
        sampler._geo_cache = ({"country": "US"}, 2000000000)
        
        metrics = await sampler.sample()
        
        # Should not make HTTP requests
        mock_httpx.get.assert_not_called()
        assert len(metrics) == 1
        assert metrics[0].fields["public_ip"] == "203.0.113.1"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.context.httpx")
    async def test_sample_geo_disabled(self, mock_httpx):
        mock_ip_response = Mock()
        mock_ip_response.status_code = 200
        mock_ip_response.text = "203.0.113.1"
        mock_httpx.get.return_value = mock_ip_response
        
        sampler = ContextSampler(geo_enabled=False)
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert "country" not in metrics[0].fields
        # Should only call once for IP, not for geo
        assert mock_httpx.get.call_count == 1


class TestWiFiSampler:
    def test_init(self):
        sampler = WiFiSampler()
        assert sampler.name == "wifi"
        assert sampler.default_interval == 30

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.wifi.subprocess")
    @patch("beacon.telemetry.samplers.wifi.platform")
    async def test_sample_macos_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Darwin"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
     agrCtlRSSI: -45
     agrExtRSSI: 0
        agrCtlNoise: -90
        agrExtNoise: 0
               state: running
            op mode: station
         lastTxRate: 866
            maxRate: 866
lastAssocStatus: 0
    802.11 auth: open
      link auth: wpa2-psk
          BSSID: aa:bb:cc:dd:ee:ff
           SSID: TestNetwork
            MCS: CC 2
        channel: 36
        """
        mock_subprocess.run.return_value = mock_result
        
        sampler = WiFiSampler()
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "wifi"
        assert metrics[0].fields["rssi_dbm"] == -45
        assert metrics[0].fields["noise_dbm"] == -90
        assert metrics[0].fields["tx_rate_mbps"] == 866
        assert metrics[0].tags["ssid"] == "TestNetwork"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.wifi.subprocess")
    @patch("beacon.telemetry.samplers.wifi.platform")
    async def test_sample_linux_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Linux"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
wlan0     IEEE 802.11  ESSID:"TestNetwork"
          Mode:Managed  Frequency:2.437 GHz  Access Point: AA:BB:CC:DD:EE:FF
          Bit Rate=72.2 Mb/s   Tx-Power=20 dBm
          Retry short limit:7   RTS thr:off   Fragment thr:off
          Power Management:on
          Link Quality=70/70  Signal level=-40 dBm
          Rx invalid nwid:0  Rx invalid crypt:0  Rx invalid frag:0
        """
        mock_subprocess.run.return_value = mock_result
        
        sampler = WiFiSampler()
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "wifi"
        assert metrics[0].fields["rssi_dbm"] == -40
        assert metrics[0].fields["tx_rate_mbps"] == 72.2
        assert metrics[0].tags["ssid"] == "TestNetwork"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.wifi.subprocess")
    @patch("beacon.telemetry.samplers.wifi.platform")
    async def test_sample_not_connected(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Darwin"
        mock_result = Mock()
        mock_result.returncode = 1
        mock_subprocess.run.return_value = mock_result
        
        sampler = WiFiSampler()
        metrics = await sampler.sample()
        
        assert metrics == []


class TestNicSampler:
    def test_init(self):
        sampler = NicSampler()
        assert sampler.name == "nic"
        assert sampler.default_interval == 60

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    async def test_sample_success(self, mock_psutil):
        # Mock network interface stats
        mock_stats = Mock()
        mock_stats.bytes_sent = 1000000
        mock_stats.bytes_recv = 2000000
        mock_stats.packets_sent = 1000
        mock_stats.packets_recv = 2000
        mock_stats.errin = 0
        mock_stats.errout = 0
        mock_stats.dropin = 0
        mock_stats.dropout = 0
        
        mock_psutil.net_io_counters.return_value = {"eth0": mock_stats}
        
        sampler = NicSampler()
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "nic"
        assert metrics[0].fields["bytes_sent"] == 1000000
        assert metrics[0].fields["bytes_recv"] == 2000000
        assert metrics[0].tags["interface"] == "eth0"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    async def test_sample_exception(self, mock_psutil):
        mock_psutil.net_io_counters.side_effect = Exception("Network error")
        
        sampler = NicSampler()
        metrics = await sampler.sample()
        
        assert metrics == []


class TestTcpSampler:
    def test_init(self):
        sampler = TcpSampler()
        assert sampler.name == "tcp"
        assert sampler.default_interval == 60

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tcp.psutil")
    async def test_sample_success(self, mock_psutil):
        # Mock network connections
        mock_conn1 = Mock()
        mock_conn1.status = "ESTABLISHED"
        mock_conn1.laddr.port = 80
        mock_conn1.raddr.ip = "192.168.1.1"
        
        mock_conn2 = Mock()
        mock_conn2.status = "LISTEN"
        mock_conn2.laddr.port = 22
        mock_conn2.raddr = None
        
        mock_psutil.net_connections.return_value = [mock_conn1, mock_conn2]
        
        sampler = TcpSampler()
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "tcp"
        assert "established_count" in metrics[0].fields
        assert "listen_count" in metrics[0].fields

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tcp.psutil")
    async def test_sample_exception(self, mock_psutil):
        mock_psutil.net_connections.side_effect = Exception("TCP error")
        
        sampler = TcpSampler()
        metrics = await sampler.sample()
        
        assert metrics == []


class TestDhcpSampler:
    def test_init(self):
        sampler = DhcpSampler()
        assert sampler.name == "dhcp"
        assert sampler.default_interval == 300

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dhcp.subprocess")
    @patch("beacon.telemetry.samplers.dhcp.platform")
    async def test_sample_macos_success(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Darwin"
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
lease {
  interface "en0";
  fixed-address 192.168.1.100;
  option subnet-mask 255.255.255.0;
  option routers 192.168.1.1;
  option domain-name-servers 8.8.8.8, 1.1.1.1;
  renew 2 2023/01/01 12:00:00;
  rebind 2 2023/01/01 18:00:00;
  expire 2 2023/01/01 20:00:00;
}
        """
        mock_subprocess.run.return_value = mock_result
        
        sampler = DhcpSampler()
        metrics = await sampler.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "dhcp"
        assert metrics[0].fields["lease_active"] == 1
        assert metrics[0].tags["interface"] == "en0"

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.dhcp.subprocess")
    @patch("beacon.telemetry.samplers.dhcp.platform")
    async def test_sample_no_lease(self, mock_platform, mock_subprocess):
        mock_platform.system.return_value = "Darwin"
        mock_result = Mock()
        mock_result.returncode = 1
        mock_subprocess.run.return_value = mock_result
        
        sampler = DhcpSampler()
        metrics = await sampler.sample()
        
        assert metrics == []


class TestChangeDetector:
    def test_init(self):
        detector = ChangeDetector()
        assert detector.name == "change"
        assert detector.default_interval == 300

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.change.psutil")
    async def test_sample_first_run(self, mock_psutil):
        # Mock network interfaces
        mock_psutil.net_if_addrs.return_value = {
            "eth0": [Mock(family=Mock(name="AF_INET"), address="192.168.1.100")]
        }
        
        # Mock default gateway
        mock_psutil.net_if_stats.return_value = {"eth0": Mock(isup=True)}
        
        detector = ChangeDetector()
        metrics = await detector.sample()
        
        # First run should not detect changes
        assert metrics == []

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.change.psutil")
    async def test_sample_network_change(self, mock_psutil):
        detector = ChangeDetector()
        
        # First sample
        mock_psutil.net_if_addrs.return_value = {
            "eth0": [Mock(family=Mock(name="AF_INET"), address="192.168.1.100")]
        }
        mock_psutil.net_if_stats.return_value = {"eth0": Mock(isup=True)}
        await detector.sample()
        
        # Second sample with different IP
        mock_psutil.net_if_addrs.return_value = {
            "eth0": [Mock(family=Mock(name="AF_INET"), address="192.168.1.101")]
        }
        metrics = await detector.sample()
        
        assert len(metrics) == 1
        assert metrics[0].measurement == "network_change"
        assert metrics[0].fields["change_detected"] == 1

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.change.psutil")
    async def test_sample_exception(self, mock_psutil):
        mock_psutil.net_if_addrs.side_effect = Exception("Network error")
        
        detector = ChangeDetector()
        metrics = await detector.sample()
        
        assert metrics == []