"""Unit tests for rules engine."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import uuid4
import pytest

from beacon.engine.rules import (
    RuleEngine,
    Rule,
    MetricCondition,
    EventCondition,
    ThresholdCondition,
    TrendCondition,
    AlertAction,
    EscalationAction,
    RuleContext,
    evaluate_rule,
    _evaluate_condition,
    _execute_action,
)
from beacon.models.envelope import Metric, Event, Severity
from beacon.models.fault import FaultDomain


@pytest.fixture
def sample_metrics():
    now = datetime.now(timezone.utc)
    return [
        Metric(
            measurement="ping",
            fields={"rtt_ms": 150.0, "loss_pct": 0.0},
            tags={"target": "8.8.8.8"},
            timestamp=now,
        ),
        Metric(
            measurement="ping",
            fields={"rtt_ms": 25.0, "loss_pct": 5.0},
            tags={"target": "1.1.1.1"},
            timestamp=now,
        ),
    ]


@pytest.fixture
def sample_events():
    now = datetime.now(timezone.utc)
    return [
        Event(
            event_type="threshold_breach",
            severity=Severity.WARNING,
            message="High RTT detected",
            tags={"target": "8.8.8.8"},
            timestamp=now,
        ),
        Event(
            event_type="packet_loss",
            severity=Severity.CRITICAL,
            message="Packet loss detected",
            tags={"target": "1.1.1.1"},
            timestamp=now,
        ),
    ]


@pytest.fixture
def rule_context(sample_metrics, sample_events):
    return RuleContext(
        run_id=uuid4(),
        metrics=sample_metrics,
        events=sample_events,
        fault_domain=FaultDomain.UNKNOWN,
    )


class TestConditions:
    def test_metric_condition_match(self, sample_metrics):
        condition = MetricCondition(
            measurement="ping",
            field="rtt_ms",
            operator=">",
            value=100.0,
        )
        
        result = condition.evaluate(sample_metrics, [])
        assert result is True

    def test_metric_condition_no_match(self, sample_metrics):
        condition = MetricCondition(
            measurement="ping",
            field="rtt_ms",
            operator=">",
            value=200.0,
        )
        
        result = condition.evaluate(sample_metrics, [])
        assert result is False

    def test_metric_condition_with_tags(self, sample_metrics):
        condition = MetricCondition(
            measurement="ping",
            field="rtt_ms",
            operator=">",
            value=100.0,
            tags={"target": "8.8.8.8"},
        )
        
        result = condition.evaluate(sample_metrics, [])
        assert result is True

    def test_metric_condition_tag_mismatch(self, sample_metrics):
        condition = MetricCondition(
            measurement="ping",
            field="rtt_ms",
            operator=">",
            value=100.0,
            tags={"target": "nonexistent"},
        )
        
        result = condition.evaluate(sample_metrics, [])
        assert result is False

    def test_metric_condition_operators(self, sample_metrics):
        # Test different operators
        conditions = [
            MetricCondition("ping", "rtt_ms", ">=", 150.0),
            MetricCondition("ping", "rtt_ms", "<", 200.0),
            MetricCondition("ping", "rtt_ms", "<=", 150.0),
            MetricCondition("ping", "rtt_ms", "==", 150.0),
            MetricCondition("ping", "rtt_ms", "!=", 100.0),
        ]
        
        for condition in conditions:
            assert condition.evaluate(sample_metrics, []) is True

    def test_event_condition_match(self, sample_events):
        condition = EventCondition(
            event_type="threshold_breach",
            severity=Severity.WARNING,
        )
        
        result = condition.evaluate([], sample_events)
        assert result is True

    def test_event_condition_no_match(self, sample_events):
        condition = EventCondition(
            event_type="nonexistent",
            severity=Severity.WARNING,
        )
        
        result = condition.evaluate([], sample_events)
        assert result is False

    def test_event_condition_severity_mismatch(self, sample_events):
        condition = EventCondition(
            event_type="threshold_breach",
            severity=Severity.CRITICAL,
        )
        
        result = condition.evaluate([], sample_events)
        assert result is False

    def test_event_condition_with_tags(self, sample_events):
        condition = EventCondition(
            event_type="threshold_breach",
            severity=Severity.WARNING,
            tags={"target": "8.8.8.8"},
        )
        
        result = condition.evaluate([], sample_events)
        assert result is True

    def test_threshold_condition_above(self, sample_metrics):
        condition = ThresholdCondition(
            measurement="ping",
            field="rtt_ms",
            threshold=100.0,
            direction="above",
        )
        
        result = condition.evaluate(sample_metrics, [])
        assert result is True

    def test_threshold_condition_below(self, sample_metrics):
        condition = ThresholdCondition(
            measurement="ping",
            field="loss_pct",
            threshold=10.0,
            direction="below",
        )
        
        result = condition.evaluate(sample_metrics, [])
        assert result is True

    def test_trend_condition_increasing(self):
        # Mock historical data showing increasing trend
        condition = TrendCondition(
            measurement="ping",
            field="rtt_ms",
            direction="increasing",
            window_minutes=5,
        )
        
        # Create metrics with increasing values
        now = datetime.now(timezone.utc)
        metrics = [
            Metric("ping", {"rtt_ms": 10.0}, {}, now),
            Metric("ping", {"rtt_ms": 20.0}, {}, now),
            Metric("ping", {"rtt_ms": 30.0}, {}, now),
        ]
        
        # For this test, we'll assume the trend is increasing
        # In a real implementation, this would analyze historical data
        with patch.object(condition, '_analyze_trend', return_value=True):
            result = condition.evaluate(metrics, [])
            assert result is True

    def test_trend_condition_decreasing(self):
        condition = TrendCondition(
            measurement="ping",
            field="rtt_ms",
            direction="decreasing",
            window_minutes=5,
        )
        
        now = datetime.now(timezone.utc)
        metrics = [
            Metric("ping", {"rtt_ms": 30.0}, {}, now),
            Metric("ping", {"rtt_ms": 20.0}, {}, now),
            Metric("ping", {"rtt_ms": 10.0}, {}, now),
        ]
        
        with patch.object(condition, '_analyze_trend', return_value=True):
            result = condition.evaluate(metrics, [])
            assert result is True


class TestActions:
    def test_alert_action_execute(self):
        action = AlertAction(
            message="Test alert",
            severity=Severity.WARNING,
            tags={"source": "test"},
        )
        
        context = Mock()
        result = action.execute(context)
        
        assert result is not None
        assert "alert" in result
        assert result["alert"]["message"] == "Test alert"
        assert result["alert"]["severity"] == Severity.WARNING

    def test_escalation_action_execute(self):
        action = EscalationAction(
            fault_domain=FaultDomain.ISP,
            confidence=0.85,
            evidence_refs=["ping:8.8.8.8:rtt_ms"],
        )
        
        context = Mock()
        result = action.execute(context)
        
        assert result is not None
        assert "escalation" in result
        assert result["escalation"]["fault_domain"] == FaultDomain.ISP
        assert result["escalation"]["confidence"] == 0.85


class TestRule:
    def test_rule_creation(self):
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        action = AlertAction("High RTT", Severity.WARNING)
        
        rule = Rule(
            name="high_rtt_rule",
            description="Detect high RTT",
            condition=condition,
            action=action,
        )
        
        assert rule.name == "high_rtt_rule"
        assert rule.description == "Detect high RTT"
        assert rule.condition == condition
        assert rule.action == action
        assert rule.enabled is True

    def test_rule_disabled(self):
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        action = AlertAction("High RTT", Severity.WARNING)
        
        rule = Rule(
            name="disabled_rule",
            description="Disabled rule",
            condition=condition,
            action=action,
            enabled=False,
        )
        
        assert rule.enabled is False


class TestRuleEngine:
    def test_rule_engine_creation(self):
        engine = RuleEngine()
        assert len(engine.rules) == 0

    def test_add_rule(self):
        engine = RuleEngine()
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        action = AlertAction("High RTT", Severity.WARNING)
        
        rule = Rule("test_rule", "Test rule", condition, action)
        engine.add_rule(rule)
        
        assert len(engine.rules) == 1
        assert engine.rules[0] == rule

    def test_evaluate_rules(self, rule_context):
        engine = RuleEngine()
        
        # Add a rule that should trigger
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        action = AlertAction("High RTT detected", Severity.WARNING)
        rule = Rule("high_rtt", "High RTT rule", condition, action)
        engine.add_rule(rule)
        
        results = engine.evaluate(rule_context)
        
        assert len(results) == 1
        assert results[0]["rule_name"] == "high_rtt"
        assert "alert" in results[0]

    def test_evaluate_disabled_rule(self, rule_context):
        engine = RuleEngine()
        
        # Add a disabled rule
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        action = AlertAction("High RTT detected", Severity.WARNING)
        rule = Rule("disabled_rule", "Disabled rule", condition, action, enabled=False)
        engine.add_rule(rule)
        
        results = engine.evaluate(rule_context)
        
        assert len(results) == 0

    def test_evaluate_multiple_rules(self, rule_context):
        engine = RuleEngine()
        
        # Add multiple rules
        rule1 = Rule(
            "high_rtt",
            "High RTT rule",
            MetricCondition("ping", "rtt_ms", ">", 100.0),
            AlertAction("High RTT", Severity.WARNING),
        )
        
        rule2 = Rule(
            "packet_loss",
            "Packet loss rule",
            EventCondition("packet_loss", Severity.CRITICAL),
            EscalationAction(FaultDomain.ISP, 0.9, ["event:packet_loss"]),
        )
        
        engine.add_rule(rule1)
        engine.add_rule(rule2)
        
        results = engine.evaluate(rule_context)
        
        assert len(results) == 2
        rule_names = {result["rule_name"] for result in results}
        assert rule_names == {"high_rtt", "packet_loss"}

    def test_evaluate_no_matching_rules(self, rule_context):
        engine = RuleEngine()
        
        # Add a rule that won't match
        condition = MetricCondition("ping", "rtt_ms", ">", 1000.0)  # Very high threshold
        action = AlertAction("Extremely high RTT", Severity.CRITICAL)
        rule = Rule("extreme_rtt", "Extreme RTT rule", condition, action)
        engine.add_rule(rule)
        
        results = engine.evaluate(rule_context)
        
        assert len(results) == 0


class TestRuleFunctions:
    def test_evaluate_rule_success(self, rule_context):
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        action = AlertAction("High RTT", Severity.WARNING)
        rule = Rule("test_rule", "Test rule", condition, action)
        
        result = evaluate_rule(rule, rule_context)
        
        assert result is not None
        assert result["rule_name"] == "test_rule"
        assert "alert" in result

    def test_evaluate_rule_condition_false(self, rule_context):
        condition = MetricCondition("ping", "rtt_ms", ">", 1000.0)
        action = AlertAction("High RTT", Severity.WARNING)
        rule = Rule("test_rule", "Test rule", condition, action)
        
        result = evaluate_rule(rule, rule_context)
        
        assert result is None

    def test_evaluate_rule_disabled(self, rule_context):
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        action = AlertAction("High RTT", Severity.WARNING)
        rule = Rule("test_rule", "Test rule", condition, action, enabled=False)
        
        result = evaluate_rule(rule, rule_context)
        
        assert result is None

    def test_evaluate_condition_metric(self, sample_metrics):
        condition = MetricCondition("ping", "rtt_ms", ">", 100.0)
        
        result = _evaluate_condition(condition, sample_metrics, [])
        
        assert result is True

    def test_evaluate_condition_event(self, sample_events):
        condition = EventCondition("threshold_breach", Severity.WARNING)
        
        result = _evaluate_condition(condition, [], sample_events)
        
        assert result is True

    def test_execute_action_alert(self):
        action = AlertAction("Test alert", Severity.WARNING)
        context = Mock()
        
        result = _execute_action(action, context)
        
        assert result is not None
        assert "alert" in result

    def test_execute_action_escalation(self):
        action = EscalationAction(FaultDomain.ISP, 0.85, ["test:ref"])
        context = Mock()
        
        result = _execute_action(action, context)
        
        assert result is not None
        assert "escalation" in result


class TestRuleContextIntegration:
    def test_rule_context_creation(self, sample_metrics, sample_events):
        run_id = uuid4()
        context = RuleContext(
            run_id=run_id,
            metrics=sample_metrics,
            events=sample_events,
            fault_domain=FaultDomain.WIFI,
        )
        
        assert context.run_id == run_id
        assert context.metrics == sample_metrics
        assert context.events == sample_events
        assert context.fault_domain == FaultDomain.WIFI

    def test_end_to_end_rule_evaluation(self, sample_metrics, sample_events):
        # Create a complete scenario
        engine = RuleEngine()
        
        # Rule 1: High RTT threshold
        high_rtt_rule = Rule(
            "high_rtt_threshold",
            "Detect RTT above 100ms",
            ThresholdCondition("ping", "rtt_ms", 100.0, "above"),
            AlertAction("High RTT detected", Severity.WARNING, {"domain": "network"}),
        )
        
        # Rule 2: Critical event escalation
        critical_event_rule = Rule(
            "critical_escalation",
            "Escalate critical events",
            EventCondition("packet_loss", Severity.CRITICAL),
            EscalationAction(FaultDomain.ISP, 0.8, ["event:packet_loss"]),
        )
        
        engine.add_rule(high_rtt_rule)
        engine.add_rule(critical_event_rule)
        
        context = RuleContext(
            run_id=uuid4(),
            metrics=sample_metrics,
            events=sample_events,
            fault_domain=FaultDomain.UNKNOWN,
        )
        
        results = engine.evaluate(context)
        
        assert len(results) == 2
        
        # Check alert result
        alert_result = next(r for r in results if "alert" in r)
        assert alert_result["rule_name"] == "high_rtt_threshold"
        assert alert_result["alert"]["message"] == "High RTT detected"
        
        # Check escalation result
        escalation_result = next(r for r in results if "escalation" in r)
        assert escalation_result["rule_name"] == "critical_escalation"
        assert escalation_result["escalation"]["fault_domain"] == FaultDomain.ISP