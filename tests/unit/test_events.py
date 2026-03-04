"""Unit tests for event detection — thresholds, Wi-Fi events, link flaps."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from beacon.events.threshold import ThresholdMonitor, ThresholdRule
from beacon.events.wifi_events import WiFiEventDetector
from beacon.events.link_events import LinkFlapDetector
from beacon.models.envelope import Metric, Severity


def _now():
    return datetime.now(timezone.utc)


class TestThresholdMonitor:
    def test_breach_detected(self):
        monitor = ThresholdMonitor()
        metrics = [
            Metric(
                measurement="ping",
                fields={"loss_pct": 15.0, "rtt_avg_ms": 50.0},
                tags={"target": "8.8.8.8"},
                timestamp=_now(),
            )
        ]
        events = monitor.evaluate(metrics)
        assert len(events) >= 1
        assert any(e.event_type == "threshold_breach" for e in events)

    def test_no_breach(self):
        monitor = ThresholdMonitor()
        metrics = [
            Metric(
                measurement="ping",
                fields={"loss_pct": 0.0, "rtt_avg_ms": 15.0},
                tags={"target": "8.8.8.8"},
                timestamp=_now(),
            )
        ]
        events = monitor.evaluate(metrics)
        assert len(events) == 0

    def test_custom_threshold(self):
        rule = ThresholdRule(
            measurement="custom",
            field="value",
            operator=">=",
            value=100.0,
            severity=Severity.CRITICAL,
            message_template="Custom threshold breached: {actual}",
        )
        monitor = ThresholdMonitor(rules=[rule])
        metrics = [
            Metric(
                measurement="custom",
                fields={"value": 150.0},
                timestamp=_now(),
            )
        ]
        events = monitor.evaluate(metrics)
        assert len(events) == 1
        assert events[0].severity == Severity.CRITICAL

    def test_less_than_operator(self):
        rule = ThresholdRule(
            measurement="wifi_link",
            field="rssi_dbm",
            operator="<",
            value=-75.0,
        )
        monitor = ThresholdMonitor(rules=[rule])
        metrics = [
            Metric(
                measurement="wifi_link",
                fields={"rssi_dbm": -80},
                timestamp=_now(),
            )
        ]
        events = monitor.evaluate(metrics)
        assert len(events) == 1

    def test_tags_filter(self):
        rule = ThresholdRule(
            measurement="ping",
            field="loss_pct",
            operator=">",
            value=5.0,
            tags_filter={"target": "8.8.8.8"},
        )
        monitor = ThresholdMonitor(rules=[rule])

        # Matching tag
        events = monitor.evaluate([
            Metric(
                measurement="ping",
                fields={"loss_pct": 10.0},
                tags={"target": "8.8.8.8"},
                timestamp=_now(),
            )
        ])
        assert len(events) == 1

        # Non-matching tag
        events = monitor.evaluate([
            Metric(
                measurement="ping",
                fields={"loss_pct": 10.0},
                tags={"target": "1.1.1.1"},
                timestamp=_now(),
            )
        ])
        assert len(events) == 0

    def test_non_numeric_field_skipped(self):
        rule = ThresholdRule(measurement="test", field="name", operator=">", value=5.0)
        monitor = ThresholdMonitor(rules=[rule])
        events = monitor.evaluate([
            Metric(
                measurement="test",
                fields={"name": "hello"},
                timestamp=_now(),
            )
        ])
        assert len(events) == 0


class TestWiFiEventDetector:
    def test_ssid_roam_detected(self):
        detector = WiFiEventDetector()
        detector._previous_ssid = "OldNetwork"
        metrics = [
            Metric(
                measurement="wifi_link",
                fields={"ssid": "NewNetwork", "rssi_dbm": -60},
                timestamp=_now(),
            )
        ]
        events = detector.analyze(metrics)
        roam_events = [e for e in events if e.event_type == "wifi_roam"]
        assert len(roam_events) == 1

    def test_critical_signal(self):
        detector = WiFiEventDetector()
        metrics = [
            Metric(
                measurement="wifi_link",
                fields={"rssi_dbm": -90},
                timestamp=_now(),
            )
        ]
        events = detector.analyze(metrics)
        critical_events = [e for e in events if e.event_type == "wifi_critical_signal"]
        assert len(critical_events) == 1

    def test_low_snr(self):
        detector = WiFiEventDetector()
        metrics = [
            Metric(
                measurement="wifi_link",
                fields={"rssi_dbm": -70, "noise_dbm": -60},
                timestamp=_now(),
            )
        ]
        events = detector.analyze(metrics)
        snr_events = [e for e in events if e.event_type == "wifi_low_snr"]
        assert len(snr_events) == 1

    def test_normal_signal_no_events(self):
        detector = WiFiEventDetector()
        metrics = [
            Metric(
                measurement="wifi_link",
                fields={"rssi_dbm": -55, "noise_dbm": -90},
                timestamp=_now(),
            )
        ]
        events = detector.analyze(metrics)
        assert len(events) == 0

    def test_assoc_failure(self):
        detector = WiFiEventDetector()
        metrics = [
            Metric(
                measurement="wifi_link",
                fields={"last_assoc_status": 1},
                timestamp=_now(),
            )
        ]
        events = detector.analyze(metrics)
        assoc_events = [e for e in events if e.event_type == "wifi_assoc_failure"]
        assert len(assoc_events) == 1


class TestLinkFlapDetector:
    def test_link_down_detected(self):
        detector = LinkFlapDetector()
        metrics = [
            Metric(
                measurement="lan_status",
                fields={"is_up": False, "speed_mbps": 0, "mtu": 1500},
                tags={"interface": "eth0"},
                timestamp=_now(),
            )
        ]
        events = detector.analyze(metrics)
        down_events = [e for e in events if e.event_type == "link_down"]
        assert len(down_events) == 1

    def test_link_flap_detected(self):
        detector = LinkFlapDetector(flap_threshold=3)
        states = [True, False, True, False, True]
        all_events = []
        for is_up in states:
            metrics = [
                Metric(
                    measurement="lan_status",
                    fields={"is_up": is_up, "speed_mbps": 1000, "mtu": 1500},
                    tags={"interface": "eth0"},
                    timestamp=_now(),
                )
            ]
            all_events.extend(detector.analyze(metrics))

        flap_events = [e for e in all_events if e.event_type == "link_flap"]
        assert len(flap_events) >= 1

    def test_stable_link_no_flap(self):
        detector = LinkFlapDetector(flap_threshold=3)
        for _ in range(5):
            metrics = [
                Metric(
                    measurement="lan_status",
                    fields={"is_up": True, "speed_mbps": 1000, "mtu": 1500},
                    tags={"interface": "eth0"},
                    timestamp=_now(),
                )
            ]
            events = detector.analyze(metrics)
            flap_events = [e for e in events if e.event_type == "link_flap"]
            assert len(flap_events) == 0
