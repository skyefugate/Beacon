"""Environment snapshot capture — records host details at diagnostic time."""

from __future__ import annotations

import logging
import platform
import socket

import psutil

from beacon.models.evidence import EnvironmentSnapshot

logger = logging.getLogger(__name__)


def capture_environment() -> EnvironmentSnapshot:
    """Capture the current host environment."""
    interfaces = []
    try:
        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            iface_info: dict = {"name": iface}
            for addr in addr_list:
                if addr.family.name == "AF_INET":
                    iface_info["ipv4"] = addr.address
                elif addr.family.name == "AF_INET6":
                    iface_info["ipv6"] = addr.address
            if "ipv4" in iface_info or "ipv6" in iface_info:
                interfaces.append(iface_info)
    except Exception:
        logger.debug("Failed to enumerate interfaces", exc_info=True)

    gateway = _detect_gateway()
    public_ip = _detect_public_ip()

    return EnvironmentSnapshot(
        hostname=socket.gethostname(),
        os=platform.system(),
        os_version=platform.release(),
        architecture=platform.machine(),
        python_version=platform.python_version(),
        interfaces=interfaces,
        default_gateway=gateway,
        public_ip=public_ip,
    )


def _detect_gateway() -> str | None:
    """Best-effort gateway detection."""
    try:
        import subprocess
        system = platform.system()
        if system == "Darwin":
            result = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "gateway:" in line:
                    return line.split("gateway:")[-1].strip()
        elif system == "Linux":
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5,
            )
            parts = result.stdout.strip().split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except Exception:
        pass
    return None


def _detect_public_ip() -> str | None:
    """Best-effort public IP detection via HTTPS."""
    try:
        import httpx
        response = httpx.get("https://api.ipify.org", timeout=5)
        if response.status_code == 200:
            return response.text.strip()
    except Exception:
        pass
    return None
