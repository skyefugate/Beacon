"""Evidence pack JSON persistence.

Stores and retrieves EvidencePack objects as JSON files,
keyed by run_id for easy lookup.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

import orjson

from beacon.models.evidence import EvidencePack

logger = logging.getLogger(__name__)


class EvidenceStore:
    """File-based evidence pack storage."""

    def __init__(self, evidence_dir: Path) -> None:
        self._dir = evidence_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, run_id: UUID) -> Path:
        return self._dir / f"{run_id}.json"

    def save(self, pack: EvidencePack) -> Path:
        """Serialize and save an EvidencePack as JSON."""
        path = self._path_for(pack.run_id)
        data = pack.model_dump(mode="json")
        raw = orjson.dumps(data, option=orjson.OPT_INDENT_2)
        path.write_bytes(raw)
        logger.info("Saved evidence pack %s → %s", pack.run_id, path)
        return path

    def load(self, run_id: UUID) -> EvidencePack | None:
        """Load an EvidencePack by run_id."""
        path = self._path_for(run_id)
        if not path.exists():
            return None
        data = orjson.loads(path.read_bytes())
        return EvidencePack.model_validate(data)

    def list_runs(self) -> list[UUID]:
        """List all stored run IDs, sorted by modification time (newest first)."""
        paths = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        results: list[UUID] = []
        for p in paths:
            try:
                results.append(UUID(p.stem))
            except ValueError:
                logger.warning("Skipping non-UUID file: %s", p.name)
        return results

    def delete(self, run_id: UUID) -> bool:
        """Delete an evidence pack by run_id."""
        path = self._path_for(run_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, run_id: UUID) -> bool:
        """Check if an evidence pack exists for the given run_id."""
        return self._path_for(run_id).exists()
