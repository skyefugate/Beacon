"""BaseExporter — ABC for telemetry export destinations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from beacon.models.envelope import Metric


class BaseExporter(ABC):
    """Abstract base for telemetry exporters."""

    name: str = "base"

    @abstractmethod
    async def export(self, metrics: list[Metric]) -> int:
        """Export a batch of metrics. Returns count successfully exported."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        ...
