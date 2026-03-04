"""YAML + environment variable configuration loading.

Configuration is resolved in order of priority (highest wins):
1. Environment variables (BEACON_*, INFLUXDB_*, COLLECTOR_*)
2. YAML config file (beacon.yaml)
3. Built-in defaults
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


def _load_yaml_config(path: Path | None = None) -> dict[str, Any]:
    """Load YAML config file, returning empty dict if not found."""
    if path is None:
        candidates = [
            Path("beacon.yaml"),
            Path("/etc/beacon/beacon.yaml"),
            Path.home() / ".config" / "beacon" / "beacon.yaml",
        ]
        for candidate in candidates:
            if candidate.is_file():
                path = candidate
                break
    if path is None or not path.is_file():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data


class InfluxDBSettings(BaseSettings):
    url: str = "http://localhost:8086"
    token: str = "beacon-dev-token"
    org: str = "beacon"
    bucket: str = "beacon"

    model_config = {"env_prefix": "INFLUXDB_"}


class CollectorSettings(BaseSettings):
    url: str = "http://localhost:9100"
    timeout_seconds: int = 30

    model_config = {"env_prefix": "COLLECTOR_"}


class StorageSettings(BaseSettings):
    data_dir: Path = Path("./data")
    artifact_dir: Path = Path("./data/artifacts")
    evidence_dir: Path = Path("./data/evidence")

    model_config = {"env_prefix": "BEACON_"}


class TelemetrySettings(BaseSettings):
    """Configuration for the continuous telemetry subsystem."""

    enabled: bool = True
    window_seconds: int = 60

    # Buffer
    buffer_path: Path = Path("./data/telemetry.db")
    buffer_max_mb: int = 100
    buffer_retention_days: int = 7

    # Tier 0 sampling intervals (seconds)
    tier0_wifi_interval: int = 10
    tier0_ping_interval: int = 10
    tier0_dns_interval: int = 30
    tier0_http_interval: int = 30
    tier0_device_interval: int = 15

    # Tier 1 / Tier 2 intervals (activated by escalation)
    tier1_wifi_quality_interval: int = 5
    tier1_tls_interval: int = 30
    tier1_vpn_interval: int = 30
    tier2_bufferbloat_interval: int = 60

    # Context sampler
    tier0_context_interval: int = 60
    context_public_ip_ttl: int = 300
    context_geo_ttl: int = 900
    context_geo_enabled: bool = True

    tier0_dhcp_interval: int = 60

    # Change detection
    change_detection_interval: int = 10

    # Export — InfluxDB
    export_influx_enabled: bool = True
    export_influx_bucket: str = "beacon_telemetry"
    export_batch_size: int = 500
    export_flush_interval: int = 10  # seconds

    # Export — JSONL file
    export_file_enabled: bool = False
    export_file_path: Path = Path("./data/telemetry.jsonl")
    export_file_max_mb: int = 10
    export_file_max_files: int = 5

    # Escalation
    escalation_cooldown_seconds: int = 300
    escalation_flap_window: int = 600
    escalation_flap_count: int = 3

    # Governor
    governor_cpu_soft_pct: float = 5.0
    governor_cpu_hard_pct: float = 10.0
    governor_memory_max_mb: int = 100
    governor_battery_low_pct: int = 20
    governor_battery_critical_pct: int = 10

    # Ping targets for telemetry
    ping_gateway: bool = True
    ping_targets: list[str] = Field(default_factory=lambda: ["8.8.8.8"])
    dns_resolvers: list[str] = Field(default_factory=lambda: ["8.8.8.8"])
    dns_domains: list[str] = Field(default_factory=lambda: ["google.com"])
    http_targets: list[str] = Field(
        default_factory=lambda: ["https://www.google.com"],
    )

    model_config = {"env_prefix": "BEACON_TELEMETRY_"}


class BeaconSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    probe_id: str = "beacon-01"
    config_path: Path | None = Field(default=None, exclude=True)

    influxdb: InfluxDBSettings = Field(default_factory=InfluxDBSettings)
    collector: CollectorSettings = Field(default_factory=CollectorSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)

    model_config = {"env_prefix": "BEACON_"}

    @classmethod
    def load(cls, config_path: Path | None = None) -> BeaconSettings:
        """Load settings from YAML + env vars.

        YAML values are used as defaults, but env vars always win
        because pydantic-settings reads them at init time.
        """
        yaml_data = _load_yaml_config(config_path)
        beacon_block = yaml_data.get("beacon", {})

        influx_yaml = yaml_data.get("influxdb", {})
        collector_yaml = yaml_data.get("collector", {})
        storage_yaml = yaml_data.get("storage", {})
        telemetry_yaml = yaml_data.get("telemetry", {})

        influx = InfluxDBSettings(
            **{
                k: v
                for k, v in influx_yaml.items()
                if k in InfluxDBSettings.model_fields
                and os.environ.get(f"INFLUXDB_{k.upper()}") is None
            }
        )
        collector = CollectorSettings(
            **{
                k: v
                for k, v in collector_yaml.items()
                if k in CollectorSettings.model_fields
                and os.environ.get(f"COLLECTOR_{k.upper()}") is None
            }
        )
        storage = StorageSettings(
            **{
                k: v
                for k, v in storage_yaml.items()
                if k in StorageSettings.model_fields
                and os.environ.get(f"BEACON_{k.upper()}") is None
            }
        )
        telemetry = TelemetrySettings(
            **{
                k: v
                for k, v in telemetry_yaml.items()
                if k in TelemetrySettings.model_fields
                and os.environ.get(f"BEACON_TELEMETRY_{k.upper()}") is None
            }
        )

        top_kwargs: dict[str, Any] = {}
        for key in ("host", "port", "log_level", "probe_id"):
            if key in beacon_block and os.environ.get(f"BEACON_{key.upper()}") is None:
                top_kwargs[key] = beacon_block[key]

        return cls(
            config_path=config_path,
            influxdb=influx,
            collector=collector,
            storage=storage,
            telemetry=telemetry,
            **top_kwargs,
        )


# Module-level singleton, lazily initialized
_settings: BeaconSettings | None = None


def get_settings(config_path: Path | None = None) -> BeaconSettings:
    """Get or create the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = BeaconSettings.load(config_path)
    return _settings


def reset_settings() -> None:
    """Reset the singleton (useful for testing)."""
    global _settings
    _settings = None
