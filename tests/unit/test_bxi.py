"""Tests for the Beacon Experience Index (BXI) scoring engine."""

from __future__ import annotations

import pytest

from beacon.api.bxi import BXIResult, compute_bxi


_HEALTHY = {
    "rtt_p95_ms": 0.0,
    "loss_pct": 0.0,
    "dns_p95_ms": 0.0,
    "http_p95_ms": 0.0,
    "jitter_ms": 0.0,
}


class TestBXIPerfectScore:
    """All metrics within thresholds → score 100."""

    def test_all_zeros(self):
        result = compute_bxi(_HEALTHY)
        assert result.score == 100
        assert result.label == "Excellent"
        assert result.color == "emerald"

    def test_no_data_is_critical(self):
        """Missing data (all None) should NOT be 100 — it means nothing works."""
        result = compute_bxi({})
        assert result.score == 0
        assert result.label == "Critical"
        assert result.color == "red"

    def test_all_below_threshold(self):
        result = compute_bxi(
            {
                "rtt_p95_ms": 15.0,
                "loss_pct": 0.0,
                "dns_p95_ms": 25.0,
                "http_p95_ms": 200.0,
                "jitter_ms": 3.0,
            }
        )
        assert result.score == 100

    def test_at_exact_thresholds(self):
        result = compute_bxi(
            {
                "rtt_p95_ms": 20.0,
                "loss_pct": 0.0,
                "dns_p95_ms": 30.0,
                "http_p95_ms": 300.0,
                "jitter_ms": 5.0,
            }
        )
        assert result.score == 100


class TestBXIIndividualPenalties:
    """Each metric penalty applies independently."""

    def test_rtt_penalty(self):
        # 45ms RTT → 25ms over → 1 step → -5
        result = compute_bxi({**_HEALTHY, "rtt_p95_ms": 45.0})
        assert result.score == 95

    def test_rtt_penalty_max_cap(self):
        # 200ms RTT → 180ms over → 7.2 steps → raw -36, capped at -30
        result = compute_bxi({**_HEALTHY, "rtt_p95_ms": 200.0})
        assert result.score == 70

    def test_loss_penalty(self):
        # 1% loss → -15
        result = compute_bxi({**_HEALTHY, "loss_pct": 1.0})
        assert result.score == 85

    def test_loss_penalty_max_cap(self):
        # 5% loss → raw -75, capped at -30
        result = compute_bxi({**_HEALTHY, "loss_pct": 5.0})
        assert result.score == 70

    def test_dns_penalty(self):
        # 80ms DNS → 50ms over → 1 step → -5
        result = compute_bxi({**_HEALTHY, "dns_p95_ms": 80.0})
        assert result.score == 95

    def test_dns_penalty_max_cap(self):
        # 330ms DNS → 300ms over → 6 steps → raw -30, capped at -20
        result = compute_bxi({**_HEALTHY, "dns_p95_ms": 330.0})
        assert result.score == 80

    def test_http_penalty(self):
        # 500ms HTTP → 200ms over → 1 step → -5
        result = compute_bxi({**_HEALTHY, "http_p95_ms": 500.0})
        assert result.score == 95

    def test_http_penalty_max_cap(self):
        # 1500ms HTTP → 1200ms over → 6 steps → raw -30, capped at -20
        result = compute_bxi({**_HEALTHY, "http_p95_ms": 1500.0})
        assert result.score == 80

    def test_jitter_penalty(self):
        # 10ms jitter → 5ms over → 1 step → -5
        result = compute_bxi({**_HEALTHY, "jitter_ms": 10.0})
        assert result.score == 95

    def test_jitter_penalty_max_cap(self):
        # 25ms jitter → 20ms over → 4 steps → raw -20, capped at -15
        result = compute_bxi({**_HEALTHY, "jitter_ms": 25.0})
        assert result.score == 85


class TestBXICombinedPenalties:
    """Multiple penalties compound."""

    def test_all_penalties_moderate(self):
        result = compute_bxi(
            {
                "rtt_p95_ms": 45.0,  # -5
                "loss_pct": 0.5,  # -7.5 → int(87.5) = 87
                "dns_p95_ms": 80.0,  # -5
                "http_p95_ms": 500.0,  # -5
                "jitter_ms": 10.0,  # -5
            }
        )
        assert result.score == 72

    def test_all_max_penalties(self):
        # All capped: -30 -30 -20 -20 -15 = -115 → 0 (floor)
        result = compute_bxi(
            {
                "rtt_p95_ms": 500.0,
                "loss_pct": 10.0,
                "dns_p95_ms": 500.0,
                "http_p95_ms": 2000.0,
                "jitter_ms": 50.0,
            }
        )
        assert result.score == 0


class TestBXIFloor:
    """Score never goes below 0."""

    def test_extreme_values(self):
        result = compute_bxi(
            {
                "rtt_p95_ms": 9999.0,
                "loss_pct": 100.0,
                "dns_p95_ms": 9999.0,
                "http_p95_ms": 99999.0,
                "jitter_ms": 9999.0,
            }
        )
        assert result.score == 0
        assert result.label == "Critical"
        assert result.color == "red"


class TestBXILabelBoundaries:
    """Verify label assignment at each boundary."""

    @pytest.mark.parametrize(
        "score_target,expected_label,expected_color",
        [
            (100, "Excellent", "emerald"),
            (90, "Excellent", "emerald"),
            (89, "Good", "cyan"),
            (70, "Good", "cyan"),
            (69, "Fair", "amber"),
            (50, "Fair", "amber"),
            (49, "Poor", "orange"),
            (30, "Poor", "orange"),
            (29, "Critical", "red"),
            (0, "Critical", "red"),
        ],
    )
    def test_label_boundaries(self, score_target, expected_label, expected_color):
        # Reverse-engineer a metric set that produces the target score.
        # Start from a healthy baseline and add penalties.
        penalty_needed = 100 - score_target
        # Use RTT penalty: each 25ms over threshold = -5 points.
        rtt_ms = 20.0 + (penalty_needed / 5.0) * 25.0
        # But cap at 30 — use loss for the rest
        if penalty_needed <= 30:
            result = compute_bxi({**_HEALTHY, "rtt_p95_ms": rtt_ms})
        else:
            # RTT caps at 30, use loss for the rest
            remaining = penalty_needed - 30
            if remaining <= 30:
                loss = remaining / 15.0
                result = compute_bxi({**_HEALTHY, "rtt_p95_ms": 200.0, "loss_pct": loss})
            else:
                remaining2 = remaining - 30
                if remaining2 <= 20:
                    dns = 30.0 + (remaining2 / 5.0) * 50.0
                    result = compute_bxi(
                        {
                            **_HEALTHY,
                            "rtt_p95_ms": 200.0,
                            "loss_pct": 5.0,
                            "dns_p95_ms": dns,
                        }
                    )
                else:
                    remaining3 = remaining2 - 20
                    http = 300.0 + (remaining3 / 5.0) * 200.0
                    result = compute_bxi(
                        {
                            **_HEALTHY,
                            "rtt_p95_ms": 200.0,
                            "loss_pct": 5.0,
                            "dns_p95_ms": 330.0,
                            "http_p95_ms": http,
                        }
                    )

        assert result.label == expected_label
        assert result.color == expected_color


class TestBXIResultStructure:
    """Verify result dataclass fields."""

    def test_result_fields(self):
        result = compute_bxi({**_HEALTHY, "rtt_p95_ms": 45.0})
        assert isinstance(result, BXIResult)
        assert isinstance(result.components, dict)
        assert "rtt_penalty" in result.components
        assert "loss_penalty" in result.components
        assert "dns_penalty" in result.components
        assert "http_penalty" in result.components
        assert "jitter_penalty" in result.components

    def test_result_is_frozen(self):
        result = compute_bxi(_HEALTHY)
        with pytest.raises(AttributeError):
            result.score = 50
