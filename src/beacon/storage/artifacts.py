"""Artifact file storage with SHA-256 integrity verification.

Artifacts (pcaps, logs, JSON dumps) are stored in a flat directory
structure keyed by SHA-256 hash to guarantee deduplication and integrity.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from beacon.models.envelope import Artifact

logger = logging.getLogger(__name__)

HASH_CHUNK_SIZE = 8192


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            sha256.update(chunk)
    return sha256.hexdigest()


class ArtifactStore:
    """File-based artifact storage with SHA-256 integrity."""

    def __init__(self, artifact_dir: Path) -> None:
        self._dir = artifact_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        source_path: Path,
        artifact_type: str,
        ttl_hours: int | None = None,
        metadata: dict | None = None,
    ) -> Artifact:
        """Store a file and return an Artifact model with its SHA-256 hash.

        The file is copied into the artifact directory. If a file with the
        same hash already exists, the existing copy is reused (dedup).
        """
        sha256 = compute_sha256(source_path)
        ext = source_path.suffix or f".{artifact_type}"
        dest_name = f"{sha256}{ext}"
        dest_path = self._dir / dest_name

        if not dest_path.exists():
            shutil.copy2(source_path, dest_path)
            logger.info("Stored artifact %s → %s", source_path.name, dest_name)
        else:
            logger.debug("Artifact %s already exists (dedup)", dest_name)

        return Artifact(
            artifact_type=artifact_type,
            ref=str(dest_path),
            sha256=sha256,
            ttl_hours=ttl_hours,
            metadata=metadata or {},
        )

    def retrieve(self, sha256: str) -> Path | None:
        """Look up an artifact by its SHA-256 hash."""
        for path in self._dir.iterdir():
            if path.stem == sha256:
                return path
        return None

    def verify(self, artifact: Artifact) -> bool:
        """Verify an artifact's integrity by recomputing its SHA-256."""
        path = Path(artifact.ref)
        if not path.exists():
            return False
        return compute_sha256(path) == artifact.sha256

    def list_artifacts(self) -> list[Path]:
        """List all stored artifact files."""
        return sorted(self._dir.iterdir())

    def delete(self, sha256: str) -> bool:
        """Delete an artifact by its SHA-256 hash."""
        path = self.retrieve(sha256)
        if path and path.exists():
            path.unlink()
            return True
        return False
