"""Tests for the beacon doctor self-check command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest
from typer.testing import CliRunner

from beacon.cli.app import app
from beacon.cli.commands.doctor import (
    CHECKS,
    _check_airport_binary,
    _check_collector_reachable,
    _check_config_readable,
    _check_daemon_running,
    _check_data_dir_writable,
    _check_influxdb_reachable,
)
from beacon.config import reset_settings


runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_beacon_settings():
    """Reset settings singleton after each test."""
    yield
    reset_settings()


class TestCheckConfigReadable:
    def test_no_config_file(self, tmp_path):
        with patch.object(Path, "is_file", return_value=False):
            ok, detail = _check_config_readable()
        assert ok is True
        assert "defaults" in detail

    def test_valid_yaml_config(self, tmp_path):
        with patch("beacon.cli.commands.doctor._load_yaml_config") as mock_load:
            mock_load.return_value = {"beacon": {"port": 8000}}
            with patch.object(Path, "is_file", return_value=True):
                ok, detail = _check_config_readable()
        assert ok is True

    def test_invalid_yaml_config(self, tmp_path):
        with patch("beacon.cli.commands.doctor._load_yaml_config") as mock_load:
            mock_load.side_effect = Exception("YAML parse error")
            with patch.object(Path, "is_file", return_value=True):
                ok, detail = _check_config_readable()
        assert ok is False
        assert "YAML parse error" in detail


class TestCheckInfluxDBReachable:
    def test_reachable_200(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        with patch("beacon.cli.commands.doctor.urlopen", return_value=mock_resp):
            ok, detail = _check_influxdb_reachable()
        assert ok is True
        assert "reachable" in detail

    def test_reachable_204_as_http_error(self):
        http_err = HTTPError(
            url="http://localhost:8086/ping",
            code=204,
            msg="No Content",
            hdrs=None,
            fp=None,
        )
        with patch("beacon.cli.commands.doctor.urlopen", side_effect=http_err):
            ok, detail = _check_influxdb_reachable()
        assert ok is True
        assert "204" in detail

    def test_unreachable_url_error(self):
        url_err = URLError("Connection refused")
        with patch("beacon.cli.commands.doctor.urlopen", side_effect=url_err):
            ok, detail = _check_influxdb_reachable()
        assert ok is False
        assert "unreachable" in detail

    def test_unreachable_os_error(self):
        with patch("beacon.cli.commands.doctor.urlopen", side_effect=OSError("Network")):
            ok, detail = _check_influxdb_reachable()
        assert ok is False


class TestCheckCollectorReachable:
    def test_reachable_200(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        with patch("beacon.cli.commands.doctor.urlopen", return_value=mock_resp):
            ok, detail = _check_collector_reachable()
        assert ok is True
        assert "reachable" in detail

    def test_unreachable(self):
        url_err = URLError("Connection refused")
        with patch("beacon.cli.commands.doctor.urlopen", side_effect=url_err):
            ok, detail = _check_collector_reachable()
        assert ok is False
        assert "unreachable" in detail


class TestCheckDaemonRunning:
    def test_daemon_not_running(self):
        with patch("beacon.telemetry.daemon.read_pid", return_value=None):
            ok, detail = _check_daemon_running()
        assert ok is False
        assert "not running" in detail

    def test_daemon_pid_alive(self):
        with patch("beacon.telemetry.daemon.read_pid", return_value=99999):
            ok, detail = _check_daemon_running()
        assert ok is True
        assert "99999" in detail


class TestCheckAirportBinary:
    def test_airport_found_at_default_path(self):
        with patch.object(Path, "is_file", return_value=True):
            ok, detail = _check_airport_binary()
        assert ok is True
        assert "airport" in detail

    def test_airport_found_via_which(self):
        with patch.object(Path, "is_file", return_value=False):
            with patch("beacon.cli.commands.doctor.shutil.which", return_value="/usr/bin/airport"):
                ok, detail = _check_airport_binary()
        assert ok is True
        assert "/usr/bin/airport" in detail

    def test_airport_not_found(self):
        with patch.object(Path, "is_file", return_value=False):
            with patch("beacon.cli.commands.doctor.shutil.which", return_value=None):
                ok, detail = _check_airport_binary()
        assert ok is False
        assert "not found" in detail


class TestCheckDataDirWritable:
    def test_writable(self, tmp_path):
        with patch("beacon.cli.commands.doctor.get_settings") as mock_settings:
            mock_settings.return_value.storage.data_dir = tmp_path
            ok, detail = _check_data_dir_writable()
        assert ok is True
        assert "writable" in detail

    def test_not_writable(self, tmp_path):
        with patch("beacon.cli.commands.doctor.get_settings") as mock_settings:
            mock_settings.return_value.storage.data_dir = tmp_path
            with patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
                ok, detail = _check_data_dir_writable()
        assert ok is False
        assert "not writable" in detail


class TestDoctorCLI:
    def test_all_checks_pass_exit_0(self):
        passing = [(True, "ok")] * len(CHECKS)
        check_fns = [lambda ok=ok, d=d: (ok, d) for ok, d in passing]
        patched = list(zip([label for label, _ in CHECKS], check_fns))
        with patch("beacon.cli.commands.doctor.CHECKS", patched):
            result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0

    def test_one_check_fails_exit_1(self):
        mixed = [(True, "ok")] * (len(CHECKS) - 1) + [(False, "broken")]
        check_fns = [lambda ok=ok, d=d: (ok, d) for ok, d in mixed]
        patched = list(zip([label for label, _ in CHECKS], check_fns))
        with patch("beacon.cli.commands.doctor.CHECKS", patched):
            result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1

    def test_output_contains_doctor_title(self):
        passing = [(True, "ok")] * len(CHECKS)
        check_fns = [lambda ok=ok, d=d: (ok, d) for ok, d in passing]
        patched = list(zip([label for label, _ in CHECKS], check_fns))
        with patch("beacon.cli.commands.doctor.CHECKS", patched):
            result = runner.invoke(app, ["doctor"])
        assert "Beacon Doctor" in result.output
        assert result.exit_code == 0
