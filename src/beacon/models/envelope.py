"""Plugin Envelope — the universal contract for all collectors, runners, and event sources.

Every plugin returns a PluginEnvelope containing metrics, events, artifacts, and notes.
This uniform shape means new plugins can be added without changing core logic.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Metric(BaseModel):
    """A single measurement data point."""

    measurement: str
    fields: dict[str, float | int | str | bool]
    tags: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime


class Event(BaseModel):
    """A discrete event detected during collection or analysis."""

    event_type: str
    severity: Severity
    message: str
    tags: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime


class Artifact(BaseModel):
    """A file artifact produced during a run (pcap, log, JSON dump, etc.)."""

    artifact_type: str
    ref: str
    sha256: str
    ttl_hours: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginEnvelope(BaseModel):
    """Universal output wrapper for every plugin.

    This is the single shape that flows through the entire pipeline:
    plugin → storage → engine → evidence pack.
    """

    plugin_name: str
    plugin_version: str
    run_id: UUID
    metrics: list[Metric] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
