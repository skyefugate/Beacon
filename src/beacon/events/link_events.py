"""Link flap detection — identifies interfaces that repeatedly go up and down."""

from __future__ import annotations

from beacon.models.envelope import Event, Metric, Severity


class LinkFlapDetector:
    """Detects link state changes from interface metrics."""

    def __init__(self, flap_threshold: int = 3) -> None:
        self._flap_threshold = flap_threshold
        self._link_history: dict[str, list[bool]] = {}

    def analyze(self, metrics: list[Metric]) -> list[Event]:
        """Analyze LAN interface metrics for link flaps."""
        events: list[Event] = []

        status_metrics = [m for m in metrics if m.measurement == "lan_status"]

        for metric in status_metrics:
            iface = metric.tags.get("interface", "unknown")
            is_up = bool(metric.fields.get("is_up", True))

            if iface not in self._link_history:
                self._link_history[iface] = []

            history = self._link_history[iface]
            history.append(is_up)

            # Check for flapping: alternating up/down states
            if len(history) >= self._flap_threshold:
                recent = history[-self._flap_threshold :]
                transitions = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i - 1])
                if transitions >= self._flap_threshold - 1:
                    events.append(
                        Event(
                            event_type="link_flap",
                            severity=Severity.CRITICAL,
                            message=f"Interface {iface} is flapping ({transitions} transitions in last {self._flap_threshold} observations)",
                            tags={"interface": iface},
                            timestamp=metric.timestamp,
                        )
                    )

            # Detect link down
            if not is_up:
                events.append(
                    Event(
                        event_type="link_down",
                        severity=Severity.CRITICAL,
                        message=f"Interface {iface} is down",
                        tags={"interface": iface},
                        timestamp=metric.timestamp,
                    )
                )

        return events
