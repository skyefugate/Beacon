"""Pack definition schema — Pydantic models for YAML pack files.

A pack defines which collectors and runners to execute, their configuration,
and the order of execution. Packs are the primary user-facing abstraction.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StepConfig(BaseModel):
    """Configuration for a single step in a pack."""

    plugin: str  # e.g., "ping", "dns", "device"
    type: str = "runner"  # "collector" or "runner"
    enabled: bool = True
    privileged: bool = False  # Runs on collector sidecar if True
    config: dict[str, Any] = Field(default_factory=dict)


class PackDefinition(BaseModel):
    """A complete pack definition, typically loaded from YAML."""

    name: str
    description: str = ""
    version: str = "1.0"
    timeout_seconds: int = 120
    steps: list[StepConfig] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def collector_steps(self) -> list[StepConfig]:
        """Return only enabled collector steps."""
        return [s for s in self.steps if s.type == "collector" and s.enabled]

    def runner_steps(self) -> list[StepConfig]:
        """Return only enabled runner steps."""
        return [s for s in self.steps if s.type == "runner" and s.enabled]

    def privileged_steps(self) -> list[StepConfig]:
        """Return steps that require the privileged collector sidecar."""
        return [s for s in self.steps if s.privileged and s.enabled]
