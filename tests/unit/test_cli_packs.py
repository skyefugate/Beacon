"""Tests for beacon packs CLI commands."""

from __future__ import annotations

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
def mock_pack():
    """Mock diagnostic pack."""
    step1 = MagicMock(plugin="network", type="ping", enabled=True, privileged=False)
    step2 = MagicMock(plugin="system", type="cpu", enabled=False, privileged=True)

    pack = MagicMock()
    pack.name = "test_pack"
    pack.description = "Test diagnostic pack"
    pack.version = "1.0.0"
    pack.steps = [step1, step2]

    return pack


class TestPacksList:
    def test_list_no_packs(self):
        """Test list command when no packs are available."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.list_packs.return_value = []

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "list"])

            assert result.exit_code == 0
            assert "No packs found" in result.output
            assert "Check the 'packs/' directory" in result.output

    def test_list_with_packs(self, mock_pack):
        """Test list command with available packs."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.list_packs.return_value = [mock_pack]

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "list"])

            assert result.exit_code == 0
            assert "Available Packs" in result.output
            assert "test_pack" in result.output
            assert "Test diagnostic pack" in result.output
            assert "1.0.0" in result.output
            assert "2" in result.output  # Number of steps

    def test_list_no_packs_directory(self):
        """Test list command when packs directory doesn't exist."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.list_packs.return_value = []

            with patch.object(Path, "is_dir", return_value=False):
                result = runner.invoke(app, ["packs", "list"])

            assert result.exit_code == 0
            assert "No packs found" in result.output
            # Should not try to load from directory
            mock_registry.load_from_directory.assert_not_called()

    def test_list_loads_from_packs_directory(self, mock_pack):
        """Test that list command loads packs from the packs directory."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.list_packs.return_value = [mock_pack]

            with patch.object(Path, "is_dir", return_value=True):
                runner.invoke(app, ["packs", "list"])

            mock_registry.load_from_directory.assert_called_once_with(Path("packs"))

    def test_list_multiple_packs(self):
        """Test list command with multiple packs."""
        pack1 = MagicMock()
        pack1.name = "pack1"
        pack1.description = "First pack"
        pack1.version = "1.0.0"
        pack1.steps = [MagicMock()]

        pack2 = MagicMock()
        pack2.name = "pack2"
        pack2.description = "Second pack"
        pack2.version = "2.0.0"
        pack2.steps = [MagicMock(), MagicMock()]

        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.list_packs.return_value = [pack1, pack2]

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "list"])

            assert result.exit_code == 0
            assert "pack1" in result.output
            assert "pack2" in result.output
            assert "First pack" in result.output
            assert "Second pack" in result.output


class TestPacksShow:
    def test_show_existing_pack(self, mock_pack):
        """Test show command for existing pack."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "show", "test_pack"])

            assert result.exit_code == 0
            assert "test_pack" in result.output
            assert "Test diagnostic pack" in result.output
            assert "1.0.0" in result.output
            assert "Steps" in result.output
            assert "network" in result.output
            assert "ping" in result.output
            assert "system" in result.output
            assert "cpu" in result.output

    def test_show_nonexistent_pack(self):
        """Test show command for nonexistent pack."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = None

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "show", "nonexistent"])

            assert result.exit_code == 1
            assert "Pack 'nonexistent' not found" in result.output

    def test_show_pack_step_status_display(self, mock_pack):
        """Test that show command displays step status correctly."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "show", "test_pack"])

            assert result.exit_code == 0
            # First step: enabled=True, privileged=False
            assert "enabled" in result.output
            assert "no" in result.output  # privileged=False
            # Second step: enabled=False, privileged=True
            assert "disabled" in result.output
            assert "yes" in result.output  # privileged=True

    def test_show_loads_from_packs_directory(self, mock_pack):
        """Test that show command loads packs from the packs directory."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack

            with patch.object(Path, "is_dir", return_value=True):
                runner.invoke(app, ["packs", "show", "test_pack"])

            mock_registry.load_from_directory.assert_called_once_with(Path("packs"))

    def test_show_no_packs_directory(self):
        """Test show command when packs directory doesn't exist."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = None

            with patch.object(Path, "is_dir", return_value=False):
                result = runner.invoke(app, ["packs", "show", "test_pack"])

            assert result.exit_code == 1
            # Should not try to load from directory
            mock_registry.load_from_directory.assert_not_called()

    def test_show_pack_with_no_steps(self):
        """Test show command for pack with no steps."""
        pack_no_steps = MagicMock(
            name="empty_pack", description="Pack with no steps", version="1.0.0", steps=[]
        )

        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = pack_no_steps

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "show", "empty_pack"])

            assert result.exit_code == 0
            assert "empty_pack" in result.output
            assert "Steps" in result.output


class TestPacksCommandErrors:
    def test_missing_pack_name_for_show(self):
        """Test show command without pack name argument."""
        result = runner.invoke(app, ["packs", "show"])

        assert result.exit_code != 0
        # Typer should show usage/help

    def test_invalid_packs_subcommand(self):
        """Test invalid packs subcommand."""
        result = runner.invoke(app, ["packs", "invalid"])

        assert result.exit_code != 0

    def test_pack_registry_exception_list(self):
        """Test handling of pack registry exceptions in list command."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            MockRegistry.side_effect = Exception("Registry error")

            result = runner.invoke(app, ["packs", "list"])

            assert result.exit_code != 0

    def test_pack_registry_exception_show(self):
        """Test handling of pack registry exceptions in show command."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            MockRegistry.side_effect = Exception("Registry error")

            result = runner.invoke(app, ["packs", "show", "test_pack"])

            assert result.exit_code != 0

    def test_load_from_directory_exception(self):
        """Test handling of load_from_directory exceptions."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry:
            mock_registry = MockRegistry.return_value
            mock_registry.load_from_directory.side_effect = Exception("Load error")
            mock_registry.list_packs.return_value = []

            with patch.object(Path, "is_dir", return_value=True):
                result = runner.invoke(app, ["packs", "list"])

            # Should handle the exception gracefully
            assert result.exit_code != 0
