"""Resource governor — monitors CPU, memory, and battery to throttle telemetry.

Returns GovernorAdvice with the maximum tier allowed, an interval multiplier,
and a suspend flag for extreme conditions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)


@dataclass
class GovernorAdvice:
    """Advice from the resource governor."""

    max_tier: int  # Maximum sampler tier allowed (0, 1, or 2)
    interval_multiplier: float  # Multiply sampler intervals by this factor
    suspend: bool  # If True, suspend all sampling
    reason: str = ""


class ResourceGovernor:
    """Monitors system resources and advises the scheduler on throttling."""

    def __init__(
        self,
        cpu_soft_pct: float = 5.0,
        cpu_hard_pct: float = 10.0,
        memory_max_mb: int = 100,
        battery_low_pct: int = 20,
        battery_critical_pct: int = 10,
    ) -> None:
        self._cpu_soft = cpu_soft_pct
        self._cpu_hard = cpu_hard_pct
        self._memory_max_mb = memory_max_mb
        self._battery_low = battery_low_pct
        self._battery_critical = battery_critical_pct

    def check(self) -> GovernorAdvice:
        """Check system resources and return advice."""
        cpu_pct = psutil.cpu_percent(interval=0)
        memory_mb = psutil.Process().memory_info().rss / (1024 * 1024)

        battery = self._get_battery()

        # Battery critical — suspend
        if battery is not None and battery <= self._battery_critical:
            return GovernorAdvice(
                max_tier=0,
                interval_multiplier=1.0,
                suspend=True,
                reason=f"Battery critical: {battery}%",
            )

        # CPU hard limit — restrict to Tier 0 with 3x intervals
        if cpu_pct > self._cpu_hard:
            return GovernorAdvice(
                max_tier=0,
                interval_multiplier=3.0,
                suspend=False,
                reason=f"CPU hard limit: {cpu_pct:.0f}% > {self._cpu_hard}%",
            )

        # Memory limit — restrict to Tier 0 with 2x intervals
        if memory_mb > self._memory_max_mb:
            return GovernorAdvice(
                max_tier=0,
                interval_multiplier=2.0,
                suspend=False,
                reason=f"Memory limit: {memory_mb:.0f}MB > {self._memory_max_mb}MB",
            )

        # CPU soft limit — restrict to Tier 1 with 2x intervals
        if cpu_pct > self._cpu_soft:
            return GovernorAdvice(
                max_tier=1,
                interval_multiplier=2.0,
                suspend=False,
                reason=f"CPU soft limit: {cpu_pct:.0f}% > {self._cpu_soft}%",
            )

        # Battery low — restrict to Tier 1
        if battery is not None and battery <= self._battery_low:
            return GovernorAdvice(
                max_tier=1,
                interval_multiplier=1.5,
                suspend=False,
                reason=f"Battery low: {battery}%",
            )

        # All clear
        return GovernorAdvice(
            max_tier=2,
            interval_multiplier=1.0,
            suspend=False,
        )

    @staticmethod
    def _get_battery() -> int | None:
        """Get battery percentage, or None if no battery / not supported."""
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                return None
            return int(battery.percent)
        except (AttributeError, RuntimeError):
            return None
