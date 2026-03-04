"""Wi-Fi collector — RSSI, noise, channel, retry rate.

On macOS, tries a fallback stack since the airport binary is deprecated
and removed on newer versions:
  1. airport -I         (fast, detailed — but often missing)
  2. wdutil info        (requires sudo — works in privileged sidecar)
  3. system_profiler    (unprivileged, slower, still gives Signal/Noise/Channel)
  4. unavailable        (records capability note, not a failure)

On Linux, uses iw dev / iw link.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from uuid import UUID

from beacon.collectors.base import BaseCollector
from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity

logger = logging.getLogger(__name__)

# macOS airport binary path (removed in newer versions)
_AIRPORT_PATH = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"


class WiFiCollector(BaseCollector):
    name = "wifi"
    version = "0.2.0"

    def collect(self, run_id: UUID) -> PluginEnvelope:
        started_at = self._now()
        metrics: list[Metric] = []
        events: list[Event] = []
        notes: list[str] = []
        now = self._now()

        system = platform.system()
        method = "unavailable"

        try:
            if system == "Darwin":
                method = self._collect_macos(metrics, events, notes, now)
            elif system == "Linux":
                method = self._collect_linux(metrics, events, notes, now)
            else:
                notes.append(f"Wi-Fi collection not supported on {system}")
        except Exception as e:
            notes.append(f"Wi-Fi collection error: {e}")
            logger.warning("Wi-Fi collection failed: %s", e)

        # Tag all metrics with the collection method
        for m in metrics:
            m.tags["wifi_method"] = method

        if method == "unavailable":
            notes.append("Wi-Fi metrics unavailable — no supported tool found on this host")

        return PluginEnvelope(
            plugin_name=self.name,
            plugin_version=self.version,
            run_id=run_id,
            metrics=metrics,
            events=events,
            notes=notes,
            started_at=started_at,
            completed_at=self._now(),
        )

    # ── macOS fallback stack ────────────────────────────────────────

    def _collect_macos(
        self,
        metrics: list[Metric],
        events: list[Event],
        notes: list[str],
        now,
    ) -> str:
        """Try each macOS Wi-Fi tool in priority order. Returns method name."""
        # 1. airport (fast, detailed, but often gone)
        try:
            if self._try_airport(metrics, events, notes, now):
                return "airport"
        except (FileNotFoundError, OSError):
            pass

        # 2. wdutil info (requires sudo — works in privileged sidecar)
        try:
            if self._try_wdutil(metrics, events, notes, now):
                return "wdutil"
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass

        # 3. system_profiler SPAirPortDataType (unprivileged, slower)
        try:
            if self._try_system_profiler(metrics, events, notes, now):
                return "system_profiler"
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass

        return "unavailable"

    def _try_airport(
        self,
        metrics: list[Metric],
        events: list[Event],
        notes: list[str],
        now,
    ) -> bool:
        """Collect via airport -I. Returns True if successful."""
        result = subprocess.run(
            [_AIRPORT_PATH, "-I"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False

        fields = self._parse_airport(result.stdout)
        if not fields:
            return False

        self._emit_wifi_metric(fields, "en0", metrics, events, now)
        return True

    def _try_wdutil(
        self,
        metrics: list[Metric],
        events: list[Event],
        notes: list[str],
        now,
    ) -> bool:
        """Collect via wdutil info (requires sudo). Returns True if successful."""
        result = subprocess.run(
            ["wdutil", "info"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False

        fields = self._parse_wdutil(result.stdout)
        if not fields:
            return False

        self._emit_wifi_metric(fields, "en0", metrics, events, now)
        return True

    def _try_system_profiler(
        self,
        metrics: list[Metric],
        events: list[Event],
        notes: list[str],
        now,
    ) -> bool:
        """Collect via system_profiler SPAirPortDataType. Returns True if successful."""
        result = subprocess.run(
            ["system_profiler", "SPAirPortDataType"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return False

        fields, iface = self._parse_system_profiler(result.stdout)
        if not fields:
            return False

        self._emit_wifi_metric(fields, iface, metrics, events, now)
        return True

    # ── Parsers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_airport(output: str) -> dict[str, float | int | str | bool]:
        """Parse airport -I output into metric fields."""
        fields: dict[str, float | int | str | bool] = {}
        for line in output.splitlines():
            line = line.strip()
            if ": " not in line:
                continue
            key, _, value = line.partition(": ")
            key = key.strip().lower()
            value = value.strip()

            if key == "agrctlrssi":
                fields["rssi_dbm"] = int(value)
            elif key == "agrctlnoise":
                fields["noise_dbm"] = int(value)
            elif key == "channel":
                fields["channel"] = value
            elif key == "lastassocstatus":
                fields["last_assoc_status"] = int(value)
            elif key == "ssid":
                fields["ssid"] = value
            elif key == "bssid":
                fields["bssid"] = value

        return fields

    @staticmethod
    def _parse_wdutil(output: str) -> dict[str, float | int | str | bool]:
        """Parse wdutil info output into metric fields."""
        fields: dict[str, float | int | str | bool] = {}
        for line in output.splitlines():
            line = line.strip()
            if ": " not in line:
                continue
            key, _, value = line.partition(": ")
            key = key.strip().lower()
            value = value.strip()

            if key == "rssi":
                m = re.search(r"(-?\d+)", value)
                if m:
                    fields["rssi_dbm"] = int(m.group(1))
            elif key == "noise":
                m = re.search(r"(-?\d+)", value)
                if m:
                    fields["noise_dbm"] = int(m.group(1))
            elif key == "channel":
                fields["channel"] = value
            elif key == "ssid":
                fields["ssid"] = value
            elif key == "bssid":
                fields["bssid"] = value

        return fields

    @staticmethod
    def _parse_system_profiler(output: str) -> tuple[dict[str, float | int | str | bool], str]:
        """Parse system_profiler SPAirPortDataType output.

        Returns (fields, interface_name).
        """
        fields: dict[str, float | int | str | bool] = {}
        iface = "en0"

        # Find the active interface section
        in_current_network = False
        for line in output.splitlines():
            stripped = line.strip()

            # Detect interface name: "en0:" at 8-space indent
            if re.match(r"^        \w+\d+:$", line):
                iface = stripped.rstrip(":")

            # "Current Network Information:" marks the connected network block
            if "Current Network Information:" in stripped:
                in_current_network = True
                continue

            if in_current_network:
                # "Signal / Noise: -50 dBm / -90 dBm"
                sig_match = re.search(
                    r"Signal\s*/\s*Noise:\s*(-?\d+)\s*dBm\s*/\s*(-?\d+)\s*dBm", stripped
                )
                if sig_match:
                    fields["rssi_dbm"] = int(sig_match.group(1))
                    fields["noise_dbm"] = int(sig_match.group(2))

                # "Channel: 149 (5GHz, 80MHz)"
                chan_match = re.match(r"Channel:\s*(.+)", stripped)
                if chan_match:
                    fields["channel"] = chan_match.group(1).strip()

                # "PHY Mode: 802.11ax"
                phy_match = re.match(r"PHY Mode:\s*(.+)", stripped)
                if phy_match:
                    fields["phy_mode"] = phy_match.group(1).strip()

                # "Transmit Rate: 1080"
                tx_match = re.match(r"Transmit Rate:\s*(\d+)", stripped)
                if tx_match:
                    fields["tx_rate_mbps"] = int(tx_match.group(1))

                # "MCS Index: 10"
                mcs_match = re.match(r"MCS Index:\s*(\d+)", stripped)
                if mcs_match:
                    fields["mcs_index"] = int(mcs_match.group(1))

                # Network name (SSID) is the key of the block: "  MyNetwork:"
                # It appears as a line with just the name and a colon right after
                # "Current Network Information:"
                ssid_match = re.match(r"^              (\S.*):$", line)
                if ssid_match and ":" not in ssid_match.group(1).rstrip(":"):
                    fields["ssid"] = ssid_match.group(1)

                # "Other Local Wi-Fi Networks:" ends the current network block
                if "Other Local Wi-Fi Networks:" in stripped:
                    break

            # "Status: Connected" / "Status: Not Connected"
            if stripped.startswith("Status:"):
                fields["connected"] = "Connected" in stripped and "Not" not in stripped

        return fields, iface

    # ── Shared metric emission ─────────────────────────────────────

    def _emit_wifi_metric(
        self,
        fields: dict[str, float | int | str | bool],
        iface: str,
        metrics: list[Metric],
        events: list[Event],
        now,
    ) -> None:
        """Create wifi_link metric and fire events if needed."""
        rssi = fields.get("rssi_dbm")
        noise = fields.get("noise_dbm")

        # Compute SNR before creating metric (Pydantic copies the dict)
        if isinstance(rssi, (int, float)) and isinstance(noise, (int, float)):
            fields["snr_db"] = rssi - noise

        metrics.append(Metric(
            measurement="wifi_link",
            fields=fields,
            tags={"interface": iface},
            timestamp=now,
        ))

        if isinstance(rssi, (int, float)) and rssi < -75:
            events.append(Event(
                event_type="weak_signal",
                severity=Severity.WARNING,
                message=f"Wi-Fi signal is weak: {rssi} dBm",
                tags={"interface": iface},
                timestamp=now,
            ))

        snr = fields.get("snr_db")
        if isinstance(snr, (int, float)) and snr < 15:
            events.append(Event(
                event_type="low_snr",
                severity=Severity.WARNING,
                message=f"Low signal-to-noise ratio: {snr} dB",
                tags={"interface": iface},
                timestamp=now,
            ))

    # ── Linux ──────────────────────────────────────────────────────

    def _collect_linux(
        self,
        metrics: list[Metric],
        events: list[Event],
        notes: list[str],
        now,
    ) -> str:
        """Collect Wi-Fi metrics on Linux via iw."""
        result = subprocess.run(
            ["iw", "dev"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            notes.append("iw dev failed — no wireless interfaces?")
            return "unavailable"

        interfaces: list[str] = []
        for line in result.stdout.splitlines():
            m = re.match(r"\s+Interface\s+(\S+)", line)
            if m:
                interfaces.append(m.group(1))

        if not interfaces:
            return "unavailable"

        for iface in interfaces:
            link = subprocess.run(
                ["iw", iface, "link"],
                capture_output=True, text=True, timeout=10,
            )
            if "Not connected" in link.stdout:
                notes.append(f"{iface} is not connected")
                continue

            fields: dict[str, float | int | str | bool] = {}
            for line in link.stdout.splitlines():
                line = line.strip()
                if "signal:" in line:
                    m = re.search(r"signal:\s*(-?\d+)", line)
                    if m:
                        fields["rssi_dbm"] = int(m.group(1))
                elif "tx bitrate:" in line:
                    m = re.search(r"tx bitrate:\s*([\d.]+)", line)
                    if m:
                        fields["tx_rate_mbps"] = float(m.group(1))
                elif "freq:" in line:
                    m = re.search(r"freq:\s*(\d+)", line)
                    if m:
                        fields["frequency_mhz"] = int(m.group(1))
                elif "SSID:" in line:
                    fields["ssid"] = line.split("SSID:")[1].strip()

            if fields:
                self._emit_wifi_metric(fields, iface, metrics, events, now)

        return "iw"
