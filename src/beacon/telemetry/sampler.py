"""BaseSampler — async ABC for all telemetry samplers.

Unlike BaseCollector (sync, returns full PluginEnvelope), BaseSampler
is async and returns lightweight list[Metric] for high-frequency sampling.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from beacon.models.envelope import Metric

logger = logging.getLogger(__name__)


class BaseSampler(ABC):
    """Abstract base class for telemetry samplers."""

    name: str = "base"
    tier: int = 0
    default_interval: int = 10  # seconds

    @abstractmethod
    async def sample(self) -> list[Metric]:
        """Collect one round of metrics. Must be non-blocking."""
        ...

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
