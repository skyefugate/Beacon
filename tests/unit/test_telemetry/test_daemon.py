"""Tests for daemon — PID file, build_scheduler, signal handling."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from beacon.config import BeaconSettings
from beacon.telemetry.daemon import (
    _build_scheduler, 
    read_pid, 
    _write_pid, 
    _remove_pid, 
    _run_daemon,
    run,
    apply_config_reload
)


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
        assert (
            len(scheduler._samplers) == 9
        )  # wifi, tcp, nic, ping, dns, http, device, context, change

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
        assert names == {"wifi", "tcp", "nic", "ping", "dns", "http", "device", "context", "change"}

    @patch("beacon.telemetry.daemon._PID_FILE")
    def test_write_pid(self, mock_pid_file):
        mock_pid_file.write_text = MagicMock()
        with patch("os.getpid", return_value=12345):
            _write_pid()
        mock_pid_file.write_text.assert_called_once_with("12345")

    @patch("beacon.telemetry.daemon._PID_FILE")
    def test_remove_pid_success(self, mock_pid_file):
        mock_pid_file.unlink = MagicMock()
        _remove_pid()
        mock_pid_file.unlink.assert_called_once_with(missing_ok=True)

    @patch("beacon.telemetry.daemon._PID_FILE")
    def test_remove_pid_os_error(self, mock_pid_file):
        mock_pid_file.unlink.side_effect = OSError("Permission denied")
        _remove_pid()  # Should not raise

    @patch("beacon.telemetry.daemon._build_scheduler")
    @patch("asyncio.get_event_loop")
    async def test_sighup_signal_handling(self, mock_get_loop, mock_build_scheduler):
        mock_scheduler = AsyncMock()
        mock_build_scheduler.return_value = mock_scheduler
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        
        settings = BeaconSettings()
        
        with patch("beacon.telemetry.daemon.get_settings", return_value=settings):
            with patch("beacon.telemetry.daemon.reset_settings"):
                with patch("beacon.telemetry.daemon.apply_config_reload") as mock_apply:
                    # Start daemon task
                    task = asyncio.create_task(_run_daemon(settings))
                    await asyncio.sleep(0.01)  # Let it set up signal handlers
                    
                    # Verify SIGHUP handler was registered
                    sighup_calls = [call for call in mock_loop.add_signal_handler.call_args_list 
                                   if call[0][0] == signal.SIGHUP]
                    assert len(sighup_calls) == 1
                    
                    # Simulate SIGHUP
                    sighup_handler = sighup_calls[0][0][1]
                    sighup_handler()
                    
                    # Stop daemon
                    sigterm_calls = [call for call in mock_loop.add_signal_handler.call_args_list 
                                    if call[0][0] == signal.SIGTERM]
                    sigterm_handler = sigterm_calls[0][0][1]
                    sigterm_handler(signal.SIGTERM)
                    
                    await task

    @patch("beacon.telemetry.daemon._build_scheduler")
    @patch("asyncio.get_event_loop")
    async def test_sigterm_graceful_shutdown(self, mock_get_loop, mock_build_scheduler):
        mock_scheduler = AsyncMock()
        mock_build_scheduler.return_value = mock_scheduler
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        
        settings = BeaconSettings()
        
        # Start daemon task
        task = asyncio.create_task(_run_daemon(settings))
        await asyncio.sleep(0.01)  # Let it set up signal handlers
        
        # Verify SIGTERM handler was registered
        sigterm_calls = [call for call in mock_loop.add_signal_handler.call_args_list 
                        if call[0][0] == signal.SIGTERM]
        assert len(sigterm_calls) == 1
        
        # Simulate SIGTERM
        sigterm_handler = sigterm_calls[0][0][1]
        sigterm_handler(signal.SIGTERM)
        
        await task
        mock_scheduler.stop.assert_called_once()

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    @patch("beacon.telemetry.daemon._write_pid")
    @patch("beacon.telemetry.daemon._remove_pid")
    @patch("asyncio.run")
    def test_daemon_startup_sequence(self, mock_run, mock_remove_pid, mock_write_pid, 
                                   mock_read_pid, mock_setup_logging, mock_get_settings):
        settings = BeaconSettings()
        settings.telemetry.enabled = True
        mock_get_settings.return_value = settings
        mock_read_pid.return_value = None  # No existing daemon
        
        run()
        
        mock_setup_logging.assert_called_once_with(settings)
        mock_read_pid.assert_called_once()
        mock_write_pid.assert_called_once()
        mock_run.assert_called_once()

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    def test_daemon_startup_already_running(self, mock_read_pid, mock_setup_logging, mock_get_settings):
        settings = BeaconSettings()
        settings.telemetry.enabled = True
        mock_get_settings.return_value = settings
        mock_read_pid.return_value = 12345  # Existing daemon
        
        with pytest.raises(SystemExit) as exc_info:
            run()
        
        assert exc_info.value.code == 1

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    def test_daemon_startup_telemetry_disabled(self, mock_setup_logging, mock_get_settings):
        settings = BeaconSettings()
        settings.telemetry.enabled = False
        mock_get_settings.return_value = settings
        
        with pytest.raises(SystemExit) as exc_info:
            run()
        
        assert exc_info.value.code == 1

    @patch("beacon.telemetry.daemon.get_settings")
    @patch("beacon.telemetry.daemon._setup_logging")
    @patch("beacon.telemetry.daemon.read_pid")
    @patch("beacon.telemetry.daemon._write_pid")
    @patch("beacon.telemetry.daemon._remove_pid")
    @patch("asyncio.run")
    def test_daemon_startup_error_cleanup(self, mock_run, mock_remove_pid, mock_write_pid,
                                        mock_read_pid, mock_setup_logging, mock_get_settings):
        settings = BeaconSettings()
        settings.telemetry.enabled = True
        mock_get_settings.return_value = settings
        mock_read_pid.return_value = None
        mock_run.side_effect = Exception("Startup failed")
        
        with pytest.raises(Exception):
            run()
        
        mock_remove_pid.assert_called_once()  # PID file cleaned up

    def test_apply_config_reload_sampler_intervals(self):
        # Create mock scheduler with samplers
        mock_scheduler = MagicMock()
        mock_sampler = MagicMock()
        mock_sampler.name = "ping"
        mock_scheduler._samplers = [mock_sampler]
        
        # Create old and new settings with different intervals
        old_settings = BeaconSettings()
        old_settings.telemetry.tier0_ping_interval = 30
        
        new_settings = BeaconSettings()
        new_settings.telemetry.tier0_ping_interval = 60
        
        apply_config_reload(mock_scheduler, old_settings.telemetry, new_settings)
        
        mock_scheduler.set_interval.assert_called_once_with("ping", 60)

    def test_apply_config_reload_ping_targets(self):
        # Create mock scheduler with ping sampler
        mock_scheduler = MagicMock()
        mock_ping_sampler = MagicMock()
        mock_ping_sampler.name = "ping"
        mock_scheduler._samplers = [mock_ping_sampler]
        
        old_settings = BeaconSettings()
        old_settings.telemetry.ping_targets = ["8.8.8.8"]
        
        new_settings = BeaconSettings()
        new_settings.telemetry.ping_targets = ["1.1.1.1", "8.8.8.8"]
        
        apply_config_reload(mock_scheduler, old_settings.telemetry, new_settings)
        
        assert mock_ping_sampler._targets == ["1.1.1.1", "8.8.8.8"]
