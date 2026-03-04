"""Dependency injection for FastAPI routes.

Provides singletons for settings, storage, registries, and the engine
via FastAPI's dependency injection system.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from beacon.config import BeaconSettings, get_settings
from beacon.engine.fault_domain import FaultDomainEngine
from beacon.evidence.builder import EvidencePackBuilder
from beacon.packs.executor import PackExecutor
from beacon.packs.registry import PackRegistry, PluginRegistry
from beacon.storage.artifacts import ArtifactStore
from beacon.storage.evidence_store import EvidenceStore
from beacon.storage.influx import InfluxStorage


@lru_cache
def get_beacon_settings() -> BeaconSettings:
    return get_settings()


@lru_cache
def get_plugin_registry() -> PluginRegistry:
    return PluginRegistry()


@lru_cache
def get_pack_registry() -> PackRegistry:
    registry = PackRegistry()
    packs_dir = Path("packs")
    if packs_dir.is_dir():
        registry.load_from_directory(packs_dir)
    return registry


@lru_cache
def get_artifact_store() -> ArtifactStore:
    settings = get_beacon_settings()
    return ArtifactStore(settings.storage.artifact_dir)


@lru_cache
def get_evidence_store() -> EvidenceStore:
    settings = get_beacon_settings()
    return EvidenceStore(settings.storage.evidence_dir)


@lru_cache
def get_fault_engine() -> FaultDomainEngine:
    return FaultDomainEngine()


@lru_cache
def get_evidence_builder() -> EvidencePackBuilder:
    settings = get_beacon_settings()
    return EvidencePackBuilder(settings, get_fault_engine())


def get_pack_executor() -> PackExecutor:
    settings = get_beacon_settings()
    return PackExecutor(
        plugin_registry=get_plugin_registry(),
        collector_url=settings.collector.url,
        collector_timeout=settings.collector.timeout_seconds,
    )


def get_influx_storage() -> InfluxStorage | None:
    """Get InfluxDB storage, returning None if unavailable."""
    try:
        settings = get_beacon_settings()
        storage = InfluxStorage(settings)
        if storage.health_check():
            return storage
    except Exception:
        pass
    return None
