"""Unit tests for collectors — using mocks to avoid requiring real hardware/privileges."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4


from beacon.collectors.device import DeviceCollector
from beacon.collectors.lan import LANCollector
from beacon.collectors.wifi import WiFiCollector
from beacon.collectors.path import PathCollector


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
