"""Unit tests for the fault domain engine — rules, correlator, scorer, engine."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from beacon.engine.correlator import EventCorrelator
from beacon.engine.fault_domain import FaultDomainEngine
from beacon.engine.rules import HeuristicRuleSet, Signal, SignalMatch
from beacon.engine.scorer import ConfidenceScorer
from beacon.models.envelope import Event, Metric, PluginEnvelope, Severity
from beacon.models.fault import FaultDomain


def _now():
    return datetime.now(timezone.utc)


def _make_envelope(
    name: str, metrics: list[Metric] = None, events: list[Event] = None
) -> PluginEnvelope:
    now = _now()
    return PluginEnvelope(
        plugin_name=name,
        plugin_version="0.1.0",
        run_id=uuid4(),
        metrics=metrics or [],
        events=events or [],
        started_at=now,
        completed_at=now,
    )


class TestHeuristicRuleSet:
    def test_matches_high_cpu_metric(self):
        envelope = _make_envelope("device", metrics=[
            Metric(measurement="device_cpu", fields={"percent": 95.0}, timestamp=_now()),
        ])
        rules = HeuristicRuleSet()
        matches = rules.evaluate([envelope])
        assert any(m.signal.name == "high_cpu" for m in matches)

    def test_matches_event_by_type(self):
        envelope = _make_envelope("ping", events=[
            Event(
                event_type="packet_loss_external",
                severity=Severity.WARNING,
                message="Loss detected",
                timestamp=_now(),
            ),
        ])
        rules = HeuristicRuleSet()
        matches = rules.evaluate([envelope])
        assert any(m.signal.name == "packet_loss_external" for m in matches)

    def test_no_matches_for_normal_metrics(self):
        envelope = _make_envelope("device", metrics=[
            Metric(measurement="device_cpu", fields={"percent": 25.0}, timestamp=_now()),
            Metric(measurement="ping", fields={"loss_pct": 0.0, "rtt_avg_ms": 15.0}, tags={"target": "8.8.8.8"}, timestamp=_now()),
        ])
        rules = HeuristicRuleSet()
        matches = rules.evaluate([envelope])
        assert len(matches) == 0

    def test_matches_weak_wifi(self):
        envelope = _make_envelope("wifi", metrics=[
            Metric(measurement="wifi_link", fields={"rssi_dbm": -80}, timestamp=_now()),
        ])
        rules = HeuristicRuleSet()
        matches = rules.evaluate([envelope])
        assert any(m.signal.name == "weak_signal" for m in matches)

    def test_matches_gateway_unreachable(self):
        envelope = _make_envelope("path", metrics=[
            Metric(
                measurement="path_gateway",
                fields={"reachable": False},
                tags={"gateway": "192.168.1.1"},
                timestamp=_now(),
            ),
        ])
        rules = HeuristicRuleSet()
        matches = rules.evaluate([envelope])
        assert any(m.signal.name == "gateway_unreachable" for m in matches)


class TestEventCorrelator:
    def test_correlates_nearby_events_and_metrics(self):
        now = _now()
        envelope = _make_envelope("mixed",
            metrics=[
                Metric(measurement="ping", fields={"loss_pct": 10.0}, tags={"target": "8.8.8.8"}, timestamp=now),
            ],
            events=[
                Event(event_type="packet_loss", severity=Severity.WARNING,
                      message="Loss detected", tags={"target": "8.8.8.8"}, timestamp=now),
            ],
        )

        correlator = EventCorrelator(window_seconds=5.0)
        correlations = correlator.correlate([envelope])
        assert len(correlations) >= 1
        assert len(correlations[0].correlated_metrics) >= 1

    def test_no_correlation_outside_window(self):
        now = _now()
        envelope = _make_envelope("mixed",
            metrics=[
                Metric(measurement="ping", fields={"loss_pct": 10.0}, timestamp=now - timedelta(minutes=5)),
            ],
            events=[
                Event(event_type="packet_loss", severity=Severity.WARNING,
                      message="Loss", timestamp=now),
            ],
        )

        correlator = EventCorrelator(window_seconds=5.0)
        correlations = correlator.correlate([envelope])
        # Event exists but no correlated metrics within window
        if correlations:
            assert len(correlations[0].correlated_metrics) == 0


class TestConfidenceScorer:
    def test_single_domain_scores_high(self):
        matches = [
            SignalMatch(
                signal=Signal(FaultDomain.WIFI, "weak_signal", 0.9),
                evidence_ref="metric:wifi_link:rssi=-80",
            ),
        ]
        scorer = ConfidenceScorer()
        result = scorer.score(matches)
        assert result.fault_domain == FaultDomain.WIFI
        assert result.confidence > 0.5

    def test_no_matches_returns_unknown(self):
        scorer = ConfidenceScorer()
        result = scorer.score([])
        assert result.fault_domain == FaultDomain.UNKNOWN
        assert result.confidence == 0.0

    def test_multiple_domains(self):
        matches = [
            SignalMatch(
                signal=Signal(FaultDomain.WIFI, "weak_signal", 0.9),
                evidence_ref="ref1",
            ),
            SignalMatch(
                signal=Signal(FaultDomain.ISP, "packet_loss_external", 0.8),
                evidence_ref="ref2",
            ),
            SignalMatch(
                signal=Signal(FaultDomain.ISP, "high_latency_external", 0.7),
                evidence_ref="ref3",
            ),
        ]
        scorer = ConfidenceScorer()
        result = scorer.score(matches)
        # ISP has more weight (0.8 + 0.7 = 1.5 vs 0.9)
        assert result.fault_domain == FaultDomain.ISP
        assert len(result.competing_hypotheses) >= 1

    def test_proximity_bias_tiebreaker(self):
        """When scores are equal, closer domains should win."""
        matches = [
            SignalMatch(
                signal=Signal(FaultDomain.WIFI, "weak_signal", 1.0),
                evidence_ref="ref1",
            ),
            SignalMatch(
                signal=Signal(FaultDomain.ISP, "packet_loss_external", 1.0),
                evidence_ref="ref2",
            ),
        ]
        scorer = ConfidenceScorer(proximity_bias=0.05)
        result = scorer.score(matches)
        # Wi-Fi is closer to user, so should win the tiebreak
        assert result.fault_domain == FaultDomain.WIFI


class TestFaultDomainEngine:
    def test_full_analysis(self):
        now = _now()
        envelopes = [
            _make_envelope("wifi", metrics=[
                Metric(measurement="wifi_link", fields={"rssi_dbm": -82}, timestamp=now),
            ]),
            _make_envelope("ping", metrics=[
                Metric(measurement="ping", fields={"loss_pct": 0.0, "rtt_avg_ms": 15.0},
                       tags={"target": "8.8.8.8"}, timestamp=now),
            ]),
        ]

        engine = FaultDomainEngine()
        result, correlations = engine.analyze(envelopes)

        assert result.fault_domain == FaultDomain.WIFI
        assert result.confidence > 0.0

    def test_no_problems(self):
        now = _now()
        envelopes = [
            _make_envelope("device", metrics=[
                Metric(measurement="device_cpu", fields={"percent": 20.0}, timestamp=now),
            ]),
            _make_envelope("ping", metrics=[
                Metric(measurement="ping", fields={"loss_pct": 0.0, "rtt_avg_ms": 10.0},
                       tags={"target": "8.8.8.8"}, timestamp=now),
            ]),
        ]

        engine = FaultDomainEngine()
        result, correlations = engine.analyze(envelopes)

        assert result.fault_domain == FaultDomain.UNKNOWN
        assert result.confidence == 0.0
