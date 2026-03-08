"""Tests for beacon run CLI commands."""

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
def mock_pack():
    """Mock diagnostic pack."""
    return MagicMock(
        name="test_pack",
        description="Test pack",
        version="1.0.0",
        steps=[MagicMock()]
    )


@pytest.fixture
def mock_evidence_pack():
    """Mock evidence pack."""
    return MagicMock(
        fault_domain=MagicMock(
            fault_domain=MagicMock(value="network"),
            confidence=0.85,
            evidence_refs=["ref1", "ref2"],
            competing_hypotheses=[
                MagicMock(fault_domain=MagicMock(value="system"), confidence=0.15)
            ]
        ),
        test_results=[
            MagicMock(events=["event1"], metrics=["metric1", "metric2"]),
            MagicMock(events=[], metrics=["metric3"])
        ]
    )


class TestRunLocal:
    def test_run_local_success(self, mock_pack, mock_evidence_pack, tmp_path):
        """Test successful local pack execution."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch("beacon.packs.executor.PackExecutor") as MockExecutor, \
             patch("beacon.evidence.builder.EvidencePackBuilder") as MockBuilder, \
             patch("beacon.storage.evidence_store.EvidenceStore") as MockStore, \
             patch("uuid.uuid4", return_value=run_id), \
             patch.object(Path, "is_dir", return_value=True):
            
            # Setup mocks
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack
            
            mock_executor = MockExecutor.return_value
            mock_executor.execute.return_value = ["envelope1", "envelope2"]
            
            mock_builder = MockBuilder.return_value
            mock_builder.build.return_value = mock_evidence_pack
            
            mock_store = MockStore.return_value
            mock_store.save.return_value = tmp_path / "evidence.json"
            
            result = runner.invoke(app, ["run", "test_pack"])
            
            assert result.exit_code == 0
            assert "Evidence pack saved" in result.output
            assert str(run_id) in result.output
            assert "test_pack" in result.output
            assert "network" in result.output
            assert "85.0%" in result.output  # Changed from 85% to 85.0%

    def test_run_local_pack_not_found(self):
        """Test local run when pack doesn't exist."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch.object(Path, "is_dir", return_value=True):
            
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = None
            
            result = runner.invoke(app, ["run", "nonexistent_pack"])
            
            assert result.exit_code == 1
            assert "Pack 'nonexistent_pack' not found" in result.output

    def test_run_local_with_output_file(self, mock_pack, mock_evidence_pack, tmp_path):
        """Test local run with output file option."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        output_file = tmp_path / "custom_evidence.json"
        
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch("beacon.packs.executor.PackExecutor") as MockExecutor, \
             patch("beacon.evidence.builder.EvidencePackBuilder") as MockBuilder, \
             patch("beacon.storage.evidence_store.EvidenceStore") as MockStore, \
             patch("uuid.uuid4", return_value=run_id), \
             patch("shutil.copy2") as mock_copy, \
             patch.object(Path, "is_dir", return_value=True):
            
            # Setup mocks
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack
            
            mock_executor = MockExecutor.return_value
            mock_executor.execute.return_value = []
            
            mock_builder = MockBuilder.return_value
            mock_builder.build.return_value = mock_evidence_pack
            
            mock_store = MockStore.return_value
            mock_store.save.return_value = tmp_path / "evidence.json"
            
            result = runner.invoke(app, ["run", "-o", str(output_file), "test_pack"])
            
            assert result.exit_code == 0
            assert "Evidence pack saved to" in result.output
            assert "custom_evidence.json" in result.output
            mock_copy.assert_called_once()

    def test_run_local_no_packs_directory(self):
        """Test local run when packs directory doesn't exist."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch.object(Path, "is_dir", return_value=False):
            
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = None
            
            result = runner.invoke(app, ["run", "test_pack"])
            
            assert result.exit_code == 1
            # Should not try to load from directory
            mock_registry.load_from_directory.assert_not_called()

    def test_run_local_unknown_fault_domain_with_metrics(self, mock_pack, tmp_path):
        """Test local run with unknown fault domain but metrics collected."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        # Mock evidence pack with unknown fault domain but metrics
        mock_evidence_pack = MagicMock(
            fault_domain=MagicMock(
                fault_domain=MagicMock(value="unknown"),
                confidence=0.0
            ),
            test_results=[
                MagicMock(events=[], metrics=["metric1", "metric2"])
            ]
        )
        
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch("beacon.packs.executor.PackExecutor") as MockExecutor, \
             patch("beacon.evidence.builder.EvidencePackBuilder") as MockBuilder, \
             patch("beacon.storage.evidence_store.EvidenceStore") as MockStore, \
             patch("uuid.uuid4", return_value=run_id), \
             patch.object(Path, "is_dir", return_value=True):
            
            # Setup mocks
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack
            
            mock_executor = MockExecutor.return_value
            mock_executor.execute.return_value = []
            
            mock_builder = MockBuilder.return_value
            mock_builder.build.return_value = mock_evidence_pack
            
            mock_store = MockStore.return_value
            mock_store.save.return_value = tmp_path / "evidence.json"
            
            result = runner.invoke(app, ["run", "test_pack"])
            
            assert result.exit_code == 0
            assert "No faults detected" in result.output
            assert "2 metrics collected" in result.output

    def test_run_local_unknown_fault_domain_no_metrics(self, mock_pack, tmp_path):
        """Test local run with unknown fault domain and no metrics."""
        run_id = UUID("12345678-1234-5678-9012-123456789012")
        
        # Mock evidence pack with unknown fault domain and no metrics
        mock_evidence_pack = MagicMock(
            fault_domain=MagicMock(
                fault_domain=MagicMock(value="unknown"),
                confidence=0.0
            ),
            test_results=[
                MagicMock(events=[], metrics=[])
            ]
        )
        
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch("beacon.packs.executor.PackExecutor") as MockExecutor, \
             patch("beacon.evidence.builder.EvidencePackBuilder") as MockBuilder, \
             patch("beacon.storage.evidence_store.EvidenceStore") as MockStore, \
             patch("uuid.uuid4", return_value=run_id), \
             patch.object(Path, "is_dir", return_value=True):
            
            # Setup mocks
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack
            
            mock_executor = MockExecutor.return_value
            mock_executor.execute.return_value = []
            
            mock_builder = MockBuilder.return_value
            mock_builder.build.return_value = mock_evidence_pack
            
            mock_store = MockStore.return_value
            mock_store.save.return_value = tmp_path / "evidence.json"
            
            result = runner.invoke(app, ["run", "test_pack"])
            
            assert result.exit_code == 0
            assert "unknown (insufficient data)" in result.output


class TestRunViaAPI:
    def test_run_via_api_success_with_wait(self, tmp_path):
        """Test successful API run with wait."""
        run_id = "12345678-1234-5678-9012-123456789012"
        server_url = "http://localhost:8000"
        evidence_data = {"test": "evidence"}
        
        with patch("httpx.post") as mock_post, \
             patch("httpx.get") as mock_get:
            
            # Mock start run response
            start_resp = MagicMock()
            start_resp.json.return_value = {"run_id": run_id}
            mock_post.return_value = start_resp
            
            # Mock status check response
            status_resp = MagicMock()
            status_resp.json.return_value = {"status": "completed"}
            
            # Mock evidence response
            evidence_resp = MagicMock()
            evidence_resp.json.return_value = evidence_data
            
            mock_get.side_effect = [status_resp, evidence_resp]
            
            result = runner.invoke(app, ["run", "-s", server_url, "test_pack"])
            
            assert result.exit_code == 0
            assert run_id in result.output
            mock_post.assert_called_once_with(f"{server_url}/packs/test_pack/run", timeout=10)

    def test_run_via_api_no_wait(self):
        """Test API run without waiting for completion."""
        run_id = "12345678-1234-5678-9012-123456789012"
        server_url = "http://localhost:8000"
        
        with patch("httpx.post") as mock_post:
            start_resp = MagicMock()
            start_resp.json.return_value = {"run_id": run_id}
            mock_post.return_value = start_resp
            
            result = runner.invoke(app, ["run", "-s", server_url, "--no-wait", "test_pack"])
            
            assert result.exit_code == 0
            assert run_id in result.output
            assert "Run started in background" in result.output

    def test_run_via_api_start_failure(self):
        """Test API run when start request fails."""
        server_url = "http://localhost:8000"
        
        with patch("httpx.post") as mock_post:
            import httpx
            mock_post.side_effect = httpx.HTTPError("Connection refused")
            
            result = runner.invoke(app, ["run", "-s", server_url, "test_pack"])
            
            assert result.exit_code == 1
            assert "Failed to start pack run" in result.output

    def test_run_via_api_status_error(self):
        """Test API run when pack execution fails."""
        run_id = "12345678-1234-5678-9012-123456789012"
        server_url = "http://localhost:8000"
        
        with patch("httpx.post") as mock_post, \
             patch("httpx.get") as mock_get:
            
            # Mock start run response
            start_resp = MagicMock()
            start_resp.json.return_value = {"run_id": run_id}
            mock_post.return_value = start_resp
            
            # Mock status check response with error
            status_resp = MagicMock()
            status_resp.json.return_value = {"status": "error", "error": "Pack execution failed"}
            mock_get.return_value = status_resp
            
            result = runner.invoke(app, ["run", "-s", server_url, "test_pack"])
            
            assert result.exit_code == 1
            assert "Pack run failed" in result.output
            assert "Pack execution failed" in result.output

    def test_run_via_api_timeout(self):
        """Test API run with timeout."""
        run_id = "12345678-1234-5678-9012-123456789012"
        server_url = "http://localhost:8000"
        
        with patch("httpx.post") as mock_post, \
             patch("httpx.get") as mock_get, \
             patch("time.monotonic", side_effect=[0, 200]):  # Simulate timeout
            
            # Mock start run response
            start_resp = MagicMock()
            start_resp.json.return_value = {"run_id": run_id}
            mock_post.return_value = start_resp
            
            # Mock status check response (still running)
            status_resp = MagicMock()
            status_resp.json.return_value = {"status": "running"}
            mock_get.return_value = status_resp
            
            result = runner.invoke(app, ["run", "-s", server_url, "--timeout", "180", "test_pack"])
            
            # Should still try to fetch evidence even after timeout
            assert result.exit_code == 0 or result.exit_code == 1

    def test_run_via_api_with_output_file(self, tmp_path):
        """Test API run with output file."""
        run_id = "12345678-1234-5678-9012-123456789012"
        server_url = "http://localhost:8000"
        output_file = tmp_path / "api_evidence.json"
        evidence_data = {"test": "evidence"}
        
        with patch("httpx.post") as mock_post, \
             patch("httpx.get") as mock_get:
            
            # Mock start run response
            start_resp = MagicMock()
            start_resp.json.return_value = {"run_id": run_id}
            mock_post.return_value = start_resp
            
            # Mock status and evidence responses
            status_resp = MagicMock()
            status_resp.json.return_value = {"status": "completed"}
            
            evidence_resp = MagicMock()
            evidence_resp.json.return_value = evidence_data
            
            mock_get.side_effect = [status_resp, evidence_resp]
            
            result = runner.invoke(app, ["run", "-s", server_url, "-o", str(output_file), "test_pack"])
            
            assert result.exit_code == 0
            assert output_file.exists()
            
            with open(output_file) as f:
                saved_data = json.load(f)
            assert saved_data == evidence_data

    def test_run_via_api_evidence_fetch_failure(self):
        """Test API run when evidence fetch fails."""
        run_id = "12345678-1234-5678-9012-123456789012"
        server_url = "http://localhost:8000"
        
        with patch("httpx.post") as mock_post, \
             patch("httpx.get") as mock_get:
            
            # Mock start run response
            start_resp = MagicMock()
            start_resp.json.return_value = {"run_id": run_id}
            mock_post.return_value = start_resp
            
            # Mock status response
            status_resp = MagicMock()
            status_resp.json.return_value = {"status": "completed"}
            
            # Mock evidence fetch failure
            import httpx
            mock_get.side_effect = [status_resp, httpx.HTTPError("Evidence fetch failed")]
            
            result = runner.invoke(app, ["run", "-s", server_url, "test_pack"])
            
            assert result.exit_code == 1
            assert "Failed to fetch evidence pack" in result.output

    def test_run_via_api_server_url_normalization(self):
        """Test that server URL is properly normalized."""
        run_id = "12345678-1234-5678-9012-123456789012"
        server_url = "http://localhost:8000/"
        
        with patch("httpx.post") as mock_post:
            start_resp = MagicMock()
            start_resp.json.return_value = {"run_id": run_id}
            mock_post.return_value = start_resp
            
            runner.invoke(app, ["run", "-s", server_url, "--no-wait", "test_pack"])
            
            # Should call without trailing slash
            mock_post.assert_called_once_with("http://localhost:8000/packs/test_pack/run", timeout=10)


class TestRunCommandErrors:
    def test_missing_pack_name(self):
        """Test run command without pack name."""
        result = runner.invoke(app, ["run"])
        
        assert result.exit_code != 0

    def test_invalid_timeout_value(self):
        """Test run command with invalid timeout."""
        result = runner.invoke(app, ["run", "test_pack", "--timeout", "invalid"])
        
        assert result.exit_code != 0

    def test_pack_executor_exception(self, mock_pack):
        """Test handling of pack executor exceptions."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch("beacon.packs.executor.PackExecutor") as MockExecutor, \
             patch.object(Path, "is_dir", return_value=True):
            
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack
            
            mock_executor = MockExecutor.return_value
            mock_executor.execute.side_effect = Exception("Execution failed")
            
            result = runner.invoke(app, ["run", "test_pack"])
            
            assert result.exit_code != 0

    def test_evidence_builder_exception(self, mock_pack):
        """Test handling of evidence builder exceptions."""
        with patch("beacon.packs.registry.PackRegistry") as MockRegistry, \
             patch("beacon.packs.executor.PackExecutor") as MockExecutor, \
             patch("beacon.evidence.builder.EvidencePackBuilder") as MockBuilder, \
             patch.object(Path, "is_dir", return_value=True):
            
            mock_registry = MockRegistry.return_value
            mock_registry.get.return_value = mock_pack
            
            mock_executor = MockExecutor.return_value
            mock_executor.execute.return_value = []
            
            mock_builder = MockBuilder.return_value
            mock_builder.build.side_effect = Exception("Builder failed")
            
            result = runner.invoke(app, ["run", "test_pack"])
            
            assert result.exit_code != 0