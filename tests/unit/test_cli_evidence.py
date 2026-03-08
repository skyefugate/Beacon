"""Tests for beacon evidence CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

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
def mock_evidence_pack():
    """Mock evidence pack data."""
    return MagicMock(
        pack_name="test_pack",
        fault_domain=MagicMock(
            fault_domain=MagicMock(value="network"),
            confidence=0.85
        ),
        completed_at=MagicMock(isoformat=lambda: "2024-01-01T12:00:00"),
        model_dump=lambda mode=None: {"test": "data"}
    )


class TestEvidenceList:
    def test_list_no_evidence_packs(self):
        """Test list command when no evidence packs exist."""
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = []
            
            result = runner.invoke(app, ["evidence", "list"])
            
            assert result.exit_code == 0
            assert "No evidence packs found" in result.output

    def test_list_with_evidence_packs(self, mock_evidence_pack):
        """Test list command with existing evidence packs."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = mock_evidence_pack
            
            result = runner.invoke(app, ["evidence", "list"])
            
            assert result.exit_code == 0
            assert "Evidence Packs" in result.output
            assert "test_pack" in result.output
            assert "network" in result.output
            assert "85%" in result.output

    def test_list_with_failed_pack_load(self):
        """Test list command when pack loading fails."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = None
            
            result = runner.invoke(app, ["evidence", "list"])
            
            assert result.exit_code == 0
            # Should not crash, just skip the failed pack

    @patch("beacon.config.get_settings")
    def test_list_uses_correct_evidence_dir(self, mock_settings):
        """Test that list command uses correct evidence directory from settings."""
        mock_settings.return_value.storage.evidence_dir = Path("/test/evidence")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = []
            
            runner.invoke(app, ["evidence", "list"])
            
            MockStore.assert_called_once_with(Path("/test/evidence"))


class TestEvidenceGet:
    def test_get_exact_run_id_match(self, mock_evidence_pack):
        """Test get command with exact run ID match."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = mock_evidence_pack
            
            result = runner.invoke(app, ["evidence", "get", str(run_id)])
            
            assert result.exit_code == 0
            mock_store.load.assert_called_once_with(run_id)

    def test_get_prefix_match(self, mock_evidence_pack):
        """Test get command with run ID prefix matching."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = mock_evidence_pack
            
            result = runner.invoke(app, ["evidence", "get", "12345678"])
            
            assert result.exit_code == 0
            mock_store.load.assert_called_once_with(run_id)

    def test_get_substring_match(self, mock_evidence_pack):
        """Test get command with substring matching when prefix fails."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = mock_evidence_pack
            
            result = runner.invoke(app, ["evidence", "get", "5678"])
            
            assert result.exit_code == 0
            mock_store.load.assert_called_once_with(run_id)

    def test_get_no_match(self):
        """Test get command when no run ID matches."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            
            result = runner.invoke(app, ["evidence", "get", "nonexistent"])
            
            assert result.exit_code == 1
            assert "No evidence pack matching" in result.output

    def test_get_ambiguous_match(self, mock_evidence_pack):
        """Test get command when multiple run IDs match prefix."""
        run_id1 = UUID("12345678-1234-5678-9012-123456789012")
        run_id2 = UUID("12345678-5678-1234-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id1, run_id2]
            
            result = runner.invoke(app, ["evidence", "get", "12345678"])
            
            assert result.exit_code == 1
            assert "Ambiguous run ID prefix" in result.output
            assert "matches 2 packs" in result.output

    def test_get_pack_load_failure(self):
        """Test get command when pack loading fails."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = None
            
            result = runner.invoke(app, ["evidence", "get", str(run_id)])
            
            assert result.exit_code == 1
            assert "Failed to load evidence pack" in result.output

    def test_get_with_output_file(self, mock_evidence_pack, tmp_path):
        """Test get command with output file option."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        output_file = tmp_path / "evidence.json"
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = mock_evidence_pack
            
            result = runner.invoke(app, ["evidence", "get", str(run_id), "--output", str(output_file)])
            
            assert result.exit_code == 0
            assert output_file.exists()
            assert "Evidence pack saved to" in result.output
            
            # Verify file content
            with open(output_file) as f:
                data = json.load(f)
            assert data == {"test": "data"}

    def test_get_output_to_stdout(self, mock_evidence_pack):
        """Test get command outputs JSON to stdout when no output file specified."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = mock_evidence_pack
            
            result = runner.invoke(app, ["evidence", "get", str(run_id)])
            
            assert result.exit_code == 0
            # Should contain JSON output
            assert '"test"' in result.output
            assert '"data"' in result.output

    @patch("beacon.config.get_settings")
    def test_get_uses_correct_evidence_dir(self, mock_settings, mock_evidence_pack):
        """Test that get command uses correct evidence directory from settings."""
        mock_settings.return_value.storage.evidence_dir = Path("/test/evidence")
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            mock_store = MockStore.return_value
            mock_store.list_runs.return_value = [run_id]
            mock_store.load.return_value = mock_evidence_pack
            
            runner.invoke(app, ["evidence", "get", str(run_id)])
            
            MockStore.assert_called_once_with(Path("/test/evidence"))


class TestEvidenceCommandErrors:
    def test_missing_run_id_argument(self):
        """Test get command without run ID argument."""
        result = runner.invoke(app, ["evidence", "get"])
        
        assert result.exit_code != 0
        # Typer should show usage/help

    def test_invalid_command(self):
        """Test invalid evidence subcommand."""
        result = runner.invoke(app, ["evidence", "invalid"])
        
        assert result.exit_code != 0

    def test_evidence_store_exception(self):
        """Test handling of evidence store exceptions."""
        with patch("beacon.storage.evidence_store.EvidenceStore") as MockStore:
            MockStore.side_effect = Exception("Storage error")
            
            result = runner.invoke(app, ["evidence", "list"])
            
            assert result.exit_code != 0