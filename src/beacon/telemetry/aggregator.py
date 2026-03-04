"""WindowAggregator — ring buffer with percentile computation over time windows.

Accumulates raw Metric samples and, on each window tick, computes
summary statistics: p50, p95, p99, min, max, mean, count, jitter.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from beacon.models.envelope import Metric

# 10-minute lookback across all windows
_MAX_LOOKBACK_SECONDS = 600


@dataclass
class AggregatedWindow:
    """Statistics for one (measurement, tags_key) over a single window."""

    measurement: str
    tags: dict[str, str]
    field_name: str
    count: int
    mean: float
    min: float
    max: float
    p50: float
    p95: float
    p99: float
    jitter: float  # stddev of consecutive diffs
    window_start: datetime
    window_end: datetime


@dataclass
class _SeriesBuffer:
    """Ring buffer for a single (measurement, tags_key, field) series."""

    values: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=_MAX_LOOKBACK_SECONDS),
    )


class WindowAggregator:
    """Collects raw metrics and computes windowed aggregates."""

    def __init__(self, window_seconds: int = 60) -> None:
        self._window_seconds = window_seconds
        # Key: (measurement, frozenset(tags.items()), field_name)
        self._buffers: dict[tuple, _SeriesBuffer] = defaultdict(_SeriesBuffer)

    def push(self, metrics: list[Metric]) -> None:
        """Add raw metric samples to the ring buffers."""
        for metric in metrics:
            ts = metric.timestamp.timestamp()
            tags_key = frozenset(metric.tags.items())
            for field_name, value in metric.fields.items():
                if not isinstance(value, (int, float)):
                    continue
                key = (metric.measurement, tags_key, field_name)
                self._buffers[key].values.append((ts, float(value)))

    def flush(self) -> list[AggregatedWindow]:
        """Compute aggregates for the current window and return them.

        Does NOT clear buffers — old samples age out via the deque maxlen.
        The caller decides how often to flush (every window_seconds).
        """
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        window_start_ts = now_ts - self._window_seconds
        results: list[AggregatedWindow] = []

        for (measurement, tags_key, field_name), buf in self._buffers.items():
            # Filter to samples within this window
            window_values = [v for ts, v in buf.values if ts >= window_start_ts]
            if not window_values:
                continue

            count = len(window_values)
            mean = statistics.mean(window_values)
            lo = min(window_values)
            hi = max(window_values)

            if count >= 2:
                quantiles = statistics.quantiles(window_values, n=100)
                p50 = quantiles[49]
                p95 = quantiles[94]
                p99 = quantiles[98] if len(quantiles) > 98 else quantiles[-1]

                # Jitter = stddev of consecutive differences
                diffs = [
                    abs(window_values[i] - window_values[i - 1])
                    for i in range(1, len(window_values))
                ]
                jitter = (
                    statistics.stdev(diffs) if len(diffs) >= 2 else (diffs[0] if diffs else 0.0)
                )
            else:
                p50 = p95 = p99 = window_values[0]
                jitter = 0.0

            tags = dict(tags_key)
            results.append(
                AggregatedWindow(
                    measurement=measurement,
                    tags=tags,
                    field_name=field_name,
                    count=count,
                    mean=round(mean, 4),
                    min=round(lo, 4),
                    max=round(hi, 4),
                    p50=round(p50, 4),
                    p95=round(p95, 4),
                    p99=round(p99, 4),
                    jitter=round(jitter, 4),
                    window_start=datetime.fromtimestamp(window_start_ts, tz=timezone.utc),
                    window_end=now,
                )
            )

        return results

    def clear(self) -> None:
        """Clear all buffers."""
        self._buffers.clear()
