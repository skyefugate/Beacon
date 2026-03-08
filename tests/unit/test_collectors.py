"""Unit tests for collectors — using mocks to avoid requiring real hardware/privileges."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch
from uuid import uuid4


from beacon.collectors.device import DeviceCollector
from beacon.collectors.lan import LANCollector
from beacon.collectors.wifi import WiFiCollector
from beacon.collectors.path import PathCollector, _detect_gateway


class TestDeviceCollector:
    def test_returns_valid_envelope(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 25.0
            mock_psutil.getloadavg.return_value = (1.0, 0.8, 0.6)
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=4 * 1024**3, percent=50.0
            )
            mock_psutil.disk_partitions.return_value = [MagicMock(mountpoint="/")]
            mock_psutil.disk_usage.return_value = MagicMock(
                total=256 * 1024**3, free=128 * 1024**3, percent=50.0
            )
            mock_psutil.sensors_temperatures.return_value = {}

            collector = DeviceCollector()
            run_id = uuid4()
            envelope = collector.collect(run_id)

            assert envelope.plugin_name == "device"
            assert envelope.run_id == run_id
            assert len(envelope.metrics) >= 2  # CPU + memory at minimum

    def test_high_cpu_triggers_event(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 95.0
            mock_psutil.getloadavg.return_value = (8.0, 7.0, 6.0)
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=4 * 1024**3, percent=50.0
            )
            mock_psutil.disk_partitions.return_value = []
            mock_psutil.sensors_temperatures.return_value = {}

            collector = DeviceCollector()
            envelope = collector.collect(uuid4())

            cpu_events = [e for e in envelope.events if e.event_type == "high_cpu"]
            assert len(cpu_events) == 1

    def test_thermal_not_available(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.getloadavg.return_value = (0.5, 0.4, 0.3)
            mock_psutil.cpu_count.return_value = 2
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=4 * 1024**3, available=3 * 1024**3, percent=25.0
            )
            mock_psutil.disk_partitions.return_value = []
            mock_psutil.sensors_temperatures.side_effect = AttributeError

            collector = DeviceCollector()
            envelope = collector.collect(uuid4())
            assert "Thermal sensors not available" in envelope.notes[0]

    def test_high_memory_triggers_event(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.getloadavg.return_value = (0.5, 0.4, 0.3)
            mock_psutil.cpu_count.return_value = 2
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=0.5 * 1024**3, percent=95.0
            )
            mock_psutil.disk_partitions.return_value = []
            mock_psutil.sensors_temperatures.return_value = {}

            collector = DeviceCollector()
            envelope = collector.collect(uuid4())

            memory_events = [e for e in envelope.events if e.event_type == "high_memory"]
            assert len(memory_events) == 1

    def test_high_disk_usage_triggers_event(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.getloadavg.return_value = (0.5, 0.4, 0.3)
            mock_psutil.cpu_count.return_value = 2
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=4 * 1024**3, percent=50.0
            )
            mock_psutil.disk_partitions.return_value = [MagicMock(mountpoint="/")]
            mock_psutil.disk_usage.return_value = MagicMock(
                total=100 * 1024**3, free=2 * 1024**3, percent=98.0
            )
            mock_psutil.sensors_temperatures.return_value = {}

            collector = DeviceCollector()
            envelope = collector.collect(uuid4())

            disk_events = [e for e in envelope.events if e.event_type == "high_disk_usage"]
            assert len(disk_events) == 1

    def test_thermal_sensors_available(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.getloadavg.return_value = (0.5, 0.4, 0.3)
            mock_psutil.cpu_count.return_value = 2
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=4 * 1024**3, percent=50.0
            )
            mock_psutil.disk_partitions.return_value = []
            mock_psutil.sensors_temperatures.return_value = {
                "cpu": [MagicMock(current=65.0, label="Core 0")]
            }

            collector = DeviceCollector()
            envelope = collector.collect(uuid4())

            thermal_metrics = [m for m in envelope.metrics if m.measurement == "device_thermal"]
            assert len(thermal_metrics) == 1
            assert thermal_metrics[0].fields["temp_celsius"] == 65.0

    def test_high_temperature_triggers_event(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.getloadavg.return_value = (0.5, 0.4, 0.3)
            mock_psutil.cpu_count.return_value = 2
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=4 * 1024**3, percent=50.0
            )
            mock_psutil.disk_partitions.return_value = []
            mock_psutil.sensors_temperatures.return_value = {
                "cpu": [MagicMock(current=85.0, label="Core 0")]
            }

            collector = DeviceCollector()
            envelope = collector.collect(uuid4())

            temp_events = [e for e in envelope.events if e.event_type == "high_temperature"]
            assert len(temp_events) == 1

    def test_cpu_count_none_fallback(self):
        with patch("beacon.collectors.device.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 10.0
            mock_psutil.getloadavg.return_value = (0.5, 0.4, 0.3)
            mock_psutil.cpu_count.return_value = None  # Test fallback
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8 * 1024**3, available=4 * 1024**3, percent=50.0
            )
            mock_psutil.disk_partitions.return_value = []
            mock_psutil.sensors_temperatures.return_value = {}

            collector = DeviceCollector()
            envelope = collector.collect(uuid4())

            cpu_metric = next(m for m in envelope.metrics if m.measurement == "device_cpu")
            assert cpu_metric.fields["core_count"] == 1


class TestLANCollector:
    def test_returns_valid_envelope(self):
        with patch("beacon.collectors.lan.psutil") as mock_psutil:
            mock_psutil.net_io_counters.return_value = {
                "eth0": MagicMock(
                    bytes_sent=1000,
                    bytes_recv=2000,
                    packets_sent=10,
                    packets_recv=20,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
            }
            mock_psutil.net_if_addrs.return_value = {
                "eth0": [MagicMock(family=MagicMock(name="AF_INET"), address="192.168.1.100")],
            }
            mock_psutil.net_if_stats.return_value = {
                "eth0": MagicMock(isup=True, speed=1000, mtu=1500),
            }

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            assert envelope.plugin_name == "lan"
            assert len(envelope.metrics) >= 1

    def test_interface_errors_generate_events(self):
        with patch("beacon.collectors.lan.psutil") as mock_psutil:
            mock_psutil.net_io_counters.return_value = {
                "eth0": MagicMock(
                    bytes_sent=1000,
                    bytes_recv=2000,
                    packets_sent=10,
                    packets_recv=20,
                    errin=5,
                    errout=3,
                    dropin=0,
                    dropout=0,
                ),
            }
            mock_psutil.net_if_addrs.return_value = {}
            mock_psutil.net_if_stats.return_value = {}

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            error_events = [e for e in envelope.events if e.event_type == "interface_errors"]
            assert len(error_events) == 1

    def test_loopback_excluded(self):
        with patch("beacon.collectors.lan.psutil") as mock_psutil:
            mock_psutil.net_io_counters.return_value = {
                "lo": MagicMock(
                    bytes_sent=100,
                    bytes_recv=100,
                    packets_sent=1,
                    packets_recv=1,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
                "lo0": MagicMock(
                    bytes_sent=100,
                    bytes_recv=100,
                    packets_sent=1,
                    packets_recv=1,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
            }
            mock_psutil.net_if_addrs.return_value = {}
            mock_psutil.net_if_stats.return_value = {}

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            # No metrics since only loopback interfaces
            iface_metrics = [m for m in envelope.metrics if m.measurement == "lan_interface"]
            assert len(iface_metrics) == 0

    def test_default_interface_detection_darwin(self):
        with (
            patch("beacon.collectors.lan.psutil") as mock_psutil,
            patch("beacon.collectors.lan.platform") as mock_platform,
            patch("beacon.collectors.lan.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0, stdout="default via 192.168.1.1 dev en0\n"
            )
            mock_psutil.net_io_counters.return_value = {}
            mock_psutil.net_if_addrs.return_value = {}
            mock_psutil.net_if_stats.return_value = {}

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            assert any("Default route interface: en0" in n for n in envelope.notes)

    def test_default_interface_detection_linux(self):
        with (
            patch("beacon.collectors.lan.psutil") as mock_psutil,
            patch("beacon.collectors.lan.platform") as mock_platform,
            patch("beacon.collectors.lan.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0, stdout="default via 192.168.1.1 dev eth0 proto dhcp metric 100\n"
            )
            mock_psutil.net_io_counters.return_value = {}
            mock_psutil.net_if_addrs.return_value = {}
            mock_psutil.net_if_stats.return_value = {}

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            assert any("Default route interface: eth0" in n for n in envelope.notes)

    def test_default_interface_detection_failure(self):
        with (
            patch("beacon.collectors.lan.psutil") as mock_psutil,
            patch("beacon.collectors.lan.platform") as mock_platform,
            patch("beacon.collectors.lan.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.side_effect = Exception("Command failed")
            mock_psutil.net_io_counters.return_value = {}
            mock_psutil.net_if_addrs.return_value = {}
            mock_psutil.net_if_stats.return_value = {}

            collector = LANCollector()
            collector.collect(uuid4())

            # Should not crash, just no default interface note

    def test_interface_role_classification(self):
        with patch("beacon.collectors.lan.psutil") as mock_psutil:
            mock_psutil.net_io_counters.return_value = {
                "en0": MagicMock(
                    bytes_sent=1000,
                    bytes_recv=2000,
                    packets_sent=10,
                    packets_recv=20,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
                "bridge0": MagicMock(
                    bytes_sent=0,
                    bytes_recv=0,
                    packets_sent=0,
                    packets_recv=0,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
                "utun0": MagicMock(
                    bytes_sent=500,
                    bytes_recv=600,
                    packets_sent=5,
                    packets_recv=6,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
                "awdl0": MagicMock(
                    bytes_sent=0,
                    bytes_recv=0,
                    packets_sent=0,
                    packets_recv=0,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
            }
            mock_psutil.net_if_addrs.return_value = {
                "en0": [MagicMock(family=MagicMock(name="AF_INET"), address="192.168.1.100")],
                "utun0": [MagicMock(family=MagicMock(name="AF_INET"), address="10.0.0.1")],
            }
            mock_psutil.net_if_stats.return_value = {
                "en0": MagicMock(isup=True, speed=1000, mtu=1500),
                "bridge0": MagicMock(isup=False, speed=0, mtu=1500),
                "utun0": MagicMock(isup=True, speed=0, mtu=1500),
                "awdl0": MagicMock(isup=True, speed=0, mtu=1500),
            }

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            metrics = envelope.metrics
            en0_metric = next(m for m in metrics if m.tags.get("interface") == "en0")
            assert en0_metric.tags["role"] == "physical"

            utun_metric = next(m for m in metrics if m.tags.get("interface") == "utun0")
            assert utun_metric.tags["role"] == "vpn_tunnel"

            bridge_metric = next(m for m in metrics if m.tags.get("interface") == "bridge0")
            assert bridge_metric.tags["role"] == "virtual"

            awdl_metric = next(m for m in metrics if m.tags.get("interface") == "awdl0")
            assert awdl_metric.tags["role"] == "virtual"

    def test_primary_interface_role(self):
        with (
            patch("beacon.collectors.lan.psutil") as mock_psutil,
            patch("beacon.collectors.lan.platform") as mock_platform,
            patch("beacon.collectors.lan.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0, stdout="default via 192.168.1.1 dev eth0 proto dhcp metric 100\n"
            )
            mock_psutil.net_io_counters.return_value = {
                "eth0": MagicMock(
                    bytes_sent=1000,
                    bytes_recv=2000,
                    packets_sent=10,
                    packets_recv=20,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
            }
            mock_psutil.net_if_addrs.return_value = {
                "eth0": [MagicMock(family=MagicMock(name="AF_INET"), address="192.168.1.100")],
            }
            mock_psutil.net_if_stats.return_value = {
                "eth0": MagicMock(isup=True, speed=1000, mtu=1500),
            }

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            eth0_metric = next(m for m in envelope.metrics if m.tags.get("interface") == "eth0")
            assert eth0_metric.tags["role"] == "primary"

    def test_inactive_interface_role(self):
        with patch("beacon.collectors.lan.psutil") as mock_psutil:
            mock_psutil.net_io_counters.return_value = {
                "eth1": MagicMock(
                    bytes_sent=0,
                    bytes_recv=0,
                    packets_sent=0,
                    packets_recv=0,
                    errin=0,
                    errout=0,
                    dropin=0,
                    dropout=0,
                ),
            }
            mock_psutil.net_if_addrs.return_value = {}
            mock_psutil.net_if_stats.return_value = {
                "eth1": MagicMock(isup=False, speed=0, mtu=1500),
            }

            collector = LANCollector()
            envelope = collector.collect(uuid4())

            eth1_metric = next(m for m in envelope.metrics if m.tags.get("interface") == "eth1")
            assert eth1_metric.tags["role"] == "inactive"


class TestWiFiCollector:
    def test_macos_collection(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "     agrCtlRSSI: -55\n"
                    "     agrCtlNoise: -90\n"
                    "     channel: 36\n"
                    "     lastAssocStatus: 0\n"
                    "     SSID: TestNetwork\n"
                ),
            )

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert envelope.plugin_name == "wifi"
            assert len(envelope.metrics) >= 1
            wifi_metric = envelope.metrics[0]
            assert wifi_metric.fields["rssi_dbm"] == -55
            assert wifi_metric.fields["ssid"] == "TestNetwork"

    def test_weak_signal_event(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout="     agrCtlRSSI: -80\n     agrCtlNoise: -90\n",
            )

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            weak_events = [e for e in envelope.events if e.event_type == "weak_signal"]
            assert len(weak_events) == 1

    def test_beacon_lost_count_parsing(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "     agrCtlRSSI: -55\n"
                    "     agrCtlNoise: -90\n"
                    "     channel: 36\n"
                    "     beaconLostCount: 5\n"
                    "     SSID: TestNetwork\n"
                ),
            )

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert len(envelope.metrics) >= 1
            wifi_metric = envelope.metrics[0]
            assert wifi_metric.fields["beacon_lost_count"] == 5

    def test_unsupported_platform(self):
        with patch("beacon.collectors.wifi.platform") as mock_platform:
            mock_platform.system.return_value = "Windows"

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert any("not supported" in n for n in envelope.notes)

    def test_macos_airport_fallback_to_wdutil(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
            patch("beacon.collectors.wifi._AIRPORT_PATH", "/nonexistent/airport"),
        ):
            mock_platform.system.return_value = "Darwin"
            # First call (airport) fails, second call (wdutil) succeeds
            mock_subprocess.run.side_effect = [
                MagicMock(returncode=1, stdout=""),
                MagicMock(
                    returncode=0,
                    stdout="RSSI: -60 dBm\nNoise: -95 dBm\nChannel: 11\nSSID: TestNet\n",
                ),
            ]

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert envelope.metrics[0].fields["rssi_dbm"] == -60
            assert envelope.notes[0] == "Method: wdutil"

    def test_macos_fallback_to_system_profiler(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            # Both airport and wdutil fail, system_profiler succeeds
            mock_subprocess.run.side_effect = [
                MagicMock(returncode=1, stdout=""),
                MagicMock(returncode=1, stdout=""),
                MagicMock(
                    returncode=0,
                    stdout="Signal / Noise: -65 dBm / -90 dBm\nChannel: 6\nNetwork: MyWiFi\n",
                ),
            ]

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert envelope.metrics[0].fields["rssi_dbm"] == -65
            assert envelope.notes[0] == "Method: system_profiler"

    def test_macos_all_methods_fail(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(returncode=1, stdout="")

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert envelope.notes[0] == "Method: unavailable"
            assert len(envelope.metrics) == 0

    def test_linux_collection(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0, stdout="signal: -50 dBm\nssid TestNetwork\nfreq: 2437\n"
            )

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert envelope.metrics[0].fields["rssi_dbm"] == -50
            assert envelope.metrics[0].fields["ssid"] == "TestNetwork"
            assert envelope.notes[0] == "Method: iw"

    def test_linux_collection_failure(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(returncode=1, stdout="")

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert envelope.notes[0] == "Method: unavailable"
            assert len(envelope.metrics) == 0

    def test_high_beacon_loss_event(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0, stdout="agrCtlRSSI: -55\nbeaconLostCount: 15\n"
            )

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            beacon_events = [e for e in envelope.events if e.event_type == "high_beacon_loss"]
            assert len(beacon_events) == 1

    def test_macos_parsing_edge_cases(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "     agrCtlRSSI: -55\n"
                    "     agrCtlNoise: -90\n"
                    "     channel: 36\n"
                    "     lastTxRate: 866\n"
                    "     maxRate: 1300\n"
                    "     SSID: Test Network With Spaces\n"
                    "     BSSID: aa:bb:cc:dd:ee:ff\n"
                    "     CC: US\n"
                ),
            )

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            metric = envelope.metrics[0]
            assert metric.fields["tx_rate_mbps"] == 866
            assert metric.fields["max_rate_mbps"] == 1300
            assert metric.fields["ssid"] == "Test Network With Spaces"
            assert metric.fields["bssid"] == "aa:bb:cc:dd:ee:ff"
            assert metric.fields["country_code"] == "US"

    def test_linux_frequency_to_channel_conversion(self):
        with (
            patch("beacon.collectors.wifi.platform") as mock_platform,
            patch("beacon.collectors.wifi.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout="signal: -50 dBm\nssid TestNetwork\nfreq: 2412\n",  # Channel 1
            )

            collector = WiFiCollector()
            envelope = collector.collect(uuid4())

            assert envelope.metrics[0].fields["channel"] == 1


class TestPathCollector:
    def test_gateway_reachable(self):
        with (
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
            patch("beacon.collectors.path.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.\n"
                    "--- 192.168.1.1 ping statistics ---\n"
                    "5 packets transmitted, 5 received, 0% packet loss, time 4005ms\n"
                    "rtt min/avg/max/mdev = 0.5/1.2/2.0/0.5 ms\n"
                ),
            )

            collector = PathCollector(gateway="192.168.1.1")
            envelope = collector.collect(uuid4())

            assert envelope.plugin_name == "path"
            assert len(envelope.metrics) >= 1
            assert envelope.metrics[0].fields["reachable"] is True

    def test_gateway_unreachable(self):
        with (
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
            patch("beacon.collectors.path.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=1,
                stdout="PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.\n--- 192.168.1.1 ping statistics ---\n5 packets transmitted, 0 received, 100% packet loss\n",
            )

            collector = PathCollector(gateway="192.168.1.1")
            envelope = collector.collect(uuid4())

            unreachable_events = [
                e for e in envelope.events if e.event_type == "gateway_unreachable"
            ]
            assert len(unreachable_events) == 1

    def test_no_gateway_detected(self):
        with patch("beacon.collectors.path._detect_gateway", return_value=None):
            collector = PathCollector()
            envelope = collector.collect(uuid4())
            assert any("Could not detect" in n for n in envelope.notes)

    def test_ping_timeout_error(self):
        with (
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
            patch("beacon.collectors.path.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.side_effect = subprocess.TimeoutExpired("ping", 10)

            collector = PathCollector(gateway="192.168.1.1")
            envelope = collector.collect(uuid4())

            timeout_events = [e for e in envelope.events if e.event_type == "ping_timeout"]
            assert len(timeout_events) == 1

    def test_ping_exception_error(self):
        with (
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
            patch("beacon.collectors.path.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.side_effect = Exception("Network error")

            collector = PathCollector(gateway="192.168.1.1")
            envelope = collector.collect(uuid4())

            error_events = [e for e in envelope.events if e.event_type == "ping_error"]
            assert len(error_events) == 1

    def test_macos_ping_parsing(self):
        with (
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
            patch("beacon.collectors.path.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "PING 192.168.1.1 (192.168.1.1): 56 data bytes\n"
                    "--- 192.168.1.1 ping statistics ---\n"
                    "5 packets transmitted, 5 packets received, 0.0% packet loss\n"
                    "round-trip min/avg/max/stddev = 0.5/1.2/2.0/0.5 ms\n"
                ),
            )

            collector = PathCollector(gateway="192.168.1.1")
            envelope = collector.collect(uuid4())

            metric = envelope.metrics[0]
            assert metric.fields["reachable"] is True
            assert metric.fields["rtt_avg_ms"] == 1.2
            assert metric.fields["packet_loss_pct"] == 0.0

    def test_partial_packet_loss(self):
        with (
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
            patch("beacon.collectors.path.platform") as mock_platform,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.\n"
                    "--- 192.168.1.1 ping statistics ---\n"
                    "5 packets transmitted, 3 received, 40% packet loss, time 4005ms\n"
                    "rtt min/avg/max/mdev = 0.5/1.2/2.0/0.5 ms\n"
                ),
            )

            collector = PathCollector(gateway="192.168.1.1")
            envelope = collector.collect(uuid4())

            metric = envelope.metrics[0]
            assert metric.fields["packet_loss_pct"] == 40.0

            loss_events = [e for e in envelope.events if e.event_type == "packet_loss"]
            assert len(loss_events) == 1


class TestDetectGateway:
    def test_detect_gateway_darwin(self):
        with (
            patch("beacon.collectors.path.platform") as mock_platform,
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Darwin"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0,
                stdout="   route to: default\ndestination: default\n       mask: default\n    gateway: 192.168.1.1\n",
            )

            gateway = _detect_gateway()
            assert gateway == "192.168.1.1"

    def test_detect_gateway_linux(self):
        with (
            patch("beacon.collectors.path.platform") as mock_platform,
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0, stdout="default via 192.168.1.1 dev eth0 proto dhcp metric 100\n"
            )

            gateway = _detect_gateway()
            assert gateway == "192.168.1.1"

    def test_detect_gateway_failure(self):
        with (
            patch("beacon.collectors.path.platform") as mock_platform,
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.side_effect = Exception("Command failed")

            gateway = _detect_gateway()
            assert gateway is None

    def test_detect_gateway_no_via_keyword(self):
        with (
            patch("beacon.collectors.path.platform") as mock_platform,
            patch("beacon.collectors.path.subprocess") as mock_subprocess,
        ):
            mock_platform.system.return_value = "Linux"
            mock_subprocess.run.return_value = MagicMock(
                returncode=0, stdout="default dev eth0 proto dhcp metric 100\n"
            )

            gateway = _detect_gateway()
            assert gateway is None
