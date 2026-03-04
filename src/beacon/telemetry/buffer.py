"""SQLiteBuffer — WAL-mode local storage for telemetry points.

Buffers metrics locally so the export pipeline can retry on InfluxDB
failures without losing data. Uses stdlib sqlite3 + asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from beacon.models.envelope import Metric

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement TEXT NOT NULL,
    fields TEXT NOT NULL,
    tags TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    exported INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_unexported
    ON telemetry_points (exported) WHERE exported = 0;

CREATE INDEX IF NOT EXISTS idx_created_at
    ON telemetry_points (created_at);
"""


class SQLiteBuffer:
    """WAL-mode SQLite buffer for telemetry metrics."""

    def __init__(self, path: Path, max_mb: int = 100, retention_days: int = 7) -> None:
        self._path = path
        self._max_mb = max_mb
        self._retention_days = retention_days
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        """Open the database and create schema."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def write_points(self, metrics: list[Metric]) -> None:
        """Buffer metrics to SQLite (async wrapper)."""
        await asyncio.to_thread(self._write_points_sync, metrics)

    def _write_points_sync(self, metrics: list[Metric]) -> None:
        assert self._conn is not None
        rows = [
            (
                m.measurement,
                json.dumps({k: v for k, v in m.fields.items()}),
                json.dumps(m.tags),
                m.timestamp.isoformat(),
            )
            for m in metrics
        ]
        self._conn.executemany(
            "INSERT INTO telemetry_points (measurement, fields, tags, timestamp) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    async def read_unexported(self, batch_size: int = 500) -> list[tuple[int, Metric]]:
        """Read a batch of unexported points. Returns (id, Metric) pairs."""
        return await asyncio.to_thread(self._read_unexported_sync, batch_size)

    def _read_unexported_sync(self, batch_size: int) -> list[tuple[int, Metric]]:
        assert self._conn is not None
        cursor = self._conn.execute(
            "SELECT id, measurement, fields, tags, timestamp "
            "FROM telemetry_points WHERE exported = 0 "
            "ORDER BY id LIMIT ?",
            (batch_size,),
        )
        results: list[tuple[int, Metric]] = []
        for row in cursor.fetchall():
            metric = Metric(
                measurement=row[1],
                fields=json.loads(row[2]),
                tags=json.loads(row[3]),
                timestamp=datetime.fromisoformat(row[4]),
            )
            results.append((row[0], metric))
        return results

    async def mark_exported(self, ids: list[int]) -> None:
        """Mark points as exported."""
        await asyncio.to_thread(self._mark_exported_sync, ids)

    def _mark_exported_sync(self, ids: list[int]) -> None:
        assert self._conn is not None
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        self._conn.execute(
            f"UPDATE telemetry_points SET exported = 1 WHERE id IN ({placeholders})",
            ids,
        )
        self._conn.commit()

    async def compact(self) -> int:
        """Remove old exported points and return count deleted."""
        return await asyncio.to_thread(self._compact_sync)

    def _compact_sync(self) -> int:
        assert self._conn is not None
        cursor = self._conn.execute(
            "DELETE FROM telemetry_points WHERE exported = 1 AND created_at < datetime('now', ?)",
            (f"-{self._retention_days} days",),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            self._conn.execute("PRAGMA incremental_vacuum")
        return deleted

    async def check_size(self) -> float:
        """Return current database size in MB."""
        return await asyncio.to_thread(self._check_size_sync)

    def _check_size_sync(self) -> float:
        if self._path.exists():
            return self._path.stat().st_size / (1024 * 1024)
        return 0.0

    async def count_unexported(self) -> int:
        """Count unexported points."""
        return await asyncio.to_thread(self._count_unexported_sync)

    def _count_unexported_sync(self) -> int:
        assert self._conn is not None
        cursor = self._conn.execute("SELECT COUNT(*) FROM telemetry_points WHERE exported = 0")
        return cursor.fetchone()[0]

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
