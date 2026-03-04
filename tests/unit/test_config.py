"""Unit tests for configuration loading."""

from __future__ import annotations


import pytest

from beacon.config import BeaconSettings, reset_settings, get_settings, _load_yaml_config


@pytest.fixture(autouse=True)
def _reset():
    """Reset settings singleton between tests."""
    reset_settings()
    yield
    reset_settings()


class TestYAMLLoading:
    def test_load_existing_yaml(self, tmp_path):
        config_file = tmp_path / "beacon.yaml"
        config_file.write_text(
            "beacon:\n  port: 9999\n  probe_id: test-probe\n"
            "influxdb:\n  bucket: test-bucket\n"
        )
        data = _load_yaml_config(config_file)
        assert data["beacon"]["port"] == 9999
        assert data["influxdb"]["bucket"] == "test-bucket"

    def test_load_missing_yaml(self, tmp_path):
        data = _load_yaml_config(tmp_path / "nonexistent.yaml")
        assert data == {}

    def test_load_empty_yaml(self, tmp_path):
        config_file = tmp_path / "beacon.yaml"
        config_file.write_text("")
        data = _load_yaml_config(config_file)
        assert data == {}


class TestBeaconSettings:
    def test_defaults(self):
        settings = BeaconSettings()
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
        assert settings.log_level == "info"
        assert settings.probe_id == "beacon-01"

    def test_influxdb_defaults(self):
        settings = BeaconSettings()
        assert settings.influxdb.org == "beacon"
        assert settings.influxdb.bucket == "beacon"

    def test_load_from_yaml(self, tmp_path, monkeypatch):
        config_file = tmp_path / "beacon.yaml"
        config_file.write_text(
            "beacon:\n  port: 3000\n  probe_id: yaml-probe\n"
            "influxdb:\n  bucket: yaml-bucket\n"
            "collector:\n  timeout_seconds: 60\n"
        )
        # Clear env vars that would override YAML
        for key in ("BEACON_PORT", "BEACON_PROBE_ID", "INFLUXDB_BUCKET", "COLLECTOR_TIMEOUT_SECONDS"):
            monkeypatch.delenv(key, raising=False)

        settings = BeaconSettings.load(config_file)
        assert settings.port == 3000
        assert settings.probe_id == "yaml-probe"
        assert settings.influxdb.bucket == "yaml-bucket"
        assert settings.collector.timeout_seconds == 60

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        config_file = tmp_path / "beacon.yaml"
        config_file.write_text("beacon:\n  port: 3000\n")
        monkeypatch.setenv("BEACON_PORT", "5555")

        settings = BeaconSettings.load(config_file)
        assert settings.port == 5555

    def test_get_settings_singleton(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_settings(self):
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2
