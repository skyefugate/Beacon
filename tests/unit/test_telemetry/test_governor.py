"""Tests for resource governor — CPU, memory, battery limits."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from beacon.telemetry.governor import ResourceGovernor


class TestResourceGovernor:
    @patch("beacon.telemetry.governor.psutil")
    def test_all_clear(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 2.0
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=50 * 1024 * 1024,  # 50 MB
        )
        mock_psutil.sensors_battery.return_value = MagicMock(percent=80.0)

        gov = ResourceGovernor()
        advice = gov.check()

        assert advice.max_tier == 2
        assert advice.interval_multiplier == 1.0
        assert advice.suspend is False

    @patch("beacon.telemetry.governor.psutil")
    def test_cpu_soft_limit(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 7.0  # > 5% soft
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=50 * 1024 * 1024,
        )
        mock_psutil.sensors_battery.return_value = None

        gov = ResourceGovernor(cpu_soft_pct=5.0)
        advice = gov.check()

        assert advice.max_tier == 1
        assert advice.interval_multiplier == 2.0
        assert advice.suspend is False

    @patch("beacon.telemetry.governor.psutil")
    def test_cpu_hard_limit(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 15.0  # > 10% hard
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=50 * 1024 * 1024,
        )
        mock_psutil.sensors_battery.return_value = None

        gov = ResourceGovernor(cpu_hard_pct=10.0)
        advice = gov.check()

        assert advice.max_tier == 0
        assert advice.interval_multiplier == 3.0
        assert "hard limit" in advice.reason

    @patch("beacon.telemetry.governor.psutil")
    def test_memory_limit(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 1.0
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=150 * 1024 * 1024,  # 150 MB > 100 MB limit
        )
        mock_psutil.sensors_battery.return_value = None

        gov = ResourceGovernor(memory_max_mb=100)
        advice = gov.check()

        assert advice.max_tier == 0
        assert advice.interval_multiplier == 2.0
        assert "Memory" in advice.reason

    @patch("beacon.telemetry.governor.psutil")
    def test_battery_low(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 1.0
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=50 * 1024 * 1024,
        )
        mock_psutil.sensors_battery.return_value = MagicMock(percent=15.0)

        gov = ResourceGovernor(battery_low_pct=20)
        advice = gov.check()

        assert advice.max_tier == 1
        assert advice.interval_multiplier == 1.5
        assert "low" in advice.reason

    @patch("beacon.telemetry.governor.psutil")
    def test_battery_critical_suspends(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 1.0
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=50 * 1024 * 1024,
        )
        mock_psutil.sensors_battery.return_value = MagicMock(percent=5.0)

        gov = ResourceGovernor(battery_critical_pct=10)
        advice = gov.check()

        assert advice.suspend is True
        assert "critical" in advice.reason

    @patch("beacon.telemetry.governor.psutil")
    def test_no_battery(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 1.0
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=50 * 1024 * 1024,
        )
        mock_psutil.sensors_battery.return_value = None

        gov = ResourceGovernor()
        advice = gov.check()

        assert advice.max_tier == 2
        assert advice.suspend is False

    @patch("beacon.telemetry.governor.psutil")
    def test_priority_order_battery_critical_first(self, mock_psutil):
        """Battery critical should win over CPU hard limit."""
        mock_psutil.cpu_percent.return_value = 99.0
        mock_psutil.Process.return_value.memory_info.return_value = MagicMock(
            rss=200 * 1024 * 1024,
        )
        mock_psutil.sensors_battery.return_value = MagicMock(percent=3.0)

        gov = ResourceGovernor()
        advice = gov.check()

        assert advice.suspend is True
