"""Tests for NicSampler -- per-NIC network interface traffic sampler."""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import patch

import pytest

from beacon.telemetry.samplers.nic import NicSampler, _LOOPBACK_INTERFACES


# Mimic psutil snetio named tuple
snetio = namedtuple(
    "snetio",
    [
        "bytes_sent",
        "bytes_recv",
        "packets_sent",
        "packets_recv",
        "errin",
        "errout",
        "dropin",
        "dropout",
    ],
)


def _make_counters(
    bytes_sent=1000,
    bytes_recv=5000,
    packets_sent=10,
    packets_recv=50,
    errin=0,
    errout=0,
    dropin=0,
    dropout=0,
):
    return snetio(
        bytes_sent=bytes_sent,
        bytes_recv=bytes_recv,
        packets_sent=packets_sent,
        packets_recv=packets_recv,
        errin=errin,
        errout=errout,
        dropin=dropin,
        dropout=dropout,
    )


class TestNicSamplerMetadata:
    def test_name(self):
        assert NicSampler.name == "nic"

    def test_tier(self):
        assert NicSampler.tier == 0

    def test_default_interval(self):
        assert NicSampler.default_interval == 30

    def test_loopback_interfaces(self):
        assert "lo" in _LOOPBACK_INTERFACES
        assert "lo0" in _LOOPBACK_INTERFACES


class TestNicSamplerFirstSample:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_first_sample_returns_no_metrics(self, mock_time, mock_psutil):
        mock_time.monotonic.return_value = 1000.0
        mock_psutil.net_io_counters.return_value = {"eth0": _make_counters()}
        sampler = NicSampler()
        metrics = await sampler.sample()
        assert metrics == []
        assert "eth0" in sampler._prev

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_loopback_skipped_by_default(self, mock_time, mock_psutil):
        mock_time.monotonic.return_value = 1000.0
        mock_psutil.net_io_counters.return_value = {"lo": _make_counters(), "lo0": _make_counters()}
        sampler = NicSampler(skip_loopback=True)
        await sampler.sample()
        assert "lo" not in sampler._prev
        assert "lo0" not in sampler._prev

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_loopback_included_when_disabled(self, mock_time, mock_psutil):
        mock_time.monotonic.return_value = 1000.0
        mock_psutil.net_io_counters.return_value = {"lo": _make_counters()}
        sampler = NicSampler(skip_loopback=False)
        await sampler.sample()
        assert "lo" in sampler._prev


class TestNicSamplerDeltas:
    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_second_sample_produces_metrics(self, mock_time, mock_psutil):
        first = {"eth0": _make_counters(bytes_sent=1000, bytes_recv=5000)}
        second = {"eth0": _make_counters(bytes_sent=2000, bytes_recv=6000)}
        mock_time.monotonic.side_effect = [1000.0, 1010.0]
        mock_psutil.net_io_counters.side_effect = [first, second]
        sampler = NicSampler()
        await sampler.sample()
        metrics = await sampler.sample()
        assert len(metrics) == 1
        m = metrics[0]
        assert m.measurement == "t_nic_traffic"
        assert m.tags == {"interface": "eth0"}
        assert m.fields["bytes_sent_rate"] == 100.0
        assert m.fields["bytes_recv_rate"] == 100.0
        assert m.fields["bytes_sent"] == 1000
        assert m.fields["bytes_recv"] == 1000

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_packet_counts_reported(self, mock_time, mock_psutil):
        first = {"eth0": _make_counters(packets_sent=100, packets_recv=500)}
        second = {"eth0": _make_counters(packets_sent=200, packets_recv=600)}
        mock_time.monotonic.side_effect = [1000.0, 1005.0]
        mock_psutil.net_io_counters.side_effect = [first, second]
        sampler = NicSampler()
        await sampler.sample()
        metrics = await sampler.sample()
        assert len(metrics) == 1
        fields = metrics[0].fields
        assert fields["packets_sent_rate"] == 20.0
        assert fields["packets_recv_rate"] == 20.0
        assert fields["packets_sent"] == 100
        assert fields["packets_recv"] == 100

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_errors_and_drops_reported(self, mock_time, mock_psutil):
        first = {"eth0": _make_counters(errin=5, errout=2, dropin=10, dropout=3)}
        second = {"eth0": _make_counters(errin=8, errout=4, dropin=15, dropout=5)}
        mock_time.monotonic.side_effect = [1000.0, 1030.0]
        mock_psutil.net_io_counters.side_effect = [first, second]
        sampler = NicSampler()
        await sampler.sample()
        metrics = await sampler.sample()
        assert len(metrics) == 1
        fields = metrics[0].fields
        assert fields["errors_in"] == 3
        assert fields["errors_out"] == 2
        assert fields["drops_in"] == 5
        assert fields["drops_out"] == 2

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_counter_wraparound_clamped_to_zero(self, mock_time, mock_psutil):
        first = {"eth0": _make_counters(bytes_sent=5000)}
        second = {"eth0": _make_counters(bytes_sent=100)}
        mock_time.monotonic.side_effect = [1000.0, 1030.0]
        mock_psutil.net_io_counters.side_effect = [first, second]
        sampler = NicSampler()
        await sampler.sample()
        metrics = await sampler.sample()
        assert len(metrics) == 1
        assert metrics[0].fields["bytes_sent"] == 0
        assert metrics[0].fields["bytes_sent_rate"] == 0.0

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_multiple_nics(self, mock_time, mock_psutil):
        first = {"eth0": _make_counters(bytes_sent=1000), "wlan0": _make_counters(bytes_sent=2000)}
        second = {"eth0": _make_counters(bytes_sent=2000), "wlan0": _make_counters(bytes_sent=4000)}
        mock_time.monotonic.side_effect = [1000.0, 1010.0]
        mock_psutil.net_io_counters.side_effect = [first, second]
        sampler = NicSampler()
        await sampler.sample()
        metrics = await sampler.sample()
        assert len(metrics) == 2
        interfaces = {m.tags["interface"] for m in metrics}
        assert interfaces == {"eth0", "wlan0"}

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_disappeared_nic_removed_from_state(self, mock_time, mock_psutil):
        first = {"eth0": _make_counters(), "eth1": _make_counters()}
        second = {"eth0": _make_counters(bytes_sent=1000)}
        mock_time.monotonic.side_effect = [1000.0, 1010.0]
        mock_psutil.net_io_counters.side_effect = [first, second]
        sampler = NicSampler()
        await sampler.sample()
        assert "eth1" in sampler._prev
        await sampler.sample()
        assert "eth1" not in sampler._prev

    @pytest.mark.asyncio
    @patch("beacon.telemetry.samplers.nic.psutil")
    @patch("beacon.telemetry.samplers.nic.time")
    async def test_psutil_exception_returns_empty(self, mock_time, mock_psutil):
        mock_psutil.net_io_counters.side_effect = RuntimeError("no network")
        sampler = NicSampler()
        metrics = await sampler.sample()
        assert metrics == []


class TestNicSamplerComputeFields:
    def test_compute_fields_basic(self):
        prev = _make_counters(
            bytes_sent=0,
            bytes_recv=0,
            packets_sent=0,
            packets_recv=0,
            errin=0,
            errout=0,
            dropin=0,
            dropout=0,
        )
        current = _make_counters(
            bytes_sent=3000,
            bytes_recv=9000,
            packets_sent=30,
            packets_recv=90,
            errin=1,
            errout=2,
            dropin=3,
            dropout=4,
        )
        fields = NicSampler._compute_fields(current, prev, elapsed=10.0)
        assert fields["bytes_sent_rate"] == 300.0
        assert fields["bytes_recv_rate"] == 900.0
        assert fields["packets_sent_rate"] == 3.0
        assert fields["packets_recv_rate"] == 9.0
        assert fields["bytes_sent"] == 3000
        assert fields["bytes_recv"] == 9000
        assert fields["packets_sent"] == 30
        assert fields["packets_recv"] == 90
        assert fields["errors_in"] == 1
        assert fields["errors_out"] == 2
        assert fields["drops_in"] == 3
        assert fields["drops_out"] == 4
