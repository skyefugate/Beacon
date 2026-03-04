"""Unit tests for storage layer — artifacts and evidence store.

InfluxDB integration tests are in tests/integration/test_influx_storage.py
since they require a running InfluxDB instance.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from beacon.storage.artifacts import ArtifactStore, compute_sha256
from beacon.storage.evidence_store import EvidenceStore


class TestComputeSha256:
    def test_consistent_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = compute_sha256(f)
        h2 = compute_sha256(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content A")
        f2.write_text("content B")
        assert compute_sha256(f1) != compute_sha256(f2)


class TestArtifactStore:
    @pytest.fixture
    def store(self, tmp_path):
        return ArtifactStore(tmp_path / "artifacts")

    @pytest.fixture
    def sample_file(self, tmp_path):
        f = tmp_path / "capture.pcap"
        f.write_bytes(b"\x00\x01\x02\x03" * 100)
        return f

    def test_store_creates_artifact(self, store, sample_file):
        artifact = store.store(sample_file, "pcap")
        assert artifact.artifact_type == "pcap"
        assert len(artifact.sha256) == 64
        assert Path(artifact.ref).exists()

    def test_store_deduplication(self, store, sample_file):
        a1 = store.store(sample_file, "pcap")
        a2 = store.store(sample_file, "pcap")
        assert a1.sha256 == a2.sha256
        assert len(store.list_artifacts()) == 1

    def test_store_with_metadata(self, store, sample_file):
        artifact = store.store(
            sample_file, "pcap", ttl_hours=48, metadata={"source": "wifi_collector"}
        )
        assert artifact.ttl_hours == 48
        assert artifact.metadata["source"] == "wifi_collector"

    def test_retrieve_by_hash(self, store, sample_file):
        artifact = store.store(sample_file, "pcap")
        found = store.retrieve(artifact.sha256)
        assert found is not None
        assert found.exists()

    def test_retrieve_missing(self, store):
        assert store.retrieve("nonexistent") is None

    def test_verify_integrity(self, store, sample_file):
        artifact = store.store(sample_file, "pcap")
        assert store.verify(artifact) is True

    def test_verify_corrupted(self, store, sample_file):
        artifact = store.store(sample_file, "pcap")
        # Corrupt the stored file
        Path(artifact.ref).write_bytes(b"corrupted")
        assert store.verify(artifact) is False

    def test_verify_missing_file(self, store, sample_file):
        artifact = store.store(sample_file, "pcap")
        Path(artifact.ref).unlink()
        assert store.verify(artifact) is False

    def test_delete(self, store, sample_file):
        artifact = store.store(sample_file, "pcap")
        assert store.delete(artifact.sha256) is True
        assert store.retrieve(artifact.sha256) is None

    def test_delete_missing(self, store):
        assert store.delete("nonexistent") is False

    def test_list_artifacts(self, store, tmp_path):
        for i in range(3):
            f = tmp_path / f"file_{i}.log"
            f.write_text(f"content {i}")
            store.store(f, "log")
        assert len(store.list_artifacts()) == 3


class TestEvidenceStore:
    @pytest.fixture
    def store(self, tmp_path):
        return EvidenceStore(tmp_path / "evidence")

    def test_save_and_load(self, store, sample_evidence_pack):
        path = store.save(sample_evidence_pack)
        assert path.exists()

        loaded = store.load(sample_evidence_pack.run_id)
        assert loaded is not None
        assert loaded.run_id == sample_evidence_pack.run_id
        assert loaded.pack_name == sample_evidence_pack.pack_name
        assert loaded.fault_domain.confidence == sample_evidence_pack.fault_domain.confidence

    def test_load_missing(self, store):
        assert store.load(uuid4()) is None

    def test_list_runs(self, store, sample_evidence_pack):
        store.save(sample_evidence_pack)
        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0] == sample_evidence_pack.run_id

    def test_exists(self, store, sample_evidence_pack):
        assert store.exists(sample_evidence_pack.run_id) is False
        store.save(sample_evidence_pack)
        assert store.exists(sample_evidence_pack.run_id) is True

    def test_delete(self, store, sample_evidence_pack):
        store.save(sample_evidence_pack)
        assert store.delete(sample_evidence_pack.run_id) is True
        assert store.exists(sample_evidence_pack.run_id) is False

    def test_delete_missing(self, store):
        assert store.delete(uuid4()) is False

    def test_roundtrip_preserves_structure(self, store, sample_evidence_pack):
        store.save(sample_evidence_pack)
        loaded = store.load(sample_evidence_pack.run_id)
        assert loaded is not None
        assert len(loaded.test_results) == len(sample_evidence_pack.test_results)
        assert len(loaded.artifact_manifest) == len(sample_evidence_pack.artifact_manifest)
        assert loaded.environment.hostname == sample_evidence_pack.environment.hostname
