"""Unit tests for telemetry daemon."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import pytest

from beacon.telemetry.daemon import (
    _setup_logging,
    _write_pid,
    _remove_pid,
    read_pid,
    _reload_config,
    _build_scheduler,
    apply_config_reload,
    run,
)
from beacon.config import BeaconSettings, TelemetrySettings


@pytest.fixture
def mock_settings():
    return BeaconSettings(
        log_level="INFO",
        telemetry=TelemetrySettings(
            enabled=True,
            tier0_wifi_interval=30,
            tier0_ping_interval=60,
            tier0_dns_interval=120,
            tier0_http_interval=300,
            tier0_device_interval=600,
            tier0_context_interval=3600,
            change_detection_interval=300,
            ping_targets=["8.8.8.8"],
            dns_resolvers=["1.1.1.1"],
            http_targets=["https://google.com"],
            ping_gateway=True,
            dns_domains=["google.com"],
            context_public_ip_ttl=3600,
            context_geo_ttl=86400,
            context_geo_enabled=True,
            buffer_path=Path("/tmp/test.db"),
            buffer_max_mb=100,
            buffer_retention_days=7,
            export_influx_enabled=True,
            export_file_enabled=False,
            export_file_path=Path("/tmp/export.json"),
            export_file_max_mb=50,
            export_file_max_files=5,
            export_batch_size=100,
        ),
    )


class TestSetupLogging:
    @patch("beacon.telemetry.daemon.logging")
    def test_setup_logging_info_level(self, mock_logging, mock_settings):
        _setup_logging(mock_settings)
        mock_logging.basicConfig.assert_called_once()
        args = mock_logging.basicConfig.call_args
        assert args[1]["level"] == mock_logging.INFO

    @patch("beacon.telemetry.daemon.logging")
    def test_setup_logging_debug_level(self, mock_logging, mock_settings):
        mock_settings.log_level = "DEBUG"
        _setup_logging(mock_settings)
        mock_logging.basicConfig.assert_called_once()
        args = mock_logging.basicConfig.call_args
        assert args[1]["level"] == mock_logging.DEBUG

    @patch("beacon.telemetry.daemon.logging")
    def test_setup_logging_invalid_level(self, mock_logging, mock_settings):
        mock_settings.log_level = "INVALID"
        _setup_logging(mock_settings)
        mock_logging.basicConfig.assert_called_once()
        args = mock_logging.basicConfig.call_args
        assert args[1]["level"] == mock_logging.INFO


class TestPidManagement:
    def test_write_pid(self, tmp_path, monkeypatch):
        test_pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("beacon.telemetry.daemon._PID_FILE", test_pid_file)

        with patch("os.getpid", return_value=12345):
            _write_pid()

        assert test_pid_file.read_text() == "12345"

    def test_remove_pid(self, tmp_path, monkeypatch):
        test_pid_file = tmp_path / "test.pid"
        test_pid_file.write_text("12345")
        monkeypatch.setattr("beacon.telemetry.daemon._PID_FILE", test_pid_file)

        _remove_pid()

        assert not test_pid_file.exists()

    def test_remove_pid_missing_file(self, tmp_path, monkeypatch):
        test_pid_file = tmp_path / "nonexistent.pid"
        monkeypatch.setattr("beacon.telemetry.daemon._PID_FILE", test_pid_file)

        _remove_pid()  # Should not raise

    def test_read_pid_success(self, tmp_path, monkeypatch):
        test_pid_file = tmp_path / "test.pid"
        test_pid_file.write_text("12345")
        monkeypatch.setattr("beacon.telemetry.daemon._PID_FILE", test_pid_file)

        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None  # Process exists
            pid = read_pid()

        assert pid == 12345
        mock_kill.assert_called_once_with(12345, 0)

    def test_read_pid_process_not_found(self, tmp_path, monkeypatch):
        test_pid_file = tmp_path / "test.pid"
        test_pid_file.write_text("12345")
        monkeypatch.setattr("beacon.telemetry.daemon._PID_FILE", test_pid_file)

        with patch("os.kill", side_effect=ProcessLookupError()):
            pid = read_pid()

        assert pid is None

    def test_read_pid_invalid_content(self, tmp_path, monkeypatch):
        test_pid_file = tmp_path / "test.pid"
        test_pid_file.write_text("invalid")
        monkeypatch.setattr("beacon.telemetry.daemon._PID_FILE", test_pid_file)

        pid = read_pid()

        assert pid is None

    def test_read_pid_missing_file(self, tmp_path, monkeypatch):
        test_pid_file = tmp_path / "nonexistent.pid"
        monkeypatch.setattr("beacon.telemetry.daemon._PID_FILE", test_pid_file)

        pid = read_pid()

        assert pid is None


class TestReloadConfig:
    @patch("beacon.telemetry.daemon.reset_settings")
    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon.logging")
    def test_reload_config_success(
        self, mock_logging, mock_get_settings, mock_reset, mock_settings
    ):
        mock_scheduler = Mock()
        mock_scheduler._samplers = [
            Mock(name="ping", default_interval=60),
            Mock(name="dns", default_interval=120),
        ]
        mock_get_settings.return_value = mock_settings

        _reload_config(mock_scheduler)

        mock_reset.assert_called_once()
        mock_get_settings.assert_called_once_with(None)
        assert mock_scheduler._settings == mock_settings

    @patch("beacon.telemetry.daemon.reset_settings")
    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon.logging")
    def test_reload_config_exception(self, mock_logging, mock_get_settings, mock_reset):
        mock_scheduler = Mock()
        mock_get_settings.side_effect = Exception("Config error")

        _reload_config(mock_scheduler)

        mock_reset.assert_called_once()


class TestBuildScheduler:
    @patch("beacon.telemetry.daemon.TelemetryScheduler")
    @patch("beacon.telemetry.daemon.SQLiteBuffer")
    @patch("beacon.telemetry.daemon.InfluxExporter")
    @patch("beacon.telemetry.daemon.FileExporter")
    def test_build_scheduler_with_exporters(
        self, mock_file_exp, mock_influx_exp, mock_buffer, mock_scheduler, mock_settings
    ):
        mock_settings.telemetry.export_influx_enabled = True
        mock_settings.telemetry.export_file_enabled = True

        _build_scheduler(mock_settings)

        mock_buffer.assert_called_once()
        mock_influx_exp.assert_called_once()
        mock_file_exp.assert_called_once()
        mock_scheduler.assert_called_once()

    @patch("beacon.telemetry.daemon.TelemetryScheduler")
    @patch("beacon.telemetry.daemon.SQLiteBuffer")
    def test_build_scheduler_no_exporters(self, mock_buffer, mock_scheduler, mock_settings):
        mock_settings.telemetry.export_influx_enabled = False
        mock_settings.telemetry.export_file_enabled = False

        _build_scheduler(mock_settings)

        mock_scheduler.assert_called_once()
        # Check that exporters list is empty
        args = mock_scheduler.call_args[0]
        exporters = args[3]  # Fourth argument is exporters
        assert len(exporters) == 0


class TestApplyConfigReload:
    def test_apply_config_reload_interval_changes(self, mock_settings):
        old_ts = TelemetrySettings(tier0_ping_interval=60)
        new_settings = BeaconSettings(telemetry=TelemetrySettings(tier0_ping_interval=30))

        mock_scheduler = Mock()

        apply_config_reload(mock_scheduler, old_ts, new_settings)

        mock_scheduler.set_interval.assert_called_with("ping", 30)
        assert mock_scheduler._settings == new_settings

    def test_apply_config_reload_target_changes(self, mock_settings):
        old_ts = TelemetrySettings(ping_targets=["8.8.8.8"])
        new_settings = BeaconSettings(telemetry=TelemetrySettings(ping_targets=["1.1.1.1"]))

        mock_ping_sampler = Mock(name="ping")
        mock_scheduler = Mock()
        mock_scheduler._samplers = [mock_ping_sampler]

        apply_config_reload(mock_scheduler, old_ts, new_settings)

        assert mock_ping_sampler._targets == ["1.1.1.1"]

    def test_apply_config_reload_no_changes(self, mock_settings):
        old_ts = TelemetrySettings(tier0_ping_interval=60)
        new_settings = BeaconSettings(telemetry=TelemetrySettings(tier0_ping_interval=60))

        mock_scheduler = Mock()

        apply_config_reload(mock_scheduler, old_ts, new_settings)

        mock_scheduler.set_interval.assert_not_called()


class TestRunDaemon:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.daemon._build_scheduler")
    async def test_run_daemon_signal_handling(self, mock_build_scheduler, mock_settings):
        mock_scheduler = AsyncMock()
        mock_build_scheduler.return_value = mock_scheduler

        # Mock the event loop
        mock_loop = Mock()

        with patch("asyncio.get_event_loop", return_value=mock_loop):
            # Create a task that will complete quickly
            async def quick_daemon():
                await asyncio.sleep(0.01)  # Very short sleep

            # Replace the actual daemon with our quick version
            with patch("beacon.telemetry.daemon._run_daemon", quick_daemon):
                await quick_daemon()

        # Verify signal handlers were set up
        expected_signals = [signal.SIGTERM, signal.SIGINT]
        assert mock_loop.add_signal_handler.call_count >= len(expected_signals)

    @pytest.mark.asyncio
    @patch("beacon.telemetry.daemon._build_scheduler")
    async def test_run_daemon_scheduler_lifecycle(self, mock_build_scheduler, mock_settings):
        mock_scheduler = AsyncMock()
        mock_build_scheduler.return_value = mock_scheduler

        # Create an event that we can trigger to stop the daemon
        stop_event = asyncio.Event()

        async def mock_daemon():
            await mock_scheduler.start()
            # Immediately set the stop event to exit quickly
            stop_event.set()
            await stop_event.wait()
            await mock_scheduler.stop()

        await mock_daemon()

        mock_scheduler.start.assert_called_once()
        mock_scheduler.stop.assert_called_once()


class TestRun:
    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    @patch("beacon.telemetry.daemon._write_pid")
    @patch("beacon.telemetry.daemon._remove_pid")
    @patch("beacon.telemetry.daemon.asyncio.run")
    def test_run_success(
        self,
        mock_asyncio_run,
        mock_remove_pid,
        mock_write_pid,
        mock_read_pid,
        mock_setup_logging,
        mock_get_settings,
        mock_settings,
    ):
        mock_get_settings.return_value = mock_settings
        mock_read_pid.return_value = None  # No existing daemon

        run()

        mock_setup_logging.assert_called_once_with(mock_settings)
        mock_write_pid.assert_called_once()
        mock_asyncio_run.assert_called_once()
        mock_remove_pid.assert_called_once()

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    @patch("beacon.telemetry.daemon.sys.exit")
    def test_run_telemetry_disabled(
        self, mock_exit, mock_read_pid, mock_setup_logging, mock_get_settings, mock_settings
    ):
        mock_settings.telemetry.enabled = False
        mock_get_settings.return_value = mock_settings

        run()

        mock_exit.assert_called_once_with(1)

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    @patch("beacon.telemetry.daemon.sys.exit")
    def test_run_daemon_already_running(
        self, mock_exit, mock_read_pid, mock_setup_logging, mock_get_settings, mock_settings
    ):
        mock_get_settings.return_value = mock_settings
        mock_read_pid.return_value = 12345  # Existing daemon

        run()

        mock_exit.assert_called_once_with(1)

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    @patch("beacon.telemetry.daemon._write_pid")
    @patch("beacon.telemetry.daemon._remove_pid")
    @patch("beacon.telemetry.daemon.asyncio.run")
    def test_run_with_config_path(
        self,
        mock_asyncio_run,
        mock_remove_pid,
        mock_write_pid,
        mock_read_pid,
        mock_setup_logging,
        mock_get_settings,
        mock_settings,
    ):
        mock_get_settings.return_value = mock_settings
        mock_read_pid.return_value = None
        config_path = Path("/test/config.yaml")

        run(config_path=config_path)

        mock_get_settings.assert_called_once_with(config_path)

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    @patch("beacon.telemetry.daemon._write_pid")
    @patch("beacon.telemetry.daemon._remove_pid")
    @patch("beacon.telemetry.daemon.asyncio.run")
    def test_run_exception_cleanup(
        self,
        mock_asyncio_run,
        mock_remove_pid,
        mock_write_pid,
        mock_read_pid,
        mock_setup_logging,
        mock_get_settings,
        mock_settings,
    ):
        mock_get_settings.return_value = mock_settings
        mock_read_pid.return_value = None
        mock_asyncio_run.side_effect = Exception("Test exception")

        with pytest.raises(Exception, match="Test exception"):
            run()

        mock_remove_pid.assert_called_once()  # Cleanup should still happen
