"""Threshold-based anomaly triggers for telemetry aggregated windows.

Evaluates aggregated metrics against configurable trigger rules.
Inspired by events/threshold.py ThresholdMonitor but operates on
aggregated windows rather than raw metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from beacon.models.envelope import Event, Severity
from beacon.telemetry.aggregator import AggregatedWindow


class TriggerType(str, Enum):
    THRESHOLD = "threshold"  # single-value comparison
    DELTA = "delta"  # change from previous window
    SUSTAINED = "sustained"  # threshold held for N consecutive windows
    EVENT = "event"  # fires on any change event


@dataclass
class TriggerRule:
    """A rule that evaluates aggregated windows and fires triggers."""

    name: str
    measurement: str
    field_name: str
    stat: str = "p95"  # which aggregate stat to check: p50, p95, p99, mean, max, etc.
    trigger_type: TriggerType = TriggerType.THRESHOLD
    operator: str = ">"
    value: float = 0.0
    severity: Severity = Severity.WARNING
    message_template: str = "{name}: {stat}={actual} {operator} {value}"
    sustained_count: int = 3  # for SUSTAINED type
    tags_filter: dict[str, str] = field(default_factory=dict)


_OPERATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


# Built-in telemetry trigger rules
DEFAULT_TRIGGERS: list[TriggerRule] = [
    TriggerRule(
        name="high_ping_p95",
        measurement="t_internet_rtt",
        field_name="rtt_avg_ms",
        stat="p95",
        operator=">",
        value=100.0,
        severity=Severity.WARNING,
        message_template="Internet RTT p95={actual:.0f}ms exceeds 100ms",
    ),
    TriggerRule(
        name="high_ping_p99",
        measurement="t_internet_rtt",
        field_name="rtt_avg_ms",
        stat="p99",
        operator=">",
        value=200.0,
        severity=Severity.CRITICAL,
        message_template="Internet RTT p99={actual:.0f}ms exceeds 200ms",
    ),
    TriggerRule(
        name="gateway_loss",
        measurement="t_gateway_rtt",
        field_name="loss_pct",
        stat="mean",
        operator=">",
        value=5.0,
        severity=Severity.WARNING,
        message_template="Gateway packet loss mean={actual:.1f}% exceeds 5%",
    ),
    TriggerRule(
        name="dns_slow",
        measurement="t_dns_latency",
        field_name="latency_ms",
        stat="p95",
        operator=">",
        value=500.0,
        severity=Severity.WARNING,
        message_template="DNS latency p95={actual:.0f}ms exceeds 500ms",
    ),
    TriggerRule(
        name="wifi_weak",
        measurement="t_wifi_link",
        field_name="rssi_dbm",
        stat="mean",
        operator="<",
        value=-75.0,
        severity=Severity.WARNING,
        message_template="Wi-Fi signal weak: mean={actual:.0f} dBm",
    ),
    TriggerRule(
        name="http_slow",
        measurement="t_http_timing",
        field_name="total_ms",
        stat="p95",
        operator=">",
        value=2000.0,
        severity=Severity.WARNING,
        message_template="HTTP response p95={actual:.0f}ms exceeds 2000ms",
    ),
    TriggerRule(
        name="high_cpu",
        measurement="t_device_health",
        field_name="cpu_percent",
        stat="mean",
        operator=">",
        value=90.0,
        severity=Severity.WARNING,
        message_template="CPU usage mean={actual:.0f}% exceeds 90%",
    ),
    TriggerRule(
        name="high_memory",
        measurement="t_device_health",
        field_name="memory_percent",
        stat="mean",
        operator=">",
        value=85.0,
        severity=Severity.WARNING,
        message_template="Memory usage mean={actual:.0f}% exceeds 85%",
    ),
    TriggerRule(
        name="low_snr",
        measurement="t_wifi_link",
        field_name="snr_db",
        stat="mean",
        operator="<",
        value=15.0,
        severity=Severity.WARNING,
        message_template="Wi-Fi SNR poor: mean={actual:.1f} dB below 15 dB",
    ),
    TriggerRule(
        name="high_noise_floor",
        measurement="t_wifi_link",
        field_name="noise_dbm",
        stat="mean",
        operator=">",
        value=-85.0,
        severity=Severity.WARNING,
        message_template="Wi-Fi noise floor elevated: mean={actual:.0f} dBm above -85 dBm",
    ),
    TriggerRule(
        name="high_load_avg_1m",
        measurement="t_device_health",
        field_name="load_avg_1m",
        stat="mean",
        operator=">",
        value=4.0,
        severity=Severity.WARNING,
        message_template="Load average (1m) mean={actual:.2f} exceeds 4.0",
    ),
    TriggerRule(
        name="wifi_rssi_drop",
        measurement="t_wifi_link",
        field_name="rssi_dbm",
        stat="mean",
        trigger_type=TriggerType.DELTA,
        operator="<",
        value=-10.0,
        severity=Severity.WARNING,
        message_template="Wi-Fi RSSI sudden drop: delta={actual:.1f} dBm",
    ),
]


@dataclass
class TriggerResult:
    """The result of a trigger evaluation."""

    rule: TriggerRule
    actual: float
    fired: bool
    event: Event | None = None


class TriggerEvaluator:
    """Evaluates aggregated windows against trigger rules."""

    def __init__(self, rules: list[TriggerRule] | None = None) -> None:
        self._rules = rules if rules is not None else DEFAULT_TRIGGERS
        # Track sustained trigger state: rule_name -> consecutive fire count
        self._sustained_counts: dict[str, int] = {}
        # Track previous values for delta triggers
        self._previous_values: dict[str, float] = {}

    def evaluate(self, windows: list[AggregatedWindow]) -> list[TriggerResult]:
        """Evaluate all windows against all rules. Returns fired triggers."""
        results: list[TriggerResult] = []

        for rule in self._rules:
            matching = self._find_matching_windows(rule, windows)
            for window in matching:
                actual = self._get_stat(window, rule.stat)
                if actual is None:
                    continue

                fired = self._check_trigger(rule, actual)

                if rule.trigger_type == TriggerType.SUSTAINED:
                    key = f"{rule.name}:{window.measurement}:{frozenset(window.tags.items())}"
                    if fired:
                        self._sustained_counts[key] = (
                            self._sustained_counts.get(key, 0) + 1
                        )
                        if self._sustained_counts[key] < rule.sustained_count:
                            fired = False  # Not enough consecutive windows yet
                    else:
                        self._sustained_counts[key] = 0

                elif rule.trigger_type == TriggerType.DELTA:
                    key = f"{rule.name}:{window.measurement}:{frozenset(window.tags.items())}"
                    prev = self._previous_values.get(key)
                    self._previous_values[key] = actual
                    if prev is None:
                        fired = False  # no baseline yet — first window, cannot compute delta
                    else:
                        delta = actual - prev
                        fired = self._check_trigger(rule, delta)

                event = None
                if fired:
                    message = rule.message_template.format(
                        name=rule.name,
                        stat=rule.stat,
                        actual=actual,
                        operator=rule.operator,
                        value=rule.value,
                    )
                    event = Event(
                        event_type=f"trigger:{rule.name}",
                        severity=rule.severity,
                        message=message,
                        tags={
                            "trigger": rule.name,
                            "measurement": window.measurement,
                            **window.tags,
                        },
                        timestamp=window.window_end,
                    )

                results.append(TriggerResult(
                    rule=rule, actual=actual, fired=fired, event=event,
                ))

        return results

    def _find_matching_windows(
        self, rule: TriggerRule, windows: list[AggregatedWindow],
    ) -> list[AggregatedWindow]:
        """Find windows that match a rule's measurement and tags filter."""
        matching = []
        for w in windows:
            if w.measurement != rule.measurement:
                continue
            if w.field_name != rule.field_name:
                continue
            if rule.tags_filter and not all(
                w.tags.get(k) == v for k, v in rule.tags_filter.items()
            ):
                continue
            matching.append(w)
        return matching

    @staticmethod
    def _get_stat(window: AggregatedWindow, stat: str) -> float | None:
        """Extract a statistic from an aggregated window."""
        return getattr(window, stat, None)

    @staticmethod
    def _check_trigger(rule: TriggerRule, actual: float) -> bool:
        """Check if the actual value fires the trigger."""
        op_fn = _OPERATORS.get(rule.operator)
        if op_fn is None:
            return False
        return op_fn(actual, rule.value)
