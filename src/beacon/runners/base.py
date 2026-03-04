"""Base test runner abstract class with RunnerConfig.

Runners are active tests (ping, DNS, HTTP, traceroute) that produce
metrics and events. Each runner accepts a RunnerConfig from the pack
definition to customize targets, timeouts, and thresholds.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from beacon.models.envelope import PluginEnvelope

logger = logging.getLogger(__name__)


class RunnerConfig(BaseModel):
    """Configuration passed to a runner from a pack definition."""

    targets: list[str] = Field(default_factory=list)
    count: int = 10
    timeout_seconds: int = 10
    interval: float = 0.5
    extra: dict[str, Any] = Field(default_factory=dict)


class BaseTestRunner(ABC):
    """Abstract base class for all Beacon test runners."""

    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    def run(self, run_id: UUID, config: RunnerConfig) -> PluginEnvelope:
        """Execute the test and return a PluginEnvelope."""
        ...

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _empty_envelope(self, run_id: UUID) -> PluginEnvelope:
        now = self._now()
        return PluginEnvelope(
            plugin_name=self.name,
            plugin_version=self.version,
            run_id=run_id,
            started_at=now,
            completed_at=now,
        )
