"""Tests for escalation engine — all transitions, flap guard, cooldown timing."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from beacon.models.envelope import Severity
from beacon.telemetry.escalation import (
    EscalationAction,
    EscalationManager,
    EscalationState,
)
from beacon.telemetry.triggers import TriggerResult, TriggerRule, TriggerType


def _make_result(fired: bool, severity: Severity = Severity.WARNING) -> TriggerResult:
    rule = TriggerRule(
        name="test",
        measurement="t_internet_rtt",
        field_name="rtt_avg_ms",
        severity=severity,
    )
    return TriggerResult(rule=rule, actual=150.0, fired=fired)


class TestEscalationManager:
    def test_initial_state_is_baseline(self):
        mgr = EscalationManager()
        assert mgr.state == EscalationState.BASELINE

    def test_warning_baseline_to_elevated(self):
        mgr = EscalationManager()
        actions = mgr.process_triggers([_make_result(True, Severity.WARNING)])
        assert mgr.state == EscalationState.ELEVATED
        assert EscalationAction.ENABLE_TIER1 in actions

    def test_critical_baseline_to_active(self):
        mgr = EscalationManager()
        actions = mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        assert mgr.state == EscalationState.ACTIVE
        assert EscalationAction.ENABLE_TIER1 in actions
        assert EscalationAction.ENABLE_BURST in actions

    def test_no_triggers_baseline_stays(self):
        mgr = EscalationManager()
        actions = mgr.process_triggers([_make_result(False)])
        assert mgr.state == EscalationState.BASELINE
        assert actions == []

    def test_elevated_critical_to_active(self):
        mgr = EscalationManager()
        mgr.process_triggers([_make_result(True, Severity.WARNING)])
        assert mgr.state == EscalationState.ELEVATED

        actions = mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        assert mgr.state == EscalationState.ACTIVE
        assert EscalationAction.ENABLE_BURST in actions

    def test_elevated_no_triggers_to_baseline(self):
        mgr = EscalationManager()
        mgr.process_triggers([_make_result(True, Severity.WARNING)])
        assert mgr.state == EscalationState.ELEVATED

        actions = mgr.process_triggers([_make_result(False)])
        assert mgr.state == EscalationState.BASELINE
        assert EscalationAction.DISABLE_TIER1 in actions

    def test_active_no_triggers_to_cooldown(self):
        mgr = EscalationManager()
        mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        assert mgr.state == EscalationState.ACTIVE

        actions = mgr.process_triggers([_make_result(False)])
        assert mgr.state == EscalationState.COOLDOWN
        assert EscalationAction.DISABLE_BURST in actions

    def test_cooldown_expires_to_baseline(self):
        mgr = EscalationManager(cooldown_seconds=0)  # instant cooldown
        mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        mgr.process_triggers([_make_result(False)])  # → COOLDOWN
        assert mgr.state == EscalationState.COOLDOWN

        # Simulate time passing past cooldown
        mgr._state_entered_at = time.monotonic() - 1
        actions = mgr.process_triggers([_make_result(False)])
        assert mgr.state == EscalationState.BASELINE
        assert EscalationAction.DISABLE_TIER1 in actions

    def test_cooldown_re_escalate_on_critical(self):
        mgr = EscalationManager()
        mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        mgr.process_triggers([_make_result(False)])  # → COOLDOWN

        actions = mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        assert mgr.state == EscalationState.ACTIVE

    def test_cooldown_re_escalate_on_warning(self):
        mgr = EscalationManager()
        mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        mgr.process_triggers([_make_result(False)])  # → COOLDOWN

        actions = mgr.process_triggers([_make_result(True, Severity.WARNING)])
        assert mgr.state == EscalationState.ELEVATED

    def test_flap_guard_suppresses_burst(self):
        mgr = EscalationManager(flap_count=3, flap_window=600)

        # Simulate 3 recent fires in history (without resetting)
        now = time.monotonic()
        mgr._fire_history.extend([now, now, now])

        assert mgr.is_flapping

        # Critical from BASELINE should not get ENABLE_BURST due to flap
        actions = mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        assert mgr.state == EscalationState.ACTIVE
        assert EscalationAction.ENABLE_BURST not in actions
        assert EscalationAction.ENABLE_TIER1 in actions

    def test_flap_history_ages_out(self):
        mgr = EscalationManager(flap_count=3, flap_window=10)

        # Add old fires
        old = time.monotonic() - 20
        for _ in range(5):
            mgr._fire_history.append(old)

        assert not mgr.is_flapping  # Old entries should age out

    def test_transitions_recorded(self):
        mgr = EscalationManager()
        mgr.process_triggers([_make_result(True, Severity.WARNING)])
        mgr.process_triggers([_make_result(False)])

        assert len(mgr.transitions) == 2
        assert mgr.transitions[0].from_state == EscalationState.BASELINE
        assert mgr.transitions[0].to_state == EscalationState.ELEVATED
        assert mgr.transitions[1].from_state == EscalationState.ELEVATED
        assert mgr.transitions[1].to_state == EscalationState.BASELINE

    def test_reset(self):
        mgr = EscalationManager()
        mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        mgr.reset()
        assert mgr.state == EscalationState.BASELINE
        assert len(mgr.transitions) == 0

    def test_full_lifecycle(self):
        """BASELINE → ELEVATED → ACTIVE → COOLDOWN → BASELINE."""
        mgr = EscalationManager(cooldown_seconds=0)

        # 1. BASELINE → ELEVATED
        mgr.process_triggers([_make_result(True, Severity.WARNING)])
        assert mgr.state == EscalationState.ELEVATED

        # 2. ELEVATED → ACTIVE
        mgr.process_triggers([_make_result(True, Severity.CRITICAL)])
        assert mgr.state == EscalationState.ACTIVE

        # 3. ACTIVE → COOLDOWN
        mgr.process_triggers([_make_result(False)])
        assert mgr.state == EscalationState.COOLDOWN

        # 4. COOLDOWN → BASELINE (instant cooldown)
        mgr._state_entered_at = time.monotonic() - 1
        mgr.process_triggers([_make_result(False)])
        assert mgr.state == EscalationState.BASELINE
