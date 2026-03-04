"""Tests for SIGHUP config reload in the telemetry daemon."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

import beacon.config as _cfg_mod
from beacon.config import BeaconSettings, TelemetrySettings
from beacon.telemetry.daemon import _build_scheduler, apply_config_reload


def _make_settings(**telemetry_kwargs) -> BeaconSettings:
    """Return a BeaconSettings with default telemetry, optionally overriding fields."""
    settings = BeaconSettings()
    settings.telemetry.export_influx_enabled = False
    settings.telemetry.export_file_enabled = False
    for k, v in telemetry_kwargs.items():
        setattr(settings.telemetry, k, v)
    return settings


class TestApplyConfigReload:
    """Unit tests for apply_config_reload()."""

    def _scheduler(self, settings: BeaconSettings):
        return _build_scheduler(settings)

    def test_interval_change_calls_set_interval(self):
        old_settings = _make_settings(tier0_ping_interval=10)
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(tier0_ping_interval=5)

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        assert scheduler._interval_overrides.get("ping") == 5

    def test_unchanged_interval_not_set(self):
        old_settings = _make_settings(tier0_ping_interval=10)
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(tier0_ping_interval=10)

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        assert "ping" not in scheduler._interval_overrides

    def test_all_sampler_intervals_can_be_changed(self):
        old_settings = _make_settings()
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(
            tier0_wifi_interval=99,
            tier0_ping_interval=99,
            tier0_dns_interval=99,
            tier0_http_interval=99,
            tier0_device_interval=99,
            tier0_context_interval=99,
            change_detection_interval=99,
        )

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        for name in ("wifi", "ping", "dns", "http", "device", "context", "change"):
            assert scheduler._interval_overrides.get(name) == 99, f"{name} not updated"

    def test_ping_targets_updated(self):
        old_settings = _make_settings(ping_targets=["8.8.8.8"])
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(ping_targets=["1.1.1.1", "9.9.9.9"])

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        ping_sampler = next(s for s in scheduler._samplers if s.name == "ping")
        assert ping_sampler._targets == ["1.1.1.1", "9.9.9.9"]

    def test_dns_resolvers_and_domains_updated(self):
        old_settings = _make_settings(
            dns_resolvers=["8.8.8.8"],
            dns_domains=["google.com"],
        )
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(
            dns_resolvers=["1.1.1.1"],
            dns_domains=["example.com", "cloudflare.com"],
        )

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        dns_sampler = next(s for s in scheduler._samplers if s.name == "dns")
        assert dns_sampler._resolvers == ["1.1.1.1"]
        assert dns_sampler._domains == ["example.com", "cloudflare.com"]

    def test_http_targets_updated(self):
        old_settings = _make_settings(http_targets=["https://google.com"])
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(http_targets=["https://cloudflare.com"])

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        http_sampler = next(s for s in scheduler._samplers if s.name == "http")
        assert http_sampler._targets == ["https://cloudflare.com"]

    def test_scheduler_settings_ref_updated(self):
        old_settings = _make_settings()
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings()

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        assert scheduler._settings is new_settings

    def test_restart_required_fields_logged_as_warning(self, caplog):
        old_settings = _make_settings()
        old_settings.telemetry.buffer_path = "/old/path/telemetry.db"  # type: ignore[assignment]
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings()
        new_settings.telemetry.buffer_path = "/new/path/telemetry.db"  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING, logger="beacon.telemetry.daemon"):
            apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        assert any(
            "buffer_path" in r.message and "full restart required" in r.message
            for r in caplog.records
        )

    def test_info_logged_for_changed_intervals(self, caplog):
        old_settings = _make_settings(tier0_ping_interval=10)
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(tier0_ping_interval=3)

        with caplog.at_level(logging.INFO, logger="beacon.telemetry.daemon"):
            apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        assert any(
            "ping" in r.message and "interval" in r.message
            for r in caplog.records
        )

    def test_no_changes_no_interval_overrides(self):
        old_settings = _make_settings()
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings()

        apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        assert scheduler._interval_overrides == {}

    def test_export_field_change_logged_at_info(self, caplog):
        old_settings = _make_settings(export_influx_bucket="old_bucket")
        scheduler = self._scheduler(old_settings)
        new_settings = _make_settings(export_influx_bucket="new_bucket")

        with caplog.at_level(logging.INFO, logger="beacon.telemetry.daemon"):
            apply_config_reload(scheduler, old_settings.telemetry, new_settings)

        assert any(
            "export_influx_bucket" in r.message
            for r in caplog.records
        )
