"""Tests for throughput runner - focusing on error paths and edge cases."""

import json
import subprocess
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from beacon.runners.base import RunnerConfig
from beacon.runners.throughput import ThroughputRunner


class TestThroughputRunner:
    def test_no_server_configured(self):
        runner = ThroughputRunner()
        config = RunnerConfig()
        envelope = runner.run(uuid4(), config)
        
        assert "skipping" in envelope.notes[0].lower()
        assert len(envelope.metrics) == 0
        assert len(envelope.events) == 0

    def test_server_from_targets(self):
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            
            runner = ThroughputRunner()
            config = RunnerConfig(targets=["192.168.1.100"])
            envelope = runner.run(uuid4(), config)
            
            assert "not installed" in envelope.notes[0]

    def test_iperf3_not_installed(self):
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            assert "not installed" in envelope.notes[0]

    def test_iperf3_timeout(self):
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("iperf3", 30)
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            assert any("timed out" in note for note in envelope.notes)

    def test_iperf3_command_failure(self):
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="iperf3: error - unable to connect to server"
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            assert any("failed" in note for note in envelope.notes)

    def test_json_decode_error(self):
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="invalid json output"
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            assert any("parse" in note for note in envelope.notes)

    def test_successful_download_test(self):
        iperf_output = {
            "end": {
                "sum_received": {
                    "bits_per_second": 100000000,
                    "bytes": 12500000,
                    "seconds": 10.0
                }
            }
        }
        
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(iperf_output)
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            assert len(envelope.metrics) == 2  # download + upload
            download_metric = envelope.metrics[0]
            assert download_metric.fields["mbps"] == 100.0
            assert download_metric.fields["direction"] == "download"

    def test_low_throughput_event(self):
        iperf_output = {
            "end": {
                "sum_received": {
                    "bits_per_second": 5000000,  # 5 Mbps - low
                    "bytes": 625000,
                    "seconds": 10.0
                }
            }
        }
        
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(iperf_output)
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            low_throughput_events = [e for e in envelope.events if e.event_type == "low_throughput"]
            assert len(low_throughput_events) == 2  # download + upload

    def test_udp_mode_with_jitter_and_loss(self):
        iperf_output = {
            "end": {
                "sum_received": {
                    "bits_per_second": 50000000,
                    "bytes": 6250000,
                    "seconds": 10.0,
                    "jitter_ms": 2.5,
                    "lost_packets": 5
                }
            }
        }
        
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(iperf_output)
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            metric = envelope.metrics[0]
            assert "jitter_ms" in metric.fields
            assert "lost_packets" in metric.fields
            assert metric.fields["jitter_ms"] == 2.5
            assert metric.fields["lost_packets"] == 5

    def test_custom_duration_and_port(self):
        iperf_output = {
            "end": {
                "sum_received": {
                    "bits_per_second": 100000000,
                    "bytes": 6250000,
                    "seconds": 5.0
                }
            }
        }
        
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(iperf_output)
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={
                "server": "192.168.1.100",
                "duration": 5,
                "port": 5202
            })
            envelope = runner.run(uuid4(), config)
            
            # Verify command was called with correct parameters
            calls = mock_run.call_args_list
            assert len(calls) == 2  # download + upload
            
            # Check download call (with -R flag)
            download_cmd = calls[0][0][0]
            assert "-t" in download_cmd and "5" in download_cmd
            assert "-p" in download_cmd and "5202" in download_cmd
            assert "-R" in download_cmd
            
            # Check upload call (without -R flag)
            upload_cmd = calls[1][0][0]
            assert "-R" not in upload_cmd

    def test_generic_exception_handling(self):
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Unexpected error")
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            assert any("failed" in note for note in envelope.notes)

    def test_sum_sent_fallback(self):
        """Test fallback to sum_sent when sum_received is not available."""
        iperf_output = {
            "end": {
                "sum_sent": {
                    "bits_per_second": 80000000,
                    "bytes": 10000000,
                    "seconds": 10.0
                }
            }
        }
        
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(iperf_output)
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            assert len(envelope.metrics) == 2
            assert envelope.metrics[0].fields["mbps"] == 80.0

    def test_missing_end_section(self):
        """Test handling of malformed JSON without end section."""
        iperf_output = {"start": {"version": "3.9"}}
        
        with patch("beacon.runners.throughput.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(iperf_output)
            )
            
            runner = ThroughputRunner()
            config = RunnerConfig(extra={"server": "192.168.1.100"})
            envelope = runner.run(uuid4(), config)
            
            # Should create metrics with default values
            assert len(envelope.metrics) == 2
            assert envelope.metrics[0].fields["mbps"] == 0.0