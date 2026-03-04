"""Threshold breach detection — scans metrics for values exceeding configured limits."""

from __future__ import annotations


from pydantic import BaseModel, Field

from beacon.models.envelope import Event, Metric, Severity


class ThresholdRule(BaseModel):
    """A threshold rule that fires when a metric field exceeds a limit."""

    measurement: str
    field: str
    operator: str = ">"  # >, <, >=, <=, ==, !=
    value: float
    severity: Severity = Severity.WARNING
    message_template: str = "{measurement}.{field} {operator} {value} (actual: {actual})"
    tags_filter: dict[str, str] = Field(default_factory=dict)


# Built-in threshold rules
DEFAULT_THRESHOLDS: list[ThresholdRule] = [
    ThresholdRule(
        measurement="ping",
        field="loss_pct",
        operator=">",
        value=5.0,
        severity=Severity.WARNING,
        message_template="Packet loss {actual}% exceeds 5% threshold",
    ),
    ThresholdRule(
        measurement="ping",
        field="loss_pct",
        operator=">=",
        value=50.0,
        severity=Severity.CRITICAL,
        message_template="Severe packet loss: {actual}%",
    ),
    ThresholdRule(
        measurement="ping",
        field="rtt_avg_ms",
        operator=">",
        value=100.0,
        severity=Severity.WARNING,
        message_template="Average RTT {actual}ms exceeds 100ms threshold",
    ),
    ThresholdRule(
        measurement="dns_resolve",
        field="latency_ms",
        operator=">",
        value=500.0,
        severity=Severity.WARNING,
        message_template="DNS resolution took {actual}ms (>500ms)",
    ),
    ThresholdRule(
        measurement="device_cpu",
        field="percent",
        operator=">",
        value=90.0,
        severity=Severity.WARNING,
        message_template="CPU usage at {actual}%",
    ),
    ThresholdRule(
        measurement="device_memory",
        field="percent_used",
        operator=">",
        value=90.0,
        severity=Severity.WARNING,
        message_template="Memory usage at {actual}%",
    ),
    ThresholdRule(
        measurement="wifi_link",
        field="rssi_dbm",
        operator="<",
        value=-75.0,
        severity=Severity.WARNING,
        message_template="Wi-Fi signal weak: {actual} dBm",
    ),
]

_OPERATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


class ThresholdMonitor:
    """Evaluates metrics against threshold rules and emits events."""

    def __init__(self, rules: list[ThresholdRule] | None = None) -> None:
        self._rules = rules if rules is not None else DEFAULT_THRESHOLDS

    def evaluate(self, metrics: list[Metric]) -> list[Event]:
        """Check all metrics against all threshold rules. Return breach events."""
        events: list[Event] = []

        for metric in metrics:
            for rule in self._rules:
                if metric.measurement != rule.measurement:
                    continue
                if rule.field not in metric.fields:
                    continue

                # Check tag filters
                if rule.tags_filter:
                    if not all(metric.tags.get(k) == v for k, v in rule.tags_filter.items()):
                        continue

                actual = metric.fields[rule.field]
                if not isinstance(actual, (int, float)):
                    continue

                op_fn = _OPERATORS.get(rule.operator)
                if op_fn and op_fn(actual, rule.value):
                    message = rule.message_template.format(
                        measurement=rule.measurement,
                        field=rule.field,
                        operator=rule.operator,
                        value=rule.value,
                        actual=actual,
                    )
                    events.append(
                        Event(
                            event_type="threshold_breach",
                            severity=rule.severity,
                            message=message,
                            tags={
                                "measurement": rule.measurement,
                                "field": rule.field,
                                **metric.tags,
                            },
                            timestamp=metric.timestamp,
                        )
                    )

        return events
