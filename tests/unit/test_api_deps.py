"""Tests for API dependency injection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from beacon.api.deps import (
    get_artifact_store,
    get_beacon_settings,
    get_evidence_builder,
    get_evidence_store,
    get_fault_engine,
    get_influx_storage,
    get_pack_executor,
    get_pack_registry,
    get_plugin_registry,
)
from beacon.config import BeaconSettings
from beacon.engine.fault_domain import FaultDomainEngine
from beacon.evidence.builder import EvidencePackBuilder
from beacon.packs.executor import PackExecutor
from beacon.packs.registry import PackRegistry, PluginRegistry
from beacon.storage.artifacts import ArtifactStore
from beacon.storage.evidence_store import EvidenceStore
from beacon.storage.influx import InfluxStorage


class TestDependencyInjection:
    """Test dependency injection functions."""

    def test_get_beacon_settings(self):
        """Test get_beacon_settings returns BeaconSettings instance."""
        settings = get_beacon_settings()
        assert isinstance(settings, BeaconSettings)

    def test_get_plugin_registry(self):
        """Test get_plugin_registry returns PluginRegistry instance."""
        registry = get_plugin_registry()
        assert isinstance(registry, PluginRegistry)

    @patch("beacon.api.deps.Path.is_dir")
    @patch("beacon.packs.registry.PackRegistry.load_from_directory")
    def test_get_pack_registry_with_packs_dir(self, mock_load, mock_is_dir):
        """Test get_pack_registry loads from packs directory when it exists."""
        mock_is_dir.return_value = True

        # Clear cache to ensure fresh call
        get_pack_registry.cache_clear()

        registry = get_pack_registry()
        assert isinstance(registry, PackRegistry)
        mock_load.assert_called_once_with(Path("packs"))

    @patch("beacon.api.deps.Path.is_dir")
    def test_get_pack_registry_without_packs_dir(self, mock_is_dir):
        """Test get_pack_registry works when packs directory doesn't exist."""
        mock_is_dir.return_value = False

        # Clear cache to ensure fresh call
        get_pack_registry.cache_clear()

        registry = get_pack_registry()
        assert isinstance(registry, PackRegistry)

    @patch("beacon.api.deps.get_beacon_settings")
    def test_get_artifact_store(self, mock_settings):
        """Test get_artifact_store returns ArtifactStore instance."""
        mock_settings.return_value.storage.artifact_dir = Path("/tmp/artifacts")

        # Clear cache to ensure fresh call
        get_artifact_store.cache_clear()

        store = get_artifact_store()
        assert isinstance(store, ArtifactStore)

    @patch("beacon.api.deps.get_beacon_settings")
    def test_get_evidence_store(self, mock_settings):
        """Test get_evidence_store returns EvidenceStore instance."""
        mock_settings.return_value.storage.evidence_dir = Path("/tmp/evidence")

        # Clear cache to ensure fresh call
        get_evidence_store.cache_clear()

        store = get_evidence_store()
        assert isinstance(store, EvidenceStore)

    def test_get_fault_engine(self):
        """Test get_fault_engine returns FaultDomainEngine instance."""
        engine = get_fault_engine()
        assert isinstance(engine, FaultDomainEngine)

    @patch("beacon.api.deps.get_beacon_settings")
    @patch("beacon.api.deps.get_fault_engine")
    def test_get_evidence_builder(self, mock_engine, mock_settings):
        """Test get_evidence_builder returns EvidencePackBuilder instance."""
        mock_settings.return_value = BeaconSettings()
        mock_engine.return_value = MagicMock()

        # Clear cache to ensure fresh call
        get_evidence_builder.cache_clear()

        builder = get_evidence_builder()
        assert isinstance(builder, EvidencePackBuilder)

    @patch("beacon.api.deps.get_beacon_settings")
    @patch("beacon.api.deps.get_plugin_registry")
    def test_get_pack_executor(self, mock_plugin_registry, mock_settings):
        """Test get_pack_executor returns PackExecutor instance."""
        mock_settings.return_value.collector.url = "http://localhost:8080"
        mock_settings.return_value.collector.timeout_seconds = 30
        mock_plugin_registry.return_value = MagicMock()

        executor = get_pack_executor()
        assert isinstance(executor, PackExecutor)

    @patch("beacon.api.deps.get_beacon_settings")
    @patch("beacon.storage.influx.InfluxStorage.health_check")
    def test_get_influx_storage_healthy(self, mock_health_check, mock_settings):
        """Test get_influx_storage returns InfluxStorage when healthy."""
        mock_settings.return_value = BeaconSettings()
        mock_health_check.return_value = True

        with patch("beacon.storage.influx.InfluxStorage.__init__", return_value=None):
            storage = get_influx_storage()
            assert isinstance(storage, InfluxStorage)

    @patch("beacon.api.deps.get_beacon_settings")
    @patch("beacon.storage.influx.InfluxStorage.health_check")
    def test_get_influx_storage_unhealthy(self, mock_health_check, mock_settings):
        """Test get_influx_storage returns None when unhealthy."""
        mock_settings.return_value = BeaconSettings()
        mock_health_check.return_value = False

        with patch("beacon.storage.influx.InfluxStorage.__init__", return_value=None):
            storage = get_influx_storage()
            assert storage is None

    @patch("beacon.api.deps.get_beacon_settings")
    def test_get_influx_storage_exception(self, mock_settings):
        """Test get_influx_storage returns None when exception occurs."""
        mock_settings.side_effect = Exception("Connection failed")

        storage = get_influx_storage()
        assert storage is None

    def test_dependency_caching(self):
        """Test that dependencies are properly cached."""
        # Test that multiple calls return the same instance
        settings1 = get_beacon_settings()
        settings2 = get_beacon_settings()
        assert settings1 is settings2

        plugin_registry1 = get_plugin_registry()
        plugin_registry2 = get_plugin_registry()
        assert plugin_registry1 is plugin_registry2

        fault_engine1 = get_fault_engine()
        fault_engine2 = get_fault_engine()
        assert fault_engine1 is fault_engine2

    def teardown_method(self):
        """Clear caches after each test."""
        get_beacon_settings.cache_clear()
        get_plugin_registry.cache_clear()
        get_pack_registry.cache_clear()
        get_artifact_store.cache_clear()
        get_evidence_store.cache_clear()
        get_fault_engine.cache_clear()
        get_evidence_builder.cache_clear()
