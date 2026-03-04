"""Tests for WindowAggregator — percentile math, jitter, edge cases."""

from datetime import datetime, timezone

import pytest

from beacon.models.envelope import Metric
from beacon.telemetry.aggregator import WindowAggregator


def _make_metric(measurement: str, field: str, value: float, **tags) -> Metric:
    return Metric(
        measurement=measurement,
        fields={field: value},
        tags=tags,
        timestamp=datetime.now(timezone.utc),
    )


class TestWindowAggregator:
    def test_empty_flush_returns_empty(self):
        agg = WindowAggregator(window_seconds=60)
        assert agg.flush() == []

    def test_single_sample(self):
        agg = WindowAggregator(window_seconds=60)
        agg.push([_make_metric("t_ping", "rtt_ms", 10.0, target="8.8.8.8")])
        windows = agg.flush()
        assert len(windows) == 1
        w = windows[0]
        assert w.measurement == "t_ping"
        assert w.field_name == "rtt_ms"
        assert w.count == 1
        assert w.mean == 10.0
        assert w.min == 10.0
        assert w.max == 10.0
        assert w.p50 == 10.0
        assert w.jitter == 0.0

    def test_multiple_samples_stats(self):
        agg = WindowAggregator(window_seconds=60)
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        metrics = [_make_metric("t_ping", "rtt_ms", v) for v in values]
        agg.push(metrics)
        windows = agg.flush()
        assert len(windows) == 1
        w = windows[0]
        assert w.count == 5
        assert w.mean == 30.0
        assert w.min == 10.0
        assert w.max == 50.0

    def test_percentiles_with_many_samples(self):
        agg = WindowAggregator(window_seconds=60)
        values = list(range(1, 101))  # 1..100
        metrics = [_make_metric("t_ping", "rtt_ms", float(v)) for v in values]
        agg.push(metrics)
        windows = agg.flush()
        w = windows[0]
        assert w.count == 100
        assert w.p50 == pytest.approx(50.0, abs=1.0)
        assert w.p95 == pytest.approx(95.0, abs=1.0)
        assert w.p99 == pytest.approx(99.0, abs=1.0)

    def test_jitter_constant_values(self):
        agg = WindowAggregator(window_seconds=60)
        metrics = [_make_metric("t_ping", "rtt_ms", 10.0) for _ in range(5)]
        agg.push(metrics)
        windows = agg.flush()
        assert windows[0].jitter == 0.0

    def test_jitter_varying_values(self):
        agg = WindowAggregator(window_seconds=60)
        # Alternating 10 and 20: diffs are all 10, so stdev = 0
        metrics = [_make_metric("t_ping", "rtt_ms", v) for v in [10, 20, 10, 20, 10]]
        agg.push(metrics)
        windows = agg.flush()
        # Consecutive diffs: [10, 10, 10, 10] — all same so stdev = 0
        assert windows[0].jitter == 0.0

    def test_separate_series_by_tags(self):
        agg = WindowAggregator(window_seconds=60)
        agg.push(
            [
                _make_metric("t_ping", "rtt_ms", 10.0, target="8.8.8.8"),
                _make_metric("t_ping", "rtt_ms", 20.0, target="1.1.1.1"),
            ]
        )
        windows = agg.flush()
        assert len(windows) == 2

    def test_non_numeric_fields_ignored(self):
        agg = WindowAggregator(window_seconds=60)
        agg.push(
            [
                Metric(
                    measurement="t_ping",
                    fields={"target": "8.8.8.8", "rtt_ms": 10.0},
                    timestamp=datetime.now(timezone.utc),
                )
            ]
        )
        windows = agg.flush()
        # Only rtt_ms should be aggregated (not the string field)
        assert len(windows) == 1
        assert windows[0].field_name == "rtt_ms"

    def test_clear(self):
        agg = WindowAggregator(window_seconds=60)
        agg.push([_make_metric("t_ping", "rtt_ms", 10.0)])
        agg.clear()
        assert agg.flush() == []

    def test_multiple_fields_per_metric(self):
        agg = WindowAggregator(window_seconds=60)
        agg.push(
            [
                Metric(
                    measurement="t_device",
                    fields={"cpu_percent": 25.0, "memory_percent": 60.0},
                    timestamp=datetime.now(timezone.utc),
                )
            ]
        )
        windows = agg.flush()
        assert len(windows) == 2
        field_names = {w.field_name for w in windows}
        assert field_names == {"cpu_percent", "memory_percent"}
