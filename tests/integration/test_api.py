"""Integration tests for the FastAPI application."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from beacon.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with isolated storage directories."""
    monkeypatch.setenv("BEACON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BEACON_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("BEACON_EVIDENCE_DIR", str(tmp_path / "evidence"))

    # Clear lru_cache'd deps
    from beacon.api import deps

    for fn in [
        deps.get_beacon_settings,
        deps.get_plugin_registry,
        deps.get_pack_registry,
        deps.get_artifact_store,
        deps.get_evidence_store,
        deps.get_fault_engine,
        deps.get_evidence_builder,
    ]:
        fn.cache_clear()

    from beacon.config import reset_settings

    reset_settings()

    app = create_app()
    with TestClient(app) as tc:
        yield tc

    # Cleanup
    reset_settings()
    for fn in [
        deps.get_beacon_settings,
        deps.get_plugin_registry,
        deps.get_pack_registry,
        deps.get_artifact_store,
        deps.get_evidence_store,
        deps.get_fault_engine,
        deps.get_evidence_builder,
    ]:
        fn.cache_clear()


class TestHealthRoutes:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_ready(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ready", "degraded")


class TestPackRoutes:
    def test_list_packs(self, client):
        resp = client.get("/packs/")
        assert resp.status_code == 200
        data = resp.json()
        assert "packs" in data

    def test_get_unknown_pack(self, client):
        resp = client.get("/packs/nonexistent")
        assert resp.status_code == 404


class TestEvidenceRoutes:
    def test_list_evidence(self, client):
        resp = client.get("/evidence/")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert data["runs"] == []

    def test_get_missing_evidence(self, client):
        resp = client.get("/evidence/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_invalid_run_id(self, client):
        resp = client.get("/evidence/not-a-uuid")
        assert resp.status_code == 400


class TestMetricsRoutes:
    @patch("beacon.api.routes.metrics.get_influx_storage", return_value=None)
    def test_query_without_influx(self, _mock, client):
        resp = client.post("/metrics/query", json={"query": 'from(bucket: "test")'})
        assert resp.status_code == 503
