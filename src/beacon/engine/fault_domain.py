"""Fault domain engine orchestrator — ties rules, correlator, and scorer together.

This is the main entry point for fault domain analysis. Given a set of
PluginEnvelopes from a pack run, it evaluates heuristic rules, correlates
events with metrics, scores each domain, and produces a FaultDomainResult.
"""

from __future__ import annotations

from beacon.engine.correlator import EventCorrelator
from beacon.engine.rules import HeuristicRuleSet
from beacon.engine.scorer import ConfidenceScorer
from beacon.events.threshold import ThresholdMonitor
from beacon.models.envelope import Metric, PluginEnvelope
from beacon.models.evidence import EventCorrelation
from beacon.models.fault import FaultDomainResult


class FaultDomainEngine:
    """Top-level fault domain analysis engine."""

    def __init__(
        self,
        rules: HeuristicRuleSet | None = None,
        correlator: EventCorrelator | None = None,
        scorer: ConfidenceScorer | None = None,
        threshold_monitor: ThresholdMonitor | None = None,
    ) -> None:
        self._rules = rules or HeuristicRuleSet()
        self._correlator = correlator or EventCorrelator()
        self._scorer = scorer or ConfidenceScorer()
        self._threshold_monitor = threshold_monitor or ThresholdMonitor()

    def analyze(
        self, envelopes: list[PluginEnvelope]
    ) -> tuple[FaultDomainResult, list[EventCorrelation]]:
        """Run full fault domain analysis.

        Returns:
            Tuple of (FaultDomainResult, list of EventCorrelations)
        """
        # Step 0: Run threshold monitor on all metrics to generate events
        all_metrics: list[Metric] = []
        for env in envelopes:
            all_metrics.extend(env.metrics)

        threshold_events = self._threshold_monitor.evaluate(all_metrics)

        # Inject threshold events into envelopes so they flow through the pipeline.
        # We add them to the first envelope (or a synthetic one) so they're visible
        # in the evidence pack's test_results.
        if threshold_events and envelopes:
            envelopes[0].events.extend(threshold_events)

        # Step 1: Evaluate heuristic rules to find signal matches
        signal_matches = self._rules.evaluate(envelopes)

        # Step 2: Correlate events with metrics
        correlations = self._correlator.correlate(envelopes)

        # Step 3: Score domains based on signal matches
        result = self._scorer.score(signal_matches, total_metrics=len(all_metrics))

        return result, correlations
