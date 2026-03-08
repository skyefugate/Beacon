"""Tests for TcpSampler -- TCP retransmit and socket error counters."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from beacon.telemetry.samplers.tcp import TcpSampler


# Fixture data ----------------------------------------------------------------

NETSTAT_MACOS_SAMPLE = "tcp:\n    12345 packets sent\n        9876 data packets (12345678 bytes)\n        2345 data packets (4567890 bytes) retransmitted\n        0 resends initiated by MTU discovery\n    23456 packets received\n    123 bad connection attempts\n    45 connections reset\n    567 connection requests\n    234 connection accepts\n"

PROC_NET_SNMP_SAMPLE = "Ip: Forwarding DefaultTTL InReceives InHdrErrors\nIp: 2 64 1234567 0\nIcmp: InMsgs InErrors InCsumErrors InDestUnreachs\nIcmp: 1 0 0 1\nTcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens AttemptFails EstabResets CurrEstab InSegs OutSegs RetransSegs InErrs OutRsts InCsumErrors\nTcp: 1 200 120000 -1 5678 1234 56 789 12 9876543 9765432 345 0 678 0\nUdp: InDatagrams NoPorts InErrors OutDatagrams\nUdp: 123456 0 0 123456\n"


class TestParseMacOS:
    def test_retransmits_parsed(self):
        counters = TcpSampler._parse_netstat_macos(NETSTAT_MACOS_SAMPLE)
        assert counters["retransmits"] == 2345

    def test_connection_failures_parsed(self):
        counters = TcpSampler._parse_netstat_macos(NETSTAT_MACOS_SAMPLE)
        assert counters["connection_failures"] == 123

    def test_resets_parsed(self):
        counters = TcpSampler._parse_netstat_macos(NETSTAT_MACOS_SAMPLE)
        assert counters["resets"] == 45

    def test_active_opens_parsed(self):
        counters = TcpSampler._parse_netstat_macos(NETSTAT_MACOS_SAMPLE)
        assert counters["active_opens"] == 567

    def test_passive_opens_parsed(self):
        counters = TcpSampler._parse_netstat_macos(NETSTAT_MACOS_SAMPLE)
        assert counters["passive_opens"] == 234

    def test_empty_output_returns_zeros(self):
        counters = TcpSampler._parse_netstat_macos("")
        assert counters["retransmits"] == 0
        assert counters["connection_failures"] == 0
        assert counters["resets"] == 0
        assert counters["active_opens"] == 0
        assert counters["passive_opens"] == 0


class TestParseProcNetSnmp:
    def test_active_opens(self):
        counters = TcpSampler._parse_proc_net_snmp(PROC_NET_SNMP_SAMPLE)
        assert counters is not None
        assert counters["active_opens"] == 5678

    def test_passive_opens(self):
        counters = TcpSampler._parse_proc_net_snmp(PROC_NET_SNMP_SAMPLE)
        assert counters is not None
        assert counters["passive_opens"] == 1234

    def test_connection_failures(self):
        counters = TcpSampler._parse_proc_net_snmp(PROC_NET_SNMP_SAMPLE)
        assert counters is not None
        assert counters["connection_failures"] == 56

    def test_resets(self):
        counters = TcpSampler._parse_proc_net_snmp(PROC_NET_SNMP_SAMPLE)
        assert counters is not None
        assert counters["resets"] == 789

    def test_retransmits(self):
        counters = TcpSampler._parse_proc_net_snmp(PROC_NET_SNMP_SAMPLE)
        assert counters is not None
        assert counters["retransmits"] == 345

    def test_missing_tcp_rows_returns_none(self):
        ip_only = "Ip: a b c" + chr(10) + "Ip: 1 2 3" + chr(10)
        result = TcpSampler._parse_proc_net_snmp(ip_only)
        assert result is None

    def test_empty_content_returns_none(self):
        result = TcpSampler._parse_proc_net_snmp("")
        assert result is None


class TestComputeDeltas:
    def test_first_sample_returns_none(self):
        sampler = TcpSampler()
        result = sampler._compute_deltas(
            {
                "retransmits": 100,
                "connection_failures": 5,
                "resets": 10,
                "active_opens": 50,
                "passive_opens": 20,
            }
        )
        assert result is None

    def test_second_sample_returns_rates(self):
        sampler = TcpSampler()
        prev = {
            "retransmits": 100,
            "connection_failures": 5,
            "resets": 10,
            "active_opens": 50,
            "passive_opens": 20,
        }
        curr = {
            "retransmits": 130,
            "connection_failures": 8,
            "resets": 12,
            "active_opens": 55,
            "passive_opens": 25,
        }
        sampler._prev = prev
        result = sampler._compute_deltas(curr)
        assert result is not None
        assert result["retransmits_per_sec"] == pytest.approx(30 / 30)
        assert result["connection_failures"] == pytest.approx(3.0)
        assert result["resets_per_sec"] == pytest.approx(2 / 30)
        assert result["active_opens"] == pytest.approx(5.0)
        assert result["passive_opens"] == pytest.approx(5.0)

    def test_counter_reset_clamped_to_zero(self):
        sampler = TcpSampler()
        sampler._prev = {
            "retransmits": 1000,
            "connection_failures": 0,
            "resets": 0,
            "active_opens": 0,
            "passive_opens": 0,
        }
        curr = {
            "retransmits": 5,
            "connection_failures": 0,
            "resets": 0,
            "active_opens": 0,
            "passive_opens": 0,
        }
        result = sampler._compute_deltas(curr)
        assert result is not None
        assert result["retransmits_per_sec"] == 0.0

    def test_zero_delta_all_zeros(self):
        sampler = TcpSampler()
        counters = {
            "retransmits": 100,
            "connection_failures": 5,
            "resets": 10,
            "active_opens": 50,
            "passive_opens": 20,
        }
        sampler._prev = counters.copy()
        result = sampler._compute_deltas(counters.copy())
        assert result is not None
        assert result["retransmits_per_sec"] == 0.0
        assert result["connection_failures"] == 0.0
        assert result["resets_per_sec"] == 0.0
        assert result["active_opens"] == 0.0
        assert result["passive_opens"] == 0.0


class TestTcpSamplerSample:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tcp.platform.system")
    @patch("beacon.telemetry.samplers.tcp.asyncio.to_thread")
    async def test_first_sample_returns_empty(self, mock_to_thread, mock_system):
        mock_system.return_value = "Darwin"
        mock_to_thread.return_value = {
            "retransmits": 100,
            "connection_failures": 5,
            "resets": 10,
            "active_opens": 50,
            "passive_opens": 20,
        }
        sampler = TcpSampler()
        metrics = await sampler.sample()
        assert metrics == []
        assert sampler._prev is not None

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tcp.platform.system")
    @patch("beacon.telemetry.samplers.tcp.asyncio.to_thread")
    async def test_second_sample_returns_metrics(self, mock_to_thread, mock_system):
        mock_system.return_value = "Darwin"
        sampler = TcpSampler()
        sampler._prev = {
            "retransmits": 100,
            "connection_failures": 5,
            "resets": 10,
            "active_opens": 50,
            "passive_opens": 20,
        }
        mock_to_thread.return_value = {
            "retransmits": 160,
            "connection_failures": 8,
            "resets": 13,
            "active_opens": 55,
            "passive_opens": 23,
        }
        metrics = await sampler.sample()
        assert len(metrics) == 1
        m = metrics[0]
        assert m.measurement == "t_tcp_stats"
        assert "retransmits_per_sec" in m.fields
        assert "connection_failures" in m.fields
        assert "resets_per_sec" in m.fields
        assert "active_opens" in m.fields
        assert "passive_opens" in m.fields
        assert m.fields["retransmits_per_sec"] == pytest.approx(60 / 30)
        assert m.fields["connection_failures"] == pytest.approx(3.0)

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tcp.platform.system")
    @patch("beacon.telemetry.samplers.tcp.asyncio.to_thread")
    async def test_collect_returns_none_returns_empty(self, mock_to_thread, mock_system):
        mock_system.return_value = "Darwin"
        mock_to_thread.return_value = None
        sampler = TcpSampler()
        sampler._prev = {
            "retransmits": 100,
            "connection_failures": 0,
            "resets": 0,
            "active_opens": 0,
            "passive_opens": 0,
        }
        metrics = await sampler.sample()
        assert metrics == []

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tcp.platform.system")
    async def test_unsupported_platform_returns_empty(self, mock_system):
        mock_system.return_value = "Windows"
        sampler = TcpSampler()
        metrics = await sampler.sample()
        assert metrics == []

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.tcp.platform.system")
    @patch("beacon.telemetry.samplers.tcp.asyncio.to_thread")
    async def test_exception_in_collection_returns_empty(self, mock_to_thread, mock_system):
        mock_system.return_value = "Linux"
        mock_to_thread.side_effect = RuntimeError("unexpected failure")
        sampler = TcpSampler()
        metrics = await sampler.sample()
        assert metrics == []


class TestCollectMacOS:
    @patch("beacon.telemetry.samplers.tcp.subprocess")
    def test_netstat_success(self, mock_subprocess):
        result_mock = MagicMock()
        result_mock.returncode = 0
        result_mock.stdout = NETSTAT_MACOS_SAMPLE
        mock_subprocess.run.return_value = result_mock
        sampler = TcpSampler()
        counters = sampler._collect_macos()
        assert counters is not None
        assert counters["retransmits"] == 2345
        assert counters["connection_failures"] == 123

    @patch("beacon.telemetry.samplers.tcp.subprocess")
    def test_netstat_nonzero_exit_returns_none(self, mock_subprocess):
        result_mock = MagicMock()
        result_mock.returncode = 1
        result_mock.stderr = "permission denied"
        result_mock.stdout = ""
        mock_subprocess.run.return_value = result_mock
        sampler = TcpSampler()
        result = sampler._collect_macos()
        assert result is None

    @patch("beacon.telemetry.samplers.tcp.subprocess")
    def test_netstat_not_found_returns_none(self, mock_subprocess):
        mock_subprocess.run.side_effect = FileNotFoundError("netstat not found")
        mock_subprocess.TimeoutExpired = TimeoutError
        sampler = TcpSampler()
        result = sampler._collect_macos()
        assert result is None


class TestCollectLinux:
    def test_reads_proc_net_snmp(self, tmp_path):
        snmp_file = tmp_path / "snmp"
        snmp_file.write_text(PROC_NET_SNMP_SAMPLE)
        sampler = TcpSampler()
        counters = sampler._collect_linux(snmp_path=str(snmp_file))
        assert counters is not None
        assert counters["active_opens"] == 5678
        assert counters["retransmits"] == 345

    def test_missing_file_returns_none(self, tmp_path):
        sampler = TcpSampler()
        result = sampler._collect_linux(snmp_path=str(tmp_path / "nonexistent"))
        assert result is None


class TestTcpSamplerMetadata:
    def test_name(self):
        assert TcpSampler.name == "tcp"

    def test_tier(self):
        assert TcpSampler.tier == 0

    def test_default_interval(self):
        assert TcpSampler.default_interval == 30
