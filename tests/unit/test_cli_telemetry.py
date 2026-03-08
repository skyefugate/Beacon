"""Tests for beacon telemetry CLI commands."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from beacon.cli.app import app
from beacon.config import reset_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_beacon_settings():
    """Reset settings singleton after each test."""
    yield
    reset_settings()


@pytest.fixture
def mock_settings():
    """Mock settings with telemetry configuration."""
    settings = MagicMock()
    settings.telemetry = MagicMock(
        enabled=True,
        window_seconds=60,
        buffer_path="/tmp/telemetry.db",
        export_influx_enabled=True,
        export_file_enabled=False,
    )
    return settings


class TestTelemetryStart:
    def test_start_foreground_success(self, mock_settings):
        """Test starting telemetry in foreground mode."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("beacon.telemetry.daemon.run") as mock_run,
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "start"])

            assert result.exit_code == 0
            assert "Starting telemetry (foreground)" in result.output
            assert "Press Ctrl+C to stop" in result.output
            mock_run.assert_called_once_with(config_path=None)

    def test_start_daemon_already_running(self):
        """Test starting telemetry when daemon is already running."""
        with patch("beacon.telemetry.daemon.read_pid", return_value=12345):
            result = runner.invoke(app, ["telemetry", "start"])

            assert result.exit_code == 1
            assert "already running" in result.output
            assert "PID 12345" in result.output

    def test_start_daemon_mode(self, mock_settings):
        """Test starting telemetry in daemon mode."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("os.fork", return_value=12345),
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "start", "--daemon"])

            assert result.exit_code == 0
            assert "Starting telemetry daemon in background" in result.output
            assert "Daemon started (PID 12345)" in result.output

    def test_start_daemon_mode_child_process(self, mock_settings):
        """Test daemon mode child process execution."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("os.fork", return_value=0),
            patch("os.setsid") as mock_setsid,
            patch("sys.stdin.close"),
            patch("beacon.telemetry.daemon.run") as mock_run,
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            # This will actually run the child process path
            runner.invoke(app, ["telemetry", "start", "--daemon"])

            # Child process should call setsid and run daemon
            mock_setsid.assert_called_once()
            mock_run.assert_called_once_with(config_path=None, daemon=True)

    def test_start_with_config_file(self, mock_settings):
        """Test starting telemetry with custom config file."""
        config_path = Path("/custom/beacon.yaml")

        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("beacon.telemetry.daemon.run") as mock_run,
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "start", "--config", str(config_path)])

            assert result.exit_code == 0
            mock_run.assert_called_once_with(config_path=config_path)

    def test_start_short_options(self, mock_settings):
        """Test starting telemetry with short options."""
        config_path = Path("/custom/beacon.yaml")

        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("os.fork", return_value=12345),
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "start", "-d", "-c", str(config_path)])

            assert result.exit_code == 0
            assert "daemon" in result.output


class TestTelemetryStop:
    def test_stop_success(self):
        """Test stopping telemetry daemon successfully."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=12345),
            patch("os.kill") as mock_kill,
        ):
            result = runner.invoke(app, ["telemetry", "stop"])

            assert result.exit_code == 0
            assert "Sent SIGTERM to daemon (PID 12345)" in result.output
            mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_stop_not_running(self):
        """Test stopping telemetry when daemon is not running."""
        with patch("beacon.telemetry.daemon.read_pid", return_value=None):
            result = runner.invoke(app, ["telemetry", "stop"])

            assert result.exit_code == 1
            assert "not running" in result.output

    def test_stop_process_not_found(self):
        """Test stopping telemetry when process doesn't exist."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=12345),
            patch("os.kill", side_effect=ProcessLookupError("No such process")),
        ):
            result = runner.invoke(app, ["telemetry", "stop"])

            assert result.exit_code == 0
            assert "Daemon process not found" in result.output

    def test_stop_permission_denied(self):
        """Test stopping telemetry with permission error."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=12345),
            patch("os.kill", side_effect=PermissionError("Permission denied")),
        ):
            result = runner.invoke(app, ["telemetry", "stop"])

            assert result.exit_code == 1
            assert "Permission denied sending signal" in result.output


class TestTelemetryStatus:
    def test_status_running(self, mock_settings):
        """Test status command when daemon is running."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=12345),
            patch("beacon.cli.commands.telemetry.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "status"])

            assert result.exit_code == 0
            assert "running (PID 12345)" in result.output
            assert "Configuration:" in result.output
            assert "Enabled:        True" in result.output
            assert "Window:         60s" in result.output
            assert "Buffer:         /tmp/telemetry.db" in result.output
            assert "InfluxDB:       enabled" in result.output
            assert "File export:    disabled" in result.output

    def test_status_not_running(self, mock_settings):
        """Test status command when daemon is not running."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "status"])

            assert result.exit_code == 0
            assert "not running" in result.output
            assert "Configuration:" in result.output

    def test_status_disabled_telemetry(self):
        """Test status command with disabled telemetry."""
        settings = MagicMock()
        settings.telemetry = MagicMock(
            enabled=False,
            window_seconds=30,
            buffer_path="/tmp/telemetry.db",
            export_influx_enabled=False,
            export_file_enabled=True,
        )

        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("beacon.cli.commands.telemetry.get_settings", return_value=settings),
        ):
            result = runner.invoke(app, ["telemetry", "status"])

            assert result.exit_code == 0
            assert "Enabled:        False" in result.output
            assert "Window:         30s" in result.output
            assert "InfluxDB:       disabled" in result.output
            assert "File export:    enabled" in result.output

    @patch("beacon.cli.commands.telemetry.get_settings")
    def test_status_uses_settings(self, mock_get_settings):
        """Test that status command uses get_settings."""
        mock_get_settings.return_value.telemetry = MagicMock(
            enabled=True,
            window_seconds=120,
            buffer_path="/custom/path.db",
            export_influx_enabled=True,
            export_file_enabled=True,
        )

        with patch("beacon.telemetry.daemon.read_pid", return_value=None):
            result = runner.invoke(app, ["telemetry", "status"])

            assert result.exit_code == 0
            mock_get_settings.assert_called_once()


class TestTelemetryCommandErrors:
    def test_invalid_telemetry_subcommand(self):
        """Test invalid telemetry subcommand."""
        result = runner.invoke(app, ["telemetry", "invalid"])

        assert result.exit_code != 0

    def test_telemetry_no_args_shows_help(self):
        """Test telemetry command without arguments shows help."""
        result = runner.invoke(app, ["telemetry"])

        assert result.exit_code != 0
        # Should show help due to no_args_is_help=True

    def test_start_daemon_read_pid_exception(self):
        """Test handling of read_pid exceptions in start command."""
        with patch("beacon.telemetry.daemon.read_pid", side_effect=Exception("PID read error")):
            result = runner.invoke(app, ["telemetry", "start"])

            assert result.exit_code != 0

    def test_stop_daemon_read_pid_exception(self):
        """Test handling of read_pid exceptions in stop command."""
        with patch("beacon.telemetry.daemon.read_pid", side_effect=Exception("PID read error")):
            result = runner.invoke(app, ["telemetry", "stop"])

            assert result.exit_code != 0

    def test_status_daemon_read_pid_exception(self):
        """Test handling of read_pid exceptions in status command."""
        with patch("beacon.telemetry.daemon.read_pid", side_effect=Exception("PID read error")):
            result = runner.invoke(app, ["telemetry", "status"])

            assert result.exit_code != 0

    def test_start_daemon_run_exception(self, mock_settings):
        """Test handling of daemon run exceptions."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("beacon.telemetry.daemon.run", side_effect=Exception("Daemon start failed")),
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "start"])

            assert result.exit_code != 0

    def test_start_fork_exception(self, mock_settings):
        """Test handling of fork exceptions in daemon mode."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch("os.fork", side_effect=OSError("Fork failed")),
            patch("beacon.config.get_settings", return_value=mock_settings),
        ):
            result = runner.invoke(app, ["telemetry", "start", "--daemon"])

            assert result.exit_code != 0

    def test_stop_kill_other_exception(self):
        """Test handling of other os.kill exceptions."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=12345),
            patch("os.kill", side_effect=OSError("Other error")),
        ):
            result = runner.invoke(app, ["telemetry", "stop"])

            assert result.exit_code != 0

    def test_status_get_settings_exception(self):
        """Test handling of get_settings exceptions in status command."""
        with (
            patch("beacon.telemetry.daemon.read_pid", return_value=None),
            patch(
                "beacon.cli.commands.telemetry.get_settings",
                side_effect=Exception("Settings error"),
            ),
        ):
            result = runner.invoke(app, ["telemetry", "status"])

            assert result.exit_code != 0
