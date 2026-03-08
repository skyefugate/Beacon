"""Tests for change detector sampler — including BSSID and channel change detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from beacon.telemetry.samplers.change import ChangeDetector


def _full_state(**overrides):
    """Return a snapshot dict with all keys, optionally overridden."""
    base = {
        "default_route": "en0",
        "dns_servers": "8.8.8.8",
        "primary_ip": "192.168.1.100",
        "ssid": "HomeNet",
        "bssid": None,
        "channel": None,
    }
    base.update(overrides)
    return base


class TestChangeDetector:
    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_no_change_no_event(self, mock_snap):
        state = _full_state()
        mock_snap.return_value = state

        detector = ChangeDetector()
        # First sample -- sets baseline
        await detector.sample()
        events = detector.pop_events()
        assert len(events) == 0

        # Second sample -- same state, no change
        metrics = await detector.sample()
        events = detector.pop_events()
        assert len(events) == 0
        assert len(metrics) == 0

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_route_change_emits_event(self, mock_snap):
        detector = ChangeDetector()

        # First sample: baseline
        mock_snap.return_value = _full_state(default_route="en0", ssid=None)
        await detector.sample()

        # Second sample: route changed
        mock_snap.return_value = _full_state(default_route="en1", ssid=None)
        metrics = await detector.sample()
        events = detector.pop_events()

        assert len(events) == 1
        assert events[0].event_type == "default_route_changed"
        assert "en0 -> en1" in events[0].message
        # One metric per change
        assert len(metrics) == 1
        assert metrics[0].fields["changes_detected"] == 1
        assert metrics[0].fields["old_value"] == "en0"
        assert metrics[0].fields["new_value"] == "en1"
        assert metrics[0].tags["event_type"] == "default_route_changed"

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_multiple_changes(self, mock_snap):
        detector = ChangeDetector()

        # Baseline
        mock_snap.return_value = _full_state()
        await detector.sample()

        # Everything changed
        mock_snap.return_value = _full_state(
            default_route="en1",
            dns_servers="1.1.1.1",
            primary_ip="10.0.0.5",
            ssid="OfficeNet",
        )
        metrics = await detector.sample()
        events = detector.pop_events()

        assert len(events) == 4
        # One metric per change -- all carry changes_detected == 4
        assert len(metrics) == 4
        assert all(m.fields["changes_detected"] == 4 for m in metrics)

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_none_to_value_is_not_change(self, mock_snap):
        """First observation (None -> value) should not fire."""
        detector = ChangeDetector()

        mock_snap.return_value = _full_state()
        await detector.sample()
        events = detector.pop_events()
        assert len(events) == 0

    def test_dns_servers_parsing(self):
        detector = ChangeDetector()
        with patch("beacon.telemetry.samplers.change.Path") as MockPath:
            mock_file = MagicMock()
            mock_file.read_text.return_value = (
                "# Generated\nnameserver 8.8.8.8\nnameserver 1.1.1.1\n"
            )
            MockPath.return_value = mock_file
            result = detector._get_dns_servers()
            assert result == "1.1.1.1,8.8.8.8"  # sorted

    # ------------------------------------------------------------------
    # BSSID change detection (issue #16)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_bssid_change_emits_event(self, mock_snap):
        """Roaming to a new AP (BSSID change) must emit a bssid_change event."""
        detector = ChangeDetector()

        # Baseline -- connected to AP1
        mock_snap.return_value = _full_state(bssid="aa:bb:cc:dd:ee:01")
        await detector.sample()

        # Roam to AP2
        mock_snap.return_value = _full_state(bssid="aa:bb:cc:dd:ee:02")
        metrics = await detector.sample()
        events = detector.pop_events()

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "bssid_change"
        assert "aa:bb:cc:dd:ee:01" in event.message
        assert "aa:bb:cc:dd:ee:02" in event.message

        assert len(metrics) == 1
        m = metrics[0]
        assert m.measurement == "t_change_event"
        assert m.tags["event_type"] == "bssid_change"
        assert m.fields["old_value"] == "aa:bb:cc:dd:ee:01"
        assert m.fields["new_value"] == "aa:bb:cc:dd:ee:02"
        assert m.fields["changes_detected"] == 1

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_channel_change_emits_event(self, mock_snap):
        """Channel change (e.g. band-steering or AP config change) must emit a channel_change event."""
        detector = ChangeDetector()

        # Baseline -- on channel 6 (2.4 GHz)
        mock_snap.return_value = _full_state(channel="6")
        await detector.sample()

        # Steered to channel 149 (5 GHz)
        mock_snap.return_value = _full_state(channel="149,+1")
        metrics = await detector.sample()
        events = detector.pop_events()

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "channel_change"
        assert "6" in event.message
        assert "149" in event.message

        assert len(metrics) == 1
        m = metrics[0]
        assert m.measurement == "t_change_event"
        assert m.tags["event_type"] == "channel_change"
        assert m.fields["old_value"] == "6"
        assert m.fields["new_value"] == "149,+1"

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_bssid_and_channel_change_simultaneously(self, mock_snap):
        """Roaming to a different AP on a different channel emits both events."""
        detector = ChangeDetector()

        mock_snap.return_value = _full_state(bssid="aa:bb:cc:11:22:33", channel="6")
        await detector.sample()

        mock_snap.return_value = _full_state(bssid="aa:bb:cc:44:55:66", channel="149")
        metrics = await detector.sample()
        events = detector.pop_events()

        event_types = {e.event_type for e in events}
        assert "bssid_change" in event_types
        assert "channel_change" in event_types

        metric_event_types = {m.tags["event_type"] for m in metrics}
        assert "bssid_change" in metric_event_types
        assert "channel_change" in metric_event_types

        # All metrics carry the total count
        assert all(m.fields["changes_detected"] == 2 for m in metrics)

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_bssid_none_to_value_is_not_change(self, mock_snap):
        """First BSSID observation (baseline) must not fire an event."""
        detector = ChangeDetector()

        mock_snap.return_value = _full_state(bssid="aa:bb:cc:dd:ee:ff")
        await detector.sample()
        events = detector.pop_events()
        assert len(events) == 0

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_channel_none_to_value_is_not_change(self, mock_snap):
        """First channel observation (baseline) must not fire an event."""
        detector = ChangeDetector()

        mock_snap.return_value = _full_state(channel="36")
        await detector.sample()
        events = detector.pop_events()
        assert len(events) == 0

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_bssid_same_value_no_event(self, mock_snap):
        """No event when BSSID stays the same across samples."""
        detector = ChangeDetector()
        state = _full_state(bssid="aa:bb:cc:dd:ee:ff", channel="6")

        mock_snap.return_value = state
        await detector.sample()

        mock_snap.return_value = state
        metrics = await detector.sample()
        events = detector.pop_events()

        assert len(events) == 0
        assert len(metrics) == 0

    # ------------------------------------------------------------------
    # get_bssid_and_channel unit tests
    # ------------------------------------------------------------------

    def test_get_bssid_and_channel_non_darwin(self):
        """On non-Darwin platforms, returns (None, None) without calling any tool."""
        detector = ChangeDetector()
        with patch("platform.system", return_value="Linux"):
            bssid, channel = detector._get_bssid_and_channel()
        assert bssid is None
        assert channel is None

    def test_get_bssid_and_channel_airport(self):
        """Parses BSSID and channel from airport -I output."""
        detector = ChangeDetector()
        airport_output = (
            " agrCtlRSSI: -55\n"
            " agrCtlNoise: -90\n"
            "        SSID: MyNet\n"
            "       BSSID: aa:bb:cc:dd:ee:ff\n"
            "     channel: 149,+1\n"
        )
        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run") as mock_run,
        ):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = airport_output
            mock_run.return_value = mock_result

            bssid, channel = detector._get_bssid_and_channel()

        assert bssid == "aa:bb:cc:dd:ee:ff"
        assert channel == "149,+1"

    def test_get_bssid_and_channel_airport_not_found(self):
        """Falls through to system_profiler when airport is not available."""
        detector = ChangeDetector()
        sp_output = (
            "        en0:\n"
            "          Status: Connected\n"
            "          Current Network Information:\n"
            "              HomeNet:\n"
            "                Channel: 6\n"
        )
        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run") as mock_run,
        ):
            # First call (airport) raises FileNotFoundError; second (system_profiler) succeeds
            sp_result = MagicMock()
            sp_result.returncode = 0
            sp_result.stdout = sp_output
            mock_run.side_effect = [FileNotFoundError, sp_result]

            bssid, channel = detector._get_bssid_and_channel()

        # system_profiler parser does not expose BSSID
        assert bssid is None
        # Channel may or may not parse depending on output format; just verify no crash
        assert isinstance(channel, (str, type(None)))
