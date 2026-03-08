"""Event-metric correlation — links events to metrics occurring around the same time."""

from __future__ import annotations

from datetime import timedelta

from beacon.models.envelope import Event, Metric, PluginEnvelope
from beacon.models.evidence import EventCorrelation


class EventCorrelator:
    """Correlates events with metrics within a configurable time window."""

    def __init__(self, window_seconds: float = 45.0) -> None:
        self._window = timedelta(seconds=window_seconds)

    def correlate(self, envelopes: list[PluginEnvelope]) -> list[EventCorrelation]:
        """Find correlations between events and metrics across all envelopes."""
        all_metrics: list[Metric] = []
        all_events: list[Event] = []

        for env in envelopes:
            all_metrics.extend(env.metrics)
            all_events.extend(env.events)

        correlations: list[EventCorrelation] = []

        for event in all_events:
            correlated_refs: list[str] = []
            for metric in all_metrics:
                delta = abs(event.timestamp - metric.timestamp)
                if delta <= self._window:
                    ref = f"{metric.measurement}:{','.join(f'{k}={v}' for k, v in metric.tags.items())}"
                    correlated_refs.append(ref)

            if correlated_refs:
                event_ref = (
                    f"{event.event_type}:{','.join(f'{k}={v}' for k, v in event.tags.items())}"
                )
                correlations.append(
                    EventCorrelation(
                        event_ref=event_ref,
                        correlated_metrics=correlated_refs,
                        time_window_seconds=self._window.total_seconds(),
                        description=event.message,
                    )
                )

        return correlations
