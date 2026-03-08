"""Tests for evidence API routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from beacon.api.app import create_app
from beacon.models.evidence import EvidencePack


class TestEvidenceRoutes:
    """Test evidence API routes."""

    @pytest.fixture
    def mock_evidence_store(self):
        """Mock evidence store."""
        store = MagicMock()
        return store

    @pytest.fixture
    def client(self, mock_evidence_store):
        """Create test client with mocked dependencies."""
        app = create_app()
        with patch(
            "beacon.api.routes.evidence.get_evidence_store", return_value=mock_evidence_store
        ):
            yield TestClient(app)

    def test_list_evidence_empty(self, client, mock_evidence_store):
        """Test listing evidence when no runs exist."""
        mock_evidence_store.list_runs.return_value = []

        response = client.get("/evidence/")

        assert response.status_code == 200
        assert response.json() == {"runs": []}
        mock_evidence_store.list_runs.assert_called_once()

    def test_list_evidence_with_runs(self, client, mock_evidence_store):
        """Test listing evidence with existing runs."""
        run_ids = [uuid4(), uuid4()]
        mock_evidence_store.list_runs.return_value = run_ids

        response = client.get("/evidence/")

        assert response.status_code == 200
        data = response.json()
        assert "runs" in data
        assert len(data["runs"]) == 2
        assert all(isinstance(run_id, str) for run_id in data["runs"])
        mock_evidence_store.list_runs.assert_called_once()

    def test_get_evidence_success(self, client, mock_evidence_store):
        """Test retrieving evidence pack successfully."""
        run_id = uuid4()
        mock_pack = MagicMock(spec=EvidencePack)
        mock_pack.model_dump.return_value = {
            "run_id": str(run_id),
            "pack_name": "test_pack",
            "envelopes": [],
        }
        mock_evidence_store.load.return_value = mock_pack

        response = client.get(f"/evidence/{run_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == str(run_id)
        assert data["pack_name"] == "test_pack"
        mock_evidence_store.load.assert_called_once_with(run_id)
        mock_pack.model_dump.assert_called_once_with(mode="json")

    def test_get_evidence_invalid_uuid(self, client, mock_evidence_store):
        """Test retrieving evidence with invalid UUID format."""
        response = client.get("/evidence/invalid-uuid")

        assert response.status_code == 400
        assert "Invalid run_id format" in response.json()["detail"]
        mock_evidence_store.load.assert_not_called()

    def test_get_evidence_not_found(self, client, mock_evidence_store):
        """Test retrieving non-existent evidence pack."""
        run_id = uuid4()
        mock_evidence_store.load.return_value = None

        response = client.get(f"/evidence/{run_id}")

        assert response.status_code == 404
        assert f"Evidence pack '{run_id}' not found" in response.json()["detail"]
        mock_evidence_store.load.assert_called_once_with(run_id)

    def test_delete_evidence_success(self, client, mock_evidence_store):
        """Test deleting evidence pack successfully."""
        run_id = uuid4()
        mock_evidence_store.delete.return_value = True

        response = client.delete(f"/evidence/{run_id}")

        assert response.status_code == 200
        assert response.json() == {"deleted": str(run_id)}
        mock_evidence_store.delete.assert_called_once_with(run_id)

    def test_delete_evidence_invalid_uuid(self, client, mock_evidence_store):
        """Test deleting evidence with invalid UUID format."""
        response = client.delete("/evidence/invalid-uuid")

        assert response.status_code == 400
        assert "Invalid run_id format" in response.json()["detail"]
        mock_evidence_store.delete.assert_not_called()

    def test_delete_evidence_not_found(self, client, mock_evidence_store):
        """Test deleting non-existent evidence pack."""
        run_id = uuid4()
        mock_evidence_store.delete.return_value = False

        response = client.delete(f"/evidence/{run_id}")

        assert response.status_code == 404
        assert f"Evidence pack '{run_id}' not found" in response.json()["detail"]
        mock_evidence_store.delete.assert_called_once_with(run_id)

    def test_uuid_edge_cases(self, client, mock_evidence_store):
        """Test UUID parsing edge cases."""
        # Test empty string
        response = client.get("/evidence/")
        assert response.status_code == 200  # This hits list endpoint

        # Test malformed UUIDs
        malformed_uuids = [
            "123",
            "not-a-uuid",
            "12345678-1234-1234-1234-12345678901",  # Too short
            "12345678-1234-1234-1234-1234567890123",  # Too long
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",  # Invalid chars
        ]

        for bad_uuid in malformed_uuids:
            response = client.get(f"/evidence/{bad_uuid}")
            assert response.status_code == 400
            assert "Invalid run_id format" in response.json()["detail"]

            response = client.delete(f"/evidence/{bad_uuid}")
            assert response.status_code == 400
            assert "Invalid run_id format" in response.json()["detail"]
