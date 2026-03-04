"""Base collector abstract class.

All collectors inherit from BaseCollector and implement the collect() method.
Each returns a PluginEnvelope with metrics, events, and optional artifacts.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID

from beacon.models.envelope import PluginEnvelope

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all Beacon collectors."""

    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    def collect(self, run_id: UUID) -> PluginEnvelope:
        """Execute collection and return a PluginEnvelope."""
        ...

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _empty_envelope(self, run_id: UUID) -> PluginEnvelope:
        """Create an empty envelope with timestamps set."""
        now = self._now()
        return PluginEnvelope(
            plugin_name=self.name,
            plugin_version=self.version,
            run_id=run_id,
            started_at=now,
            completed_at=now,
        )
