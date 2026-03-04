"""Tests for telemetry trigger evaluator."""

from __future__ import annotations

from datetime import datetime, timezone


from beacon.models.envelope import Severity
from beacon.telemetry.aggregator import AggregatedWindow
from beacon.telemetry.triggers import (
    TriggerEvaluator,
    TriggerRule,
    TriggerType,
)


def _make_window(
    measurement: str = "t_internet_rtt",
    field_name: str = "rtt_avg_ms",
    p50: float = 20.0,
    p95: float = 50.0,
    p99: float = 80.0,
    mean: float = 25.0,
    **kwargs,
) -> AggregatedWindow:
    now = datetime.now(timezone.utc)
    return AggregatedWindow(
        measurement=measurement,
        tags=kwargs.get("tags", {}),
        field_name=field_name,
        count=10,
        mean=mean,
        min=kwargs.get("min_val", 5.0),
        max=kwargs.get("max_val", 100.0),
        p50=p50,
        p95=p95,
        p99=p99,
        jitter=kwargs.get("jitter", 2.0),
        window_start=now,
        window_end=now,
    )


class TestTriggerEvaluator:
    def test_threshold_fires_when_exceeded(self):
        rule = TriggerRule(
            name="test_high_rtt",
            measurement="t_internet_rtt",
            field_name="rtt_avg_ms",
            stat="p95",
            operator=">",
            value=100.0,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [_make_window(p95=150.0)]

        results = evaluator.evaluate(windows)
        assert len(results) == 1
        assert results[0].fired is True
        assert results[0].event is not None
        assert "trigger:test_high_rtt" == results[0].event.event_type

    def test_threshold_does_not_fire_below(self):
        rule = TriggerRule(
            name="test_high_rtt",
            measurement="t_internet_rtt",
            field_name="rtt_avg_ms",
            stat="p95",
            operator=">",
            value=100.0,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [_make_window(p95=50.0)]

        results = evaluator.evaluate(windows)
        assert len(results) == 1
        assert results[0].fired is False
        assert results[0].event is None

    def test_less_than_operator(self):
        rule = TriggerRule(
            name="wifi_weak",
            measurement="t_wifi_link",
            field_name="rssi_dbm",
            stat="mean",
            operator="<",
            value=-75.0,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_wifi_link",
                field_name="rssi_dbm",
                mean=-80.0,
            )
        ]

        results = evaluator.evaluate(windows)
        assert results[0].fired is True

    def test_tags_filter_match(self):
        rule = TriggerRule(
            name="target_rtt",
            measurement="t_internet_rtt",
            field_name="rtt_avg_ms",
            stat="p95",
            operator=">",
            value=100.0,
            tags_filter={"target": "8.8.8.8"},
        )
        evaluator = TriggerEvaluator(rules=[rule])

        # Matching tag
        w1 = _make_window(p95=150.0, tags={"target": "8.8.8.8"})
        results = evaluator.evaluate([w1])
        assert results[0].fired is True

        # Non-matching tag
        w2 = _make_window(p95=150.0, tags={"target": "1.1.1.1"})
        results = evaluator.evaluate([w2])
        assert len(results) == 0

    def test_sustained_requires_consecutive(self):
        rule = TriggerRule(
            name="sustained_rtt",
            measurement="t_internet_rtt",
            field_name="rtt_avg_ms",
            stat="p95",
            operator=">",
            value=100.0,
            trigger_type=TriggerType.SUSTAINED,
            sustained_count=3,
        )
        evaluator = TriggerEvaluator(rules=[rule])

        # Fire 3 consecutive times
        for i in range(3):
            windows = [_make_window(p95=150.0)]
            results = evaluator.evaluate(windows)
            if i < 2:
                assert results[0].fired is False
            else:
                assert results[0].fired is True

    def test_sustained_resets_on_no_fire(self):
        rule = TriggerRule(
            name="sustained_rtt",
            measurement="t_internet_rtt",
            field_name="rtt_avg_ms",
            stat="p95",
            operator=">",
            value=100.0,
            trigger_type=TriggerType.SUSTAINED,
            sustained_count=3,
        )
        evaluator = TriggerEvaluator(rules=[rule])

        # Fire twice then drop
        for _ in range(2):
            evaluator.evaluate([_make_window(p95=150.0)])
        evaluator.evaluate([_make_window(p95=50.0)])  # resets

        # Need 3 more to fire again
        for i in range(3):
            results = evaluator.evaluate([_make_window(p95=150.0)])
            if i < 2:
                assert results[0].fired is False
            else:
                assert results[0].fired is True

    def test_measurement_mismatch_skips(self):
        rule = TriggerRule(
            name="test",
            measurement="t_internet_rtt",
            field_name="rtt_avg_ms",
            stat="p95",
            operator=">",
            value=100.0,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [_make_window(measurement="t_dns_latency", p95=999.0)]
        results = evaluator.evaluate(windows)
        assert len(results) == 0

    def test_default_triggers_exist(self):
        evaluator = TriggerEvaluator()
        assert len(evaluator._rules) > 0

    def test_event_severity_matches_rule(self):
        rule = TriggerRule(
            name="critical_test",
            measurement="t_internet_rtt",
            field_name="rtt_avg_ms",
            stat="p99",
            operator=">",
            value=200.0,
            severity=Severity.CRITICAL,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        results = evaluator.evaluate([_make_window(p99=300.0)])
        assert results[0].event.severity == Severity.CRITICAL

    def test_no_windows_returns_empty(self):
        evaluator = TriggerEvaluator()
        results = evaluator.evaluate([])
        assert results == []


class TestNewDefaultTriggers:
    """Tests for memory, SNR, noise floor, and load average triggers."""

    def test_high_memory_fires(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "high_memory")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_device_health",
                field_name="memory_percent",
                mean=90.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is True

    def test_low_snr_fires(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "low_snr")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_wifi_link",
                field_name="snr_db",
                mean=10.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is True

    def test_high_noise_floor_fires(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "high_noise_floor")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_wifi_link",
                field_name="noise_dbm",
                mean=-80.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is True

    def test_high_load_avg_fires(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "high_load_avg_1m")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_device_health",
                field_name="load_avg_1m",
                mean=5.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is True


class TestDeltaTrigger:
    def test_first_call_never_fires(self):
        rule = TriggerRule(
            name="rssi_drop",
            measurement="t_wifi_link",
            field_name="rssi_dbm",
            stat="mean",
            trigger_type=TriggerType.DELTA,
            operator="<",
            value=-10.0,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [_make_window(measurement="t_wifi_link", field_name="rssi_dbm", mean=-60.0)]
        results = evaluator.evaluate(windows)
        assert results[0].fired is False  # no baseline yet

    def test_small_delta_does_not_fire(self):
        rule = TriggerRule(
            name="rssi_drop",
            measurement="t_wifi_link",
            field_name="rssi_dbm",
            stat="mean",
            trigger_type=TriggerType.DELTA,
            operator="<",
            value=-10.0,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        evaluator.evaluate(
            [_make_window(measurement="t_wifi_link", field_name="rssi_dbm", mean=-60.0)]
        )
        results = evaluator.evaluate(
            [_make_window(measurement="t_wifi_link", field_name="rssi_dbm", mean=-63.0)]
        )
        assert results[0].fired is False  # only -3 dBm drop, threshold is -10

    def test_large_delta_fires(self):
        rule = TriggerRule(
            name="rssi_drop",
            measurement="t_wifi_link",
            field_name="rssi_dbm",
            stat="mean",
            trigger_type=TriggerType.DELTA,
            operator="<",
            value=-10.0,
        )
        evaluator = TriggerEvaluator(rules=[rule])
        evaluator.evaluate(
            [_make_window(measurement="t_wifi_link", field_name="rssi_dbm", mean=-60.0)]
        )
        results = evaluator.evaluate(
            [_make_window(measurement="t_wifi_link", field_name="rssi_dbm", mean=-75.0)]
        )
        assert results[0].fired is True  # -15 dBm drop exceeds threshold
        assert results[0].event is not None


class TestDiskTriggers:
    """Tests for disk I/O latency and disk usage escalation triggers."""

    def test_high_disk_io_latency_fires(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "high_disk_io_latency")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_disk_io",
                field_name="avg_latency_ms",
                mean=150.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is True

    def test_high_disk_io_latency_does_not_fire_below_threshold(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "high_disk_io_latency")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_disk_io",
                field_name="avg_latency_ms",
                mean=50.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is False

    def test_disk_usage_critical_fires_above_90(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS, Severity

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "disk_usage_critical")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_disk_usage",
                field_name="used_percent",
                mean=95.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is True
        assert results[0].event is not None
        assert results[0].event.severity == Severity.CRITICAL

    def test_disk_usage_critical_does_not_fire_below_90(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "disk_usage_critical")
        evaluator = TriggerEvaluator(rules=[rule])
        windows = [
            _make_window(
                measurement="t_disk_usage",
                field_name="used_percent",
                mean=85.0,
            )
        ]
        results = evaluator.evaluate(windows)
        assert results[0].fired is False

    def test_disk_usage_high_is_sustained_type(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS, TriggerType

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "disk_usage_high")
        assert rule.trigger_type == TriggerType.SUSTAINED
        assert rule.severity == Severity.WARNING
        assert rule.value == 80.0

    def test_disk_usage_high_requires_consecutive_windows(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "disk_usage_high")
        evaluator = TriggerEvaluator(rules=[rule])

        # Should not fire until sustained_count consecutive windows
        for i in range(rule.sustained_count):
            windows = [
                _make_window(
                    measurement="t_disk_usage",
                    field_name="used_percent",
                    mean=85.0,
                )
            ]
            results = evaluator.evaluate(windows)
            if i < rule.sustained_count - 1:
                assert results[0].fired is False
            else:
                assert results[0].fired is True

    def test_disk_usage_high_resets_on_drop(self):
        from beacon.telemetry.triggers import DEFAULT_TRIGGERS

        rule = next(r for r in DEFAULT_TRIGGERS if r.name == "disk_usage_high")
        evaluator = TriggerEvaluator(rules=[rule])

        # Fire twice then drop below threshold
        for _ in range(rule.sustained_count - 1):
            evaluator.evaluate(
                [
                    _make_window(
                        measurement="t_disk_usage",
                        field_name="used_percent",
                        mean=85.0,
                    )
                ]
            )
        # Drop below threshold - should reset counter
        evaluator.evaluate(
            [
                _make_window(
                    measurement="t_disk_usage",
                    field_name="used_percent",
                    mean=70.0,
                )
            ]
        )

        # Need sustained_count consecutive windows again to fire
        for i in range(rule.sustained_count):
            results = evaluator.evaluate(
                [
                    _make_window(
                        measurement="t_disk_usage",
                        field_name="used_percent",
                        mean=85.0,
                    )
                ]
            )
            if i < rule.sustained_count - 1:
                assert results[0].fired is False
            else:
                assert results[0].fired is True
