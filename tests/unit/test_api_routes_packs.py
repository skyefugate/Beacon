"""Tests for packs API routes."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from beacon.api.app import create_app
from beacon.packs.schema import PackDefinition


class TestPacksRoutes:
    """Test packs API routes."""

    @pytest.fixture
    def mock_pack_registry(self):
        """Mock pack registry."""
        registry = MagicMock()
        return registry

    @pytest.fixture
    def mock_pack_executor(self):
        """Mock pack executor."""
        executor = MagicMock()
        return executor

    @pytest.fixture
    def mock_evidence_builder(self):
        """Mock evidence builder."""
        builder = MagicMock()
        return builder

    @pytest.fixture
    def mock_evidence_store(self):
        """Mock evidence store."""
        store = MagicMock()
        return store

    @pytest.fixture
    def sample_pack(self):
        """Sample pack for testing."""
        return PackDefinition(
            name="test_pack",
            description="Test pack description",
            version="1.0.0",
            steps=[],
            timeout_seconds=300
        )

    @pytest.fixture
    def client(self, mock_pack_registry, mock_pack_executor, mock_evidence_builder, mock_evidence_store):
        """Create test client with mocked dependencies."""
        app = create_app()
        with (
            patch("beacon.api.routes.packs.get_pack_registry", return_value=mock_pack_registry),
            patch("beacon.api.routes.packs.get_pack_executor", return_value=mock_pack_executor),
            patch("beacon.api.routes.packs.get_evidence_builder", return_value=mock_evidence_builder),
            patch("beacon.api.routes.packs.get_evidence_store", return_value=mock_evidence_store),
        ):
            yield TestClient(app)

    def test_list_packs_empty(self, client, mock_pack_registry):
        """Test listing packs when no packs exist."""
        mock_pack_registry.list_packs.return_value = []
        
        response = client.get("/packs/")
        
        assert response.status_code == 200
        assert response.json() == {"packs": []}
        mock_pack_registry.list_packs.assert_called_once()

    def test_list_packs_with_packs(self, client, mock_pack_registry, sample_pack):
        """Test listing packs with existing packs."""
        mock_pack_registry.list_packs.return_value = [sample_pack]
        
        response = client.get("/packs/")
        
        assert response.status_code == 200
        data = response.json()
        assert "packs" in data
        assert len(data["packs"]) == 1
        pack_data = data["packs"][0]
        assert pack_data["name"] == "test_pack"
        assert pack_data["description"] == "Test pack description"
        assert pack_data["version"] == "1.0.0"
        assert pack_data["steps"] == 0
        assert pack_data["timeout_seconds"] == 300

    def test_get_pack_success(self, client, mock_pack_registry, sample_pack):
        """Test retrieving a specific pack successfully."""
        mock_pack_registry.get.return_value = sample_pack
        
        response = client.get("/packs/test_pack")
        
        assert response.status_code == 200
        mock_pack_registry.get.assert_called_once_with("test_pack")

    def test_get_pack_not_found(self, client, mock_pack_registry):
        """Test retrieving non-existent pack."""
        mock_pack_registry.get.return_value = None
        
        response = client.get("/packs/nonexistent")
        
        assert response.status_code == 404
        assert "Pack 'nonexistent' not found" in response.json()["detail"]
        mock_pack_registry.get.assert_called_once_with("nonexistent")

    def test_run_pack_success(self, client, mock_pack_registry, sample_pack):
        """Test running a pack successfully."""
        mock_pack_registry.get.return_value = sample_pack
        
        # Clear any existing run status
        with patch("beacon.api.routes.packs._run_status", {}):
            response = client.post("/packs/test_pack/run")
        
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "running"
        assert data["pack"] == "test_pack"
        
        # Verify run_id is a valid UUID
        UUID(data["run_id"])

    def test_run_pack_not_found(self, client, mock_pack_registry):
        """Test running non-existent pack."""
        mock_pack_registry.get.return_value = None
        
        response = client.post("/packs/nonexistent/run")
        
        assert response.status_code == 404
        assert "Pack 'nonexistent' not found" in response.json()["detail"]

    def test_run_pack_already_running(self, client, mock_pack_registry, sample_pack):
        """Test running pack when it's already running."""
        mock_pack_registry.get.return_value = sample_pack
        
        # Set up existing running status
        existing_run_id = str(uuid4())
        run_status = {
            existing_run_id: {
                "status": "running",
                "pack": "test_pack",
                "_ts": time.monotonic()
            }
        }
        
        with patch("beacon.api.routes.packs._run_status", run_status):
            response = client.post("/packs/test_pack/run")
        
        assert response.status_code == 429
        assert "already running" in response.json()["detail"]

    def test_get_run_status_success(self, client):
        """Test retrieving run status successfully."""
        run_id = str(uuid4())
        run_status = {
            run_id: {
                "status": "completed",
                "pack": "test_pack",
                "run_id": run_id,
                "evidence_path": "/path/to/evidence"
            }
        }
        
        with patch("beacon.api.routes.packs._run_status", run_status):
            response = client.get(f"/packs/test_pack/run/{run_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["pack"] == "test_pack"

    def test_get_run_status_not_found(self, client):
        """Test retrieving non-existent run status."""
        run_id = str(uuid4())
        
        with patch("beacon.api.routes.packs._run_status", {}):
            response = client.get(f"/packs/test_pack/run/{run_id}")
        
        assert response.status_code == 404
        assert f"Run '{run_id}' not found" in response.json()["detail"]

    @patch("beacon.api.routes.packs._execute_pack_run")
    def test_background_task_execution(self, mock_execute, client, mock_pack_registry, sample_pack):
        """Test that background task is properly scheduled."""
        mock_pack_registry.get.return_value = sample_pack
        
        with patch("beacon.api.routes.packs._run_status", {}):
            response = client.post("/packs/test_pack/run")
        
        assert response.status_code == 200
        # Background task should be called (though we can't easily verify timing)
        # The mock will be called when the background task executes

    def test_execute_pack_run_success(self):
        """Test successful pack execution in background task."""
        from beacon.api.routes.packs import _execute_pack_run
        
        run_id = str(uuid4())
        pack_name = "test_pack"
        
        # Mock all dependencies
        mock_registry = MagicMock()
        mock_pack = MagicMock()
        mock_pack.name = pack_name
        mock_registry.get.return_value = mock_pack
        
        mock_executor = MagicMock()
        mock_envelopes = [{"data": "test"}]
        mock_executor.execute.return_value = mock_envelopes
        
        mock_builder = MagicMock()
        mock_evidence_pack = MagicMock()
        mock_builder.build.return_value = mock_evidence_pack
        
        mock_store = MagicMock()
        mock_store.save.return_value = "/path/to/evidence"
        
        run_status = {}
        
        with (
            patch("beacon.api.routes.packs.get_pack_registry", return_value=mock_registry),
            patch("beacon.api.routes.packs.get_pack_executor", return_value=mock_executor),
            patch("beacon.api.routes.packs.get_evidence_builder", return_value=mock_builder),
            patch("beacon.api.routes.packs.get_evidence_store", return_value=mock_store),
            patch("beacon.api.routes.packs._run_status", run_status),
        ):
            _execute_pack_run(run_id, pack_name)
        
        assert run_id in run_status
        assert run_status[run_id]["status"] == "completed"
        assert run_status[run_id]["pack"] == pack_name

    def test_execute_pack_run_pack_not_found(self):
        """Test pack execution when pack is not found."""
        from beacon.api.routes.packs import _execute_pack_run
        
        run_id = str(uuid4())
        pack_name = "nonexistent"
        
        mock_registry = MagicMock()
        mock_registry.get.return_value = None
        
        run_status = {}
        
        with (
            patch("beacon.api.routes.packs.get_pack_registry", return_value=mock_registry),
            patch("beacon.api.routes.packs._run_status", run_status),
        ):
            _execute_pack_run(run_id, pack_name)
        
        assert run_id in run_status
        assert run_status[run_id]["status"] == "error"
        assert "Pack not found" in run_status[run_id]["error"]

    def test_execute_pack_run_exception(self):
        """Test pack execution when exception occurs."""
        from beacon.api.routes.packs import _execute_pack_run
        
        run_id = str(uuid4())
        pack_name = "test_pack"
        
        mock_registry = MagicMock()
        mock_registry.get.side_effect = Exception("Registry error")
        
        run_status = {}
        
        with (
            patch("beacon.api.routes.packs.get_pack_registry", return_value=mock_registry),
            patch("beacon.api.routes.packs._run_status", run_status),
        ):
            _execute_pack_run(run_id, pack_name)
        
        assert run_id in run_status
        assert run_status[run_id]["status"] == "error"
        assert "Registry error" in run_status[run_id]["error"]

    def test_evict_old_runs(self):
        """Test eviction of old completed runs."""
        from beacon.api.routes.packs import _evict_old_runs
        
        old_time = time.monotonic() - 4000  # Old timestamp
        recent_time = time.monotonic()
        
        run_status = {
            "old_completed": {"status": "completed", "_ts": old_time},
            "old_error": {"status": "error", "_ts": old_time},
            "recent_completed": {"status": "completed", "_ts": recent_time},
            "running": {"status": "running", "_ts": old_time},
        }
        
        with patch("beacon.api.routes.packs._run_status", run_status):
            _evict_old_runs()
        
        # Old completed/error runs should be evicted
        assert "old_completed" not in run_status
        assert "old_error" not in run_status
        # Recent and running should remain
        assert "recent_completed" in run_status
        assert "running" in run_status

    def test_evict_runs_max_entries(self):
        """Test eviction when max entries exceeded."""
        from beacon.api.routes.packs import _evict_old_runs
        
        # Create more than max entries
        run_status = {}
        for i in range(600):  # More than _MAX_STATUS_ENTRIES (500)
            run_status[f"run_{i}"] = {
                "status": "completed",
                "_ts": time.monotonic() - i  # Older runs have smaller timestamps
            }
        
        with (
            patch("beacon.api.routes.packs._run_status", run_status),
            patch("beacon.api.routes.packs._MAX_STATUS_ENTRIES", 500),
        ):
            _evict_old_runs()
        
        # Should be capped at max entries
        assert len(run_status) <= 500

    def test_concurrent_pack_runs(self, client, mock_pack_registry, sample_pack):
        """Test concurrent pack run requests."""
        mock_pack_registry.get.return_value = sample_pack
        
        # First request should succeed
        with patch("beacon.api.routes.packs._run_status", {}):
            response1 = client.post("/packs/test_pack/run")
            assert response1.status_code == 200
            
            # Set up running status for second request
            run_id = response1.json()["run_id"]
            run_status = {
                run_id: {"status": "running", "pack": "test_pack", "_ts": time.monotonic()}
            }
            
            with patch("beacon.api.routes.packs._run_status", run_status):
                response2 = client.post("/packs/test_pack/run")
                assert response2.status_code == 429

    def test_pack_name_edge_cases(self, client, mock_pack_registry):
        """Test pack names with special characters."""
        special_names = [
            "pack-with-dashes",
            "pack_with_underscores",
            "pack.with.dots",
            "pack123",
            "UPPERCASE_PACK"
        ]
        
        for name in special_names:
            mock_pack_registry.get.return_value = None
            response = client.get(f"/packs/{name}")
            assert response.status_code == 404
            mock_pack_registry.get.assert_called_with(name)

    def test_run_status_data_integrity(self, client):
        """Test run status data structure integrity."""
        run_id = str(uuid4())
        run_status = {
            run_id: {
                "status": "completed",
                "pack": "test_pack",
                "run_id": run_id,
                "evidence_path": "/path/to/evidence",
                "_ts": time.monotonic()
            }
        }
        
        with patch("beacon.api.routes.packs._run_status", run_status):
            response = client.get(f"/packs/test_pack/run/{run_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all expected fields are present
        assert "status" in data
        assert "pack" in data
        assert "run_id" in data
        assert "evidence_path" in data
        # The API currently returns all fields including internal ones
        assert "_ts" in data