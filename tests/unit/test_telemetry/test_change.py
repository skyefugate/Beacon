"""Tests for change detector sampler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from beacon.telemetry.samplers.change import ChangeDetector


class TestChangeDetector:
    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_no_change_no_event(self, mock_snap):
        state = {
            "default_route": "en0",
            "dns_servers": "8.8.8.8",
            "primary_ip": "192.168.1.100",
            "ssid": "abc12345",
        }
        mock_snap.return_value = state

        detector = ChangeDetector()
        # First sample — sets baseline
        metrics = await detector.sample()
        events = detector.pop_events()
        assert len(events) == 0

        # Second sample — same state, no change
        metrics = await detector.sample()
        events = detector.pop_events()
        assert len(events) == 0
        assert len(metrics) == 0

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_route_change_emits_event(self, mock_snap):
        detector = ChangeDetector()

        # First sample: baseline
        mock_snap.return_value = {
            "default_route": "en0",
            "dns_servers": "8.8.8.8",
            "primary_ip": "192.168.1.100",
            "ssid": None,
        }
        await detector.sample()

        # Second sample: route changed
        mock_snap.return_value = {
            "default_route": "en1",
            "dns_servers": "8.8.8.8",
            "primary_ip": "192.168.1.100",
            "ssid": None,
        }
        metrics = await detector.sample()
        events = detector.pop_events()

        assert len(events) == 1
        assert events[0].event_type == "default_route_changed"
        assert "en0 -> en1" in events[0].message
        assert len(metrics) == 1
        assert metrics[0].fields["changes_detected"] == 1

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_multiple_changes(self, mock_snap):
        detector = ChangeDetector()

        # Baseline
        mock_snap.return_value = {
            "default_route": "en0",
            "dns_servers": "8.8.8.8",
            "primary_ip": "192.168.1.100",
            "ssid": "HomeNet",
        }
        await detector.sample()

        # Everything changed
        mock_snap.return_value = {
            "default_route": "en1",
            "dns_servers": "1.1.1.1",
            "primary_ip": "10.0.0.5",
            "ssid": "OfficeNet",
        }
        metrics = await detector.sample()
        events = detector.pop_events()

        assert len(events) == 4
        assert metrics[0].fields["changes_detected"] == 4

    @pytest.mark.asyncio
    @patch.object(ChangeDetector, "_snapshot")
    async def test_none_to_value_is_not_change(self, mock_snap):
        """First observation (None -> value) should not fire."""
        detector = ChangeDetector()

        mock_snap.return_value = {
            "default_route": "en0",
            "dns_servers": "8.8.8.8",
            "primary_ip": "192.168.1.100",
            "ssid": "MyNet",
        }
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
