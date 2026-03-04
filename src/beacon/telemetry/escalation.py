"""Escalation engine — state machine for adaptive telemetry sampling.

States: BASELINE → ELEVATED → ACTIVE → COOLDOWN → BASELINE

When triggers fire, the escalation engine transitions through states,
enabling higher-tier samplers and adjusting intervals to gather more
detail about degraded conditions.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from beacon.models.envelope import Severity
from beacon.telemetry.triggers import TriggerResult

logger = logging.getLogger(__name__)


class EscalationState(str, Enum):
    BASELINE = "baseline"
    ELEVATED = "elevated"
    ACTIVE = "active"
    COOLDOWN = "cooldown"


class EscalationAction(str, Enum):
    ENABLE_TIER1 = "enable_tier1"
    DISABLE_TIER1 = "disable_tier1"
    ENABLE_BURST = "enable_burst"
    DISABLE_BURST = "disable_burst"
    ADJUST_INTERVALS = "adjust_intervals"
    TRIGGER_PACK = "trigger_pack"


@dataclass
class EscalationTransition:
    """Record of a state transition."""

    from_state: EscalationState
    to_state: EscalationState
    reason: str
    actions: list[EscalationAction]
    timestamp: float = field(default_factory=time.monotonic)


class EscalationManager:
    """Manages escalation state transitions based on trigger results.

    Flap guard: if triggers fire >= flap_count times within flap_window
    seconds, extends cooldown and suppresses Tier 2 activation.
    """

    def __init__(
        self,
        cooldown_seconds: int = 300,
        flap_window: int = 600,
        flap_count: int = 3,
    ) -> None:
        self._state = EscalationState.BASELINE
        self._cooldown_seconds = cooldown_seconds
        self._flap_window = flap_window
        self._flap_count = flap_count

        self._state_entered_at: float = time.monotonic()
        self._fire_history: deque[float] = deque()
        self._transitions: list[EscalationTransition] = []

    @property
    def state(self) -> EscalationState:
        return self._state

    @property
    def transitions(self) -> list[EscalationTransition]:
        return list(self._transitions)

    @property
    def is_flapping(self) -> bool:
        """Check if we're in a flap condition."""
        now = time.monotonic()
        # Clean old entries
        while self._fire_history and (now - self._fire_history[0]) > self._flap_window:
            self._fire_history.popleft()
        return len(self._fire_history) >= self._flap_count

    def process_triggers(self, results: list[TriggerResult]) -> list[EscalationAction]:
        """Process trigger results and return escalation actions."""
        fired = [r for r in results if r.fired]
        has_critical = any(r.rule.severity == Severity.CRITICAL for r in fired)
        has_warning = any(r.rule.severity == Severity.WARNING for r in fired)
        now = time.monotonic()

        if fired:
            self._fire_history.append(now)

        actions: list[EscalationAction] = []

        if self._state == EscalationState.BASELINE:
            if has_critical:
                actions = self._transition(
                    EscalationState.ACTIVE,
                    "Critical trigger in BASELINE",
                    [EscalationAction.ENABLE_TIER1, EscalationAction.ENABLE_BURST, EscalationAction.TRIGGER_PACK],
                )
            elif has_warning:
                actions = self._transition(
                    EscalationState.ELEVATED,
                    "Warning trigger in BASELINE",
                    [EscalationAction.ENABLE_TIER1],
                )

        elif self._state == EscalationState.ELEVATED:
            if has_critical:
                actions = self._transition(
                    EscalationState.ACTIVE,
                    "Critical trigger in ELEVATED",
                    [EscalationAction.ENABLE_BURST, EscalationAction.TRIGGER_PACK],
                )
            elif not fired:
                # No triggers — de-escalate
                actions = self._transition(
                    EscalationState.BASELINE,
                    "No triggers in ELEVATED",
                    [EscalationAction.DISABLE_TIER1],
                )

        elif self._state == EscalationState.ACTIVE:
            if not fired:
                actions = self._transition(
                    EscalationState.COOLDOWN,
                    "No triggers in ACTIVE",
                    [EscalationAction.DISABLE_BURST],
                )

        elif self._state == EscalationState.COOLDOWN:
            elapsed = now - self._state_entered_at
            cooldown = self._cooldown_seconds
            if self.is_flapping:
                cooldown *= 2  # Extended cooldown for flapping

            if fired:
                # Re-escalate from cooldown
                if has_critical:
                    actions = self._transition(
                        EscalationState.ACTIVE,
                        "Re-escalation from COOLDOWN (critical)",
                        [EscalationAction.ENABLE_BURST, EscalationAction.TRIGGER_PACK],
                    )
                else:
                    actions = self._transition(
                        EscalationState.ELEVATED,
                        "Re-escalation from COOLDOWN (warning)",
                        [EscalationAction.ADJUST_INTERVALS],
                    )
            elif elapsed >= cooldown:
                actions = self._transition(
                    EscalationState.BASELINE,
                    "Cooldown expired",
                    [EscalationAction.DISABLE_TIER1],
                )

        return actions

    def _transition(
        self,
        to_state: EscalationState,
        reason: str,
        actions: list[EscalationAction],
    ) -> list[EscalationAction]:
        """Record a state transition."""
        # Suppress Tier 2 (burst) during flap
        if self.is_flapping:
            actions = [
                a
                for a in actions
                if a not in (EscalationAction.ENABLE_BURST, EscalationAction.TRIGGER_PACK)
            ]

        transition = EscalationTransition(
            from_state=self._state,
            to_state=to_state,
            reason=reason,
            actions=actions,
        )
        self._transitions.append(transition)

        logger.info(
            "Escalation: %s → %s (%s), actions: %s",
            self._state.value,
            to_state.value,
            reason,
            [a.value for a in actions],
        )

        self._state = to_state
        self._state_entered_at = time.monotonic()
        return actions

    def reset(self) -> None:
        """Reset to BASELINE (for testing or manual override)."""
        self._state = EscalationState.BASELINE
        self._state_entered_at = time.monotonic()
        self._fire_history.clear()
        self._transitions.clear()
