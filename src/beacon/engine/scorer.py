"""Confidence scorer — converts signal matches into per-domain confidence scores.

Uses weighted scoring with proximity bias: when scores are close, the engine
prefers the domain closest to the user (device → wifi → LAN → ISP → DNS →
app/SaaS). This follows the "check your own setup first" principle.
"""

from __future__ import annotations

from beacon.engine.rules import SignalMatch
from beacon.models.fault import CompetingHypothesis, FaultDomain, FaultDomainResult

# Proximity order — closer to the user comes first
PROXIMITY_ORDER: list[FaultDomain] = [
    FaultDomain.DEVICE,
    FaultDomain.WIFI,
    FaultDomain.LAN,
    FaultDomain.ISP,
    FaultDomain.DNS,
    FaultDomain.APP_SAAS,
    FaultDomain.VPN_SASE,
]

# Small bonus for domains closer to the user (tiebreaker)
PROXIMITY_BIAS = 0.05


class ConfidenceScorer:
    """Scores fault domains based on signal matches."""

    def __init__(self, proximity_bias: float = PROXIMITY_BIAS) -> None:
        self._proximity_bias = proximity_bias

    def score(self, matches: list[SignalMatch], total_metrics: int = 0) -> FaultDomainResult:
        """Compute confidence scores for each fault domain and return the result."""
        if not matches:
            return FaultDomainResult(
                fault_domain=FaultDomain.UNKNOWN,
                confidence=0.0,
                evidence_refs=[],
                competing_hypotheses=[],
            )

        # Aggregate weighted scores per domain
        domain_scores: dict[FaultDomain, float] = {}
        domain_evidence: dict[FaultDomain, list[str]] = {}

        for match in matches:
            domain = match.signal.domain
            domain_scores[domain] = domain_scores.get(domain, 0.0) + match.signal.weight
            if domain not in domain_evidence:
                domain_evidence[domain] = []
            domain_evidence[domain].append(match.evidence_ref)

        # Normalize scores to 0.0–1.0
        max_score = max(domain_scores.values()) if domain_scores else 1.0
        for domain in domain_scores:
            domain_scores[domain] /= max(max_score, 1.0)

        # Apply proximity bias
        for i, domain in enumerate(PROXIMITY_ORDER):
            if domain in domain_scores:
                bias = self._proximity_bias * (len(PROXIMITY_ORDER) - i) / len(PROXIMITY_ORDER)
                domain_scores[domain] += bias

        # Clamp to 1.0
        for domain in domain_scores:
            domain_scores[domain] = min(domain_scores[domain], 1.0)

        # Find the winner
        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
        winner_domain, winner_confidence = sorted_domains[0]

        # Build competing hypotheses from the rest
        hypotheses: list[CompetingHypothesis] = []
        for domain, conf in sorted_domains[1:]:
            hypotheses.append(
                CompetingHypothesis(
                    fault_domain=domain,
                    confidence=round(conf, 4),
                    reasoning=f"Scored {conf:.2f} based on {len(domain_evidence.get(domain, []))} signals",
                )
            )

        return FaultDomainResult(
            fault_domain=winner_domain,
            confidence=round(winner_confidence, 4),
            evidence_refs=domain_evidence.get(winner_domain, []),
            competing_hypotheses=hypotheses,
        )
