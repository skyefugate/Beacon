"""JSONL file exporter — rotated log file output for telemetry metrics.

Writes one JSON object per line. Rotates at max_mb, keeps max_files.
"""

from __future__ import annotations

import logging
from pathlib import Path

import orjson

from beacon.models.envelope import Metric
from beacon.telemetry.export.base import BaseExporter

logger = logging.getLogger(__name__)


class FileExporter(BaseExporter):
    """JSONL file exporter with size-based rotation."""

    name = "file"

    def __init__(
        self,
        path: Path,
        max_mb: int = 10,
        max_files: int = 5,
    ) -> None:
        self._path = path
        self._max_bytes = max_mb * 1024 * 1024
        self._max_files = max_files

    async def export(self, metrics: list[Metric]) -> int:
        """Append metrics as JSONL to the output file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Check rotation
        if self._path.exists() and self._path.stat().st_size >= self._max_bytes:
            self._rotate()

        try:
            with open(self._path, "ab") as f:
                for metric in metrics:
                    line = orjson.dumps(metric.model_dump(mode="json"))
                    f.write(line + b"\n")
            return len(metrics)
        except OSError as e:
            logger.warning("File export failed: %s", e)
            return 0

    def _rotate(self) -> None:
        """Rotate files: .jsonl → .jsonl.1 → .jsonl.2 → ... → delete oldest."""
        # Delete the oldest
        oldest = Path(f"{self._path}.{self._max_files}")
        if oldest.exists():
            oldest.unlink()

        # Shift existing rotated files
        for i in range(self._max_files - 1, 0, -1):
            src = Path(f"{self._path}.{i}")
            dst = Path(f"{self._path}.{i + 1}")
            if src.exists():
                src.rename(dst)

        # Rotate current
        if self._path.exists():
            self._path.rename(Path(f"{self._path}.1"))

    async def close(self) -> None:
        pass  # No persistent handles to close
