"""Tests for traceroute runner - focusing on error paths and edge cases."""

import subprocess
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from beacon.runners.base import RunnerConfig
from beacon.runners.traceroute import TracerouteRunner


class TestTracerouteRunner:
    def test_successful_traceroute(self):
        traceroute_output = (
            "traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets\n"
            " 1  gateway (192.168.1.1)  1.234 ms  1.456 ms  1.789 ms\n"
            " 2  10.0.0.1 (10.0.0.1)  5.123 ms  5.456 ms  5.789 ms\n"
            " 3  dns.google (8.8.8.8)  10.123 ms  10.456 ms  10.789 ms\n"
        )
        
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=traceroute_output
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            assert envelope.plugin_name == "traceroute"
            assert len(envelope.metrics) == 4  # 3 hops + 1 summary
            
            # Check hop metrics
            hop_metrics = [m for m in envelope.metrics if m.measurement == "traceroute_hop"]
            assert len(hop_metrics) == 3
            
            # Check summary metric
            summary_metrics = [m for m in envelope.metrics if m.measurement == "traceroute_summary"]
            assert len(summary_metrics) == 1
            assert summary_metrics[0].fields["total_hops"] == 3
            assert summary_metrics[0].fields["timeout_hops"] == 0

    def test_default_target(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" 1  8.8.8.8  10.0 ms  10.0 ms  10.0 ms\n"
            )

            runner = TracerouteRunner()
            config = RunnerConfig()  # No targets specified
            envelope = runner.run(uuid4(), config)

            # Should use default target 8.8.8.8
            assert len(envelope.metrics) >= 1

    def test_darwin_command(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Darwin"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" 1  8.8.8.8  10.0 ms  10.0 ms  10.0 ms\n"
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            # Verify Darwin-specific command was used
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "traceroute"
            assert "-m" in call_args
            assert "-w" in call_args
            assert "-q" in call_args

    def test_windows_command(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Windows"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" 1  8.8.8.8  10 ms  10 ms  10 ms\n"
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            # Verify Windows-specific command was used
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "tracert"
            assert "-h" in call_args

    def test_custom_max_hops_and_wait(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" 1  8.8.8.8  10.0 ms  10.0 ms  10.0 ms\n"
            )

            runner = TracerouteRunner()
            config = RunnerConfig(
                targets=["8.8.8.8"],
                extra={"max_hops": 15, "wait_seconds": 5}
            )
            envelope = runner.run(uuid4(), config)

            # Verify custom parameters were used
            call_args = mock_run.call_args[0][0]
            assert "15" in call_args
            assert "5" in call_args

    def test_timeout_error(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.side_effect = subprocess.TimeoutExpired("traceroute", 60)

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            assert any("timed out" in note for note in envelope.notes)

    def test_command_not_found(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.side_effect = FileNotFoundError()

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            assert any("not found" in note for note in envelope.notes)

    def test_generic_exception(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.side_effect = Exception("Unexpected error")

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            assert any("failed" in note for note in envelope.notes)

    def test_blackhole_detection(self):
        traceroute_output = (
            "traceroute to 8.8.8.8, 30 hops max\n"
            " 1  192.168.1.1  1.0 ms  1.0 ms  1.0 ms\n"
            " 2  * * *\n"
            " 3  * * *\n"
            " 4  * * *\n"
        )
        
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=traceroute_output
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            blackhole_events = [e for e in envelope.events if e.event_type == "traceroute_blackhole"]
            assert len(blackhole_events) == 1

    def test_multiple_targets(self):
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" 1  8.8.8.8  10.0 ms  10.0 ms  10.0 ms\n"
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8", "1.1.1.1", "9.9.9.9"])
            envelope = runner.run(uuid4(), config)

            # Should have metrics for all targets
            summary_metrics = [m for m in envelope.metrics if m.measurement == "traceroute_summary"]
            assert len(summary_metrics) == 3

    def test_parse_traceroute_complex(self):
        """Test parsing of complex traceroute output with various edge cases."""
        output = (
            "traceroute to example.com (93.184.216.34), 30 hops max, 60 byte packets\n"
            " 1  gateway (192.168.1.1)  1.234 ms  1.456 ms  1.789 ms\n"
            " 2  10.0.0.1  5.123 ms  5.456 ms  5.789 ms\n"
            " 3  * * *\n"
            " 4  mixed.example.com (203.0.113.1)  10.1 ms  * 10.5 ms\n"
            " 5  multiple.example.com (198.51.100.1)  15.1 ms  15.2 ms  15.3 ms\n"
            " 6  final (93.184.216.34)  20.0 ms  20.1 ms  20.2 ms\n"
        )
        
        hops = TracerouteRunner._parse_traceroute(output)
        
        assert len(hops) == 6
        
        # Hop 1: Normal hop with hostname and IP
        assert hops[0]["hop_number"] == 1
        assert hops[0]["ip"] == "192.168.1.1"
        assert hops[0]["hostname"] == "gateway"
        assert hops[0]["all_timeouts"] is False
        assert hops[0]["rtt_min_ms"] == 1.234
        assert hops[0]["rtt_avg_ms"] == pytest.approx(1.493, rel=1e-2)
        assert hops[0]["rtt_max_ms"] == 1.789
        
        # Hop 2: IP only, no hostname
        assert hops[1]["hop_number"] == 2
        assert hops[1]["ip"] == "10.0.0.1"
        assert "hostname" not in hops[1]
        
        # Hop 3: All timeouts
        assert hops[2]["hop_number"] == 3
        assert hops[2]["all_timeouts"] is True
        assert hops[2]["timeouts"] == 3
        assert "rtt_min_ms" not in hops[2]
        
        # Hop 4: Mixed timeouts and responses
        assert hops[3]["hop_number"] == 4
        assert hops[3]["all_timeouts"] is False
        assert hops[3]["timeouts"] == 1
        assert hops[3]["rtt_min_ms"] == 10.1
        
        # Hop 5: All responses
        assert hops[4]["hop_number"] == 5
        assert hops[4]["all_timeouts"] is False
        assert hops[4]["timeouts"] == 0

    def test_parse_traceroute_empty_output(self):
        """Test parsing of empty or invalid output."""
        hops = TracerouteRunner._parse_traceroute("")
        assert hops == []
        
        hops = TracerouteRunner._parse_traceroute("traceroute: command not found")
        assert hops == []

    def test_parse_traceroute_no_ip_match(self):
        """Test parsing hop without IP address."""
        output = " 1  some-weird-output  1.0 ms  2.0 ms  3.0 ms\n"
        hops = TracerouteRunner._parse_traceroute(output)
        
        assert len(hops) == 1
        assert hops[0]["hop_number"] == 1
        assert "ip" not in hops[0]
        assert hops[0]["rtt_min_ms"] == 1.0

    def test_parse_traceroute_malformed_rtt(self):
        """Test parsing with malformed RTT values."""
        output = " 1  192.168.1.1  abc ms  * def ms\n"
        hops = TracerouteRunner._parse_traceroute(output)
        
        assert len(hops) == 1
        assert hops[0]["hop_number"] == 1
        # Should handle malformed RTT gracefully
        assert hops[0]["timeouts"] >= 1

    def test_summary_completion_detection(self):
        """Test detection of completed vs incomplete traceroute."""
        # Complete traceroute
        complete_output = (
            " 1  192.168.1.1  1.0 ms  1.0 ms  1.0 ms\n"
            " 2  8.8.8.8  10.0 ms  10.0 ms  10.0 ms\n"
        )
        
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=complete_output
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            summary = [m for m in envelope.metrics if m.measurement == "traceroute_summary"][0]
            assert summary.fields["completed"] is True

        # Incomplete traceroute (ends with timeouts)
        incomplete_output = (
            " 1  192.168.1.1  1.0 ms  1.0 ms  1.0 ms\n"
            " 2  * * *\n"
        )
        
        with patch("beacon.runners.traceroute.subprocess.run") as mock_run, \
             patch("beacon.runners.traceroute.platform.system") as mock_platform:
            
            mock_platform.return_value = "Linux"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=incomplete_output.strip() + "* * *"
            )

            runner = TracerouteRunner()
            config = RunnerConfig(targets=["8.8.8.8"])
            envelope = runner.run(uuid4(), config)

            summary = [m for m in envelope.metrics if m.measurement == "traceroute_summary"][0]
            assert summary.fields["completed"] is False