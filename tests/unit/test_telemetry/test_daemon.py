"""Tests for daemon — PID file, build_scheduler, signal handling."""

from __future__ import annotations

from unittest.mock import patch


from beacon.config import BeaconSettings
from beacon.telemetry.daemon import _build_scheduler, read_pid


class TestDaemon:
    def test_read_pid_no_file(self, tmp_path):
        with patch("beacon.telemetry.daemon._PID_FILE", tmp_path / "nonexistent.pid"):
            assert read_pid() is None

    def test_read_pid_stale(self, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("99999999")  # Almost certainly not a real PID
        with patch("beacon.telemetry.daemon._PID_FILE", pid_file):
            assert read_pid() is None

    def test_build_scheduler(self):
        settings = BeaconSettings()
        scheduler = _build_scheduler(settings)

        assert scheduler is not None
        assert len(scheduler._samplers) == 8  # wifi, dhcp, ping, dns, http, device, context, change

    def test_build_scheduler_with_influx(self):
        settings = BeaconSettings()
        settings.telemetry.export_influx_enabled = True
        scheduler = _build_scheduler(settings)

        assert len(scheduler._exporters) == 1

    def test_build_scheduler_with_file_export(self):
        settings = BeaconSettings()
        settings.telemetry.export_influx_enabled = False
        settings.telemetry.export_file_enabled = True
        scheduler = _build_scheduler(settings)

        assert len(scheduler._exporters) == 1

    def test_build_scheduler_no_exporters(self):
        settings = BeaconSettings()
        settings.telemetry.export_influx_enabled = False
        settings.telemetry.export_file_enabled = False
        scheduler = _build_scheduler(settings)

        assert len(scheduler._exporters) == 0

    def test_build_scheduler_sampler_names(self):
        settings = BeaconSettings()
        scheduler = _build_scheduler(settings)
        names = {s.name for s in scheduler._samplers}
        assert names == {"wifi", "dhcp", "ping", "dns", "http", "device", "context", "change"}
