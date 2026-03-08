"""Unit tests for environment snapshot capture."""

from __future__ import annotations

from unittest.mock import Mock, patch

from beacon.evidence.environment import (
    capture_environment,
    _detect_gateway,
    _detect_public_ip,
)
from beacon.models.evidence import EnvironmentSnapshot


class TestCaptureEnvironment:
    @patch("beacon.evidence.environment.psutil")
    @patch("beacon.evidence.environment.socket")
    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment._detect_gateway")
    @patch("beacon.evidence.environment._detect_public_ip")
    def test_capture_environment_success(
        self, mock_public_ip, mock_gateway, mock_platform, mock_socket, mock_psutil
    ):
        # Mock platform info
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "5.4.0"
        mock_platform.machine.return_value = "x86_64"
        mock_platform.python_version.return_value = "3.11.0"

        # Mock socket
        mock_socket.gethostname.return_value = "test-host"

        # Mock network interfaces
        mock_addr_ipv4 = Mock()
        mock_addr_ipv4.family.name = "AF_INET"
        mock_addr_ipv4.address = "192.168.1.100"

        mock_addr_ipv6 = Mock()
        mock_addr_ipv6.family.name = "AF_INET6"
        mock_addr_ipv6.address = "fe80::1"

        mock_psutil.net_if_addrs.return_value = {
            "eth0": [mock_addr_ipv4, mock_addr_ipv6],
            "lo": [Mock(family=Mock(name="AF_INET"), address="127.0.0.1")],
        }

        # Mock gateway and public IP
        mock_gateway.return_value = "192.168.1.1"
        mock_public_ip.return_value = "203.0.113.1"

        result = capture_environment()

        assert isinstance(result, EnvironmentSnapshot)
        assert result.hostname == "test-host"
        assert result.os == "Linux"
        assert result.os_version == "5.4.0"
        assert result.architecture == "x86_64"
        assert result.python_version == "3.11.0"
        assert result.default_gateway == "192.168.1.1"
        assert result.public_ip == "203.0.113.1"
        assert len(result.interfaces) == 2

        # Check interface details
        eth0_interface = next(iface for iface in result.interfaces if iface["name"] == "eth0")
        assert eth0_interface["ipv4"] == "192.168.1.100"
        assert eth0_interface["ipv6"] == "fe80::1"

    @patch("beacon.evidence.environment.psutil")
    @patch("beacon.evidence.environment.socket")
    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment._detect_gateway")
    @patch("beacon.evidence.environment._detect_public_ip")
    def test_capture_environment_interface_exception(
        self, mock_public_ip, mock_gateway, mock_platform, mock_socket, mock_psutil
    ):
        # Mock basic info
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "5.4.0"
        mock_platform.machine.return_value = "x86_64"
        mock_platform.python_version.return_value = "3.11.0"
        mock_socket.gethostname.return_value = "test-host"

        # Mock interface enumeration failure
        mock_psutil.net_if_addrs.side_effect = Exception("Interface error")

        mock_gateway.return_value = None
        mock_public_ip.return_value = None

        result = capture_environment()

        assert isinstance(result, EnvironmentSnapshot)
        assert result.hostname == "test-host"
        assert result.interfaces == []  # Should be empty due to exception

    @patch("beacon.evidence.environment.psutil")
    @patch("beacon.evidence.environment.socket")
    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment._detect_gateway")
    @patch("beacon.evidence.environment._detect_public_ip")
    def test_capture_environment_ipv4_only(
        self, mock_public_ip, mock_gateway, mock_platform, mock_socket, mock_psutil
    ):
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "5.4.0"
        mock_platform.machine.return_value = "x86_64"
        mock_platform.python_version.return_value = "3.11.0"
        mock_socket.gethostname.return_value = "test-host"

        # Mock interface with only IPv4
        mock_addr_ipv4 = Mock()
        mock_addr_ipv4.family.name = "AF_INET"
        mock_addr_ipv4.address = "192.168.1.100"

        mock_psutil.net_if_addrs.return_value = {
            "eth0": [mock_addr_ipv4],
        }

        mock_gateway.return_value = None
        mock_public_ip.return_value = None

        result = capture_environment()

        assert len(result.interfaces) == 1
        assert result.interfaces[0]["name"] == "eth0"
        assert result.interfaces[0]["ipv4"] == "192.168.1.100"
        assert "ipv6" not in result.interfaces[0]

    @patch("beacon.evidence.environment.psutil")
    @patch("beacon.evidence.environment.socket")
    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment._detect_gateway")
    @patch("beacon.evidence.environment._detect_public_ip")
    def test_capture_environment_no_ip_addresses(
        self, mock_public_ip, mock_gateway, mock_platform, mock_socket, mock_psutil
    ):
        mock_platform.system.return_value = "Linux"
        mock_platform.release.return_value = "5.4.0"
        mock_platform.machine.return_value = "x86_64"
        mock_platform.python_version.return_value = "3.11.0"
        mock_socket.gethostname.return_value = "test-host"

        # Mock interface with no IP addresses (e.g., only MAC address)
        mock_addr_mac = Mock()
        mock_addr_mac.family.name = "AF_LINK"
        mock_addr_mac.address = "aa:bb:cc:dd:ee:ff"

        mock_psutil.net_if_addrs.return_value = {
            "eth0": [mock_addr_mac],
        }

        mock_gateway.return_value = None
        mock_public_ip.return_value = None

        result = capture_environment()

        # Interface should be excluded since it has no IP addresses
        assert len(result.interfaces) == 0


class TestDetectGateway:
    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment.subprocess")
    def test_detect_gateway_darwin_success(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"

        mock_result = Mock()
        mock_result.stdout = "   route to: default\ndestination: default\n       mask: default\n    gateway: 192.168.1.1\n  interface: en0\n"
        mock_subprocess.run.return_value = mock_result

        gateway = _detect_gateway()

        assert gateway == "192.168.1.1"
        mock_subprocess.run.assert_called_once_with(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment.subprocess")
    def test_detect_gateway_linux_success(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Linux"

        mock_result = Mock()
        mock_result.stdout = "default via 192.168.1.1 dev eth0 proto dhcp metric 100"
        mock_subprocess.run.return_value = mock_result

        gateway = _detect_gateway()

        assert gateway == "192.168.1.1"
        mock_subprocess.run.assert_called_once_with(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment.subprocess")
    def test_detect_gateway_darwin_no_gateway(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"

        mock_result = Mock()
        mock_result.stdout = "route to: default\ndestination: default\n"
        mock_subprocess.run.return_value = mock_result

        gateway = _detect_gateway()

        assert gateway is None

    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment.subprocess")
    def test_detect_gateway_linux_no_via(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Linux"

        mock_result = Mock()
        mock_result.stdout = "default dev eth0 proto dhcp metric 100"
        mock_subprocess.run.return_value = mock_result

        gateway = _detect_gateway()

        assert gateway is None

    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment.subprocess")
    def test_detect_gateway_subprocess_exception(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Linux"
        mock_subprocess.run.side_effect = Exception("Command failed")

        gateway = _detect_gateway()

        assert gateway is None

    @patch("beacon.evidence.environment.platform")
    def test_detect_gateway_unsupported_platform(self, mock_platform):
        mock_platform.system.return_value = "Windows"

        gateway = _detect_gateway()

        assert gateway is None

    @patch("beacon.evidence.environment.platform")
    @patch("beacon.evidence.environment.subprocess")
    def test_detect_gateway_timeout(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Linux"
        mock_subprocess.run.side_effect = Exception("Timeout")

        gateway = _detect_gateway()

        assert gateway is None


class TestDetectPublicIp:
    @patch("beacon.evidence.environment.httpx")
    def test_detect_public_ip_success(self, mock_httpx):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "203.0.113.1"
        mock_httpx.get.return_value = mock_response

        public_ip = _detect_public_ip()

        assert public_ip == "203.0.113.1"
        mock_httpx.get.assert_called_once_with("https://api.ipify.org", timeout=5)

    @patch("beacon.evidence.environment.httpx")
    def test_detect_public_ip_with_whitespace(self, mock_httpx):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "  203.0.113.1  \n"
        mock_httpx.get.return_value = mock_response

        public_ip = _detect_public_ip()

        assert public_ip == "203.0.113.1"

    @patch("beacon.evidence.environment.httpx")
    def test_detect_public_ip_http_error(self, mock_httpx):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_httpx.get.return_value = mock_response

        public_ip = _detect_public_ip()

        assert public_ip is None

    @patch("beacon.evidence.environment.httpx")
    def test_detect_public_ip_exception(self, mock_httpx):
        mock_httpx.get.side_effect = Exception("Network error")

        public_ip = _detect_public_ip()

        assert public_ip is None

    @patch("beacon.evidence.environment.httpx")
    def test_detect_public_ip_timeout(self, mock_httpx):
        mock_httpx.get.side_effect = Exception("Timeout")

        public_ip = _detect_public_ip()

        assert public_ip is None
