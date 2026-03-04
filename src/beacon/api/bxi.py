"""Beacon Experience Index (BXI) — composite 0-100 network quality score.

Pure scoring function with no external dependencies. Computes a weighted
penalty-based score from aggregated telemetry metrics.

Score = 100 minus penalties:
  RTT p95 > 20ms:    -5 per 25ms over    (max -30)
  Packet loss > 0%:  -15 per 1%           (max -30)
  DNS p95 > 30ms:    -5 per 50ms over     (max -20)
  HTTP p95 > 300ms:  -5 per 200ms over    (max -20)
  Jitter > 5ms:      -5 per 5ms over      (max -15)
  Floor at 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BXIResult:
    """Computed BXI score with label and color."""

    score: int
    label: str
    color: str
    components: dict[str, float]


# Label/color bands: (min_score, label, tailwind_color)
_BANDS: list[tuple[int, str, str]] = [
    (90, "Excellent", "emerald"),
    (70, "Good", "cyan"),
    (50, "Fair", "amber"),
    (30, "Poor", "orange"),
    (0, "Critical", "red"),
]


def _label_and_color(score: int) -> tuple[str, str]:
    """Map a 0-100 score to a label and color."""
    for min_score, label, color in _BANDS:
        if score >= min_score:
            return label, color
    return "Critical", "red"


def _penalty(value: float, threshold: float, rate: float, step: float, cap: float) -> float:
    """Compute a capped linear penalty.

    Args:
        value: The observed metric value.
        threshold: Value below which no penalty applies.
        rate: Penalty points per step over threshold.
        step: Size of each penalty step (denominator).
        cap: Maximum penalty (positive number).

    Returns:
        Penalty as a positive number (to be subtracted from 100).
    """
    if value <= threshold:
        return 0.0
    excess = value - threshold
    raw = (excess / step) * rate
    return min(raw, cap)


def compute_bxi(metrics: dict[str, Any]) -> BXIResult:
    """Compute BXI from a flat dict of latest aggregated metrics.

    Expected keys (all optional):
        rtt_p95_ms: float | None  — Internet RTT p95
        loss_pct: float | None    — Packet loss percentage
        dns_p95_ms: float | None  — DNS resolution p95
        http_p95_ms: float | None — HTTP total time p95
        jitter_ms: float | None   — RTT jitter (std dev or IQR)

    A value of None means "no data available" — the metric could not be
    measured (e.g. network is down, sampler not running). This is treated
    as a full penalty for that metric because unmeasurable ≠ perfect.
    """
    rtt_raw = metrics.get("rtt_p95_ms")
    loss_raw = metrics.get("loss_pct")
    dns_raw = metrics.get("dns_p95_ms")
    http_raw = metrics.get("http_p95_ms")
    jitter_raw = metrics.get("jitter_ms")

    # None → max penalty (unmeasurable means broken, not perfect)
    p_rtt = 30.0 if rtt_raw is None else _penalty(float(rtt_raw), threshold=20.0, rate=5.0, step=25.0, cap=30.0)
    p_loss = 30.0 if loss_raw is None else _penalty(float(loss_raw), threshold=0.0, rate=15.0, step=1.0, cap=30.0)
    p_dns = 20.0 if dns_raw is None else _penalty(float(dns_raw), threshold=30.0, rate=5.0, step=50.0, cap=20.0)
    p_http = 20.0 if http_raw is None else _penalty(float(http_raw), threshold=300.0, rate=5.0, step=200.0, cap=20.0)
    p_jitter = 15.0 if jitter_raw is None else _penalty(float(jitter_raw), threshold=5.0, rate=5.0, step=5.0, cap=15.0)

    raw = 100.0 - p_rtt - p_loss - p_dns - p_http - p_jitter
    score = max(0, int(raw))

    label, color = _label_and_color(score)

    return BXIResult(
        score=score,
        label=label,
        color=color,
        components={
            "rtt_penalty": round(p_rtt, 2),
            "loss_penalty": round(p_loss, 2),
            "dns_penalty": round(p_dns, 2),
            "http_penalty": round(p_http, 2),
            "jitter_penalty": round(p_jitter, 2),
        },
    )
