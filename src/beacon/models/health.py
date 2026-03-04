"""Health snapshot models for device status at the time of a diagnostic run."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CPUHealth(BaseModel):
    percent: float
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float
    core_count: int


class MemoryHealth(BaseModel):
    total_mb: float
    available_mb: float
    percent_used: float


class DiskHealth(BaseModel):
    path: str
    total_gb: float
    free_gb: float
    percent_used: float


class ThermalHealth(BaseModel):
    label: str
    current_celsius: float
    high_celsius: float | None = None
    critical_celsius: float | None = None


class HealthSnapshot(BaseModel):
    """Point-in-time device health captured during a diagnostic run."""

    cpu: CPUHealth
    memory: MemoryHealth
    disks: list[DiskHealth] = Field(default_factory=list)
    thermals: list[ThermalHealth] = Field(default_factory=list)
