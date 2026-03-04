"""Wi-Fi event detection — deauthentication, disassociation, and roaming events.

These events are detected by analyzing Wi-Fi metrics over time. In MVP-0,
we detect them from the collector's metric snapshots rather than real-time
frame analysis.
"""

from __future__ import annotations

from beacon.models.envelope import Event, Metric, Severity


class WiFiEventDetector:
    """Detects Wi-Fi events from collected metrics."""

    def __init__(self) -> None:
        self._previous_ssid: str | None = None
        self._previous_bssid: str | None = None

    def analyze(self, metrics: list[Metric]) -> list[Event]:
        """Analyze Wi-Fi metrics for notable events."""
        events: list[Event] = []

        wifi_metrics = [m for m in metrics if m.measurement == "wifi_link"]

        for metric in wifi_metrics:
            # Detect SSID change (roaming)
            current_ssid = metric.fields.get("ssid")
            if isinstance(current_ssid, str) and self._previous_ssid is not None:
                if current_ssid != self._previous_ssid:
                    events.append(
                        Event(
                            event_type="wifi_roam",
                            severity=Severity.INFO,
                            message=f"SSID changed from {self._previous_ssid} to {current_ssid}",
                            tags=metric.tags,
                            timestamp=metric.timestamp,
                        )
                    )
            if isinstance(current_ssid, str):
                self._previous_ssid = current_ssid

            # Detect BSSID change (AP roaming within same SSID)
            current_bssid = metric.fields.get("bssid")
            if isinstance(current_bssid, str) and self._previous_bssid is not None:
                if current_bssid != self._previous_bssid:
                    events.append(
                        Event(
                            event_type="wifi_ap_roam",
                            severity=Severity.INFO,
                            message=f"AP changed from {self._previous_bssid} to {current_bssid}",
                            tags=metric.tags,
                            timestamp=metric.timestamp,
                        )
                    )
            if isinstance(current_bssid, str):
                self._previous_bssid = current_bssid

            # Detect association failure
            assoc_status = metric.fields.get("last_assoc_status")
            if isinstance(assoc_status, (int, float)) and assoc_status != 0:
                events.append(
                    Event(
                        event_type="wifi_assoc_failure",
                        severity=Severity.CRITICAL,
                        message=f"Wi-Fi association failure (status: {assoc_status})",
                        tags=metric.tags,
                        timestamp=metric.timestamp,
                    )
                )

            # Detect very poor signal
            rssi = metric.fields.get("rssi_dbm")
            if isinstance(rssi, (int, float)) and rssi < -85:
                events.append(
                    Event(
                        event_type="wifi_critical_signal",
                        severity=Severity.CRITICAL,
                        message=f"Wi-Fi signal critically low: {rssi} dBm",
                        tags=metric.tags,
                        timestamp=metric.timestamp,
                    )
                )

            # Detect high noise floor
            noise = metric.fields.get("noise_dbm")
            if isinstance(noise, (int, float)) and isinstance(rssi, (int, float)):
                snr = rssi - noise
                if snr < 15:
                    events.append(
                        Event(
                            event_type="wifi_low_snr",
                            severity=Severity.WARNING,
                            message=f"Wi-Fi SNR critically low: {snr} dB (RSSI: {rssi}, Noise: {noise})",
                            tags=metric.tags,
                            timestamp=metric.timestamp,
                        )
                    )

        return events
