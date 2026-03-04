"""Tests for JSONL file exporter — write, rotation, max files."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import orjson
import pytest

from beacon.models.envelope import Metric
from beacon.telemetry.export.file import FileExporter


def _make_metric(value: float = 10.0) -> Metric:
    return Metric(
        measurement="t_ping",
        fields={"rtt_ms": value},
        tags={"target": "8.8.8.8"},
        timestamp=datetime.now(timezone.utc),
    )


class TestFileExporter:
    @pytest.mark.asyncio
    async def test_write_creates_file(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        exporter = FileExporter(path=path)

        count = await exporter.export([_make_metric()])
        assert count == 1
        assert path.exists()

    @pytest.mark.asyncio
    async def test_write_jsonl_format(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        exporter = FileExporter(path=path)

        await exporter.export([_make_metric(42.0)])

        lines = path.read_bytes().strip().split(b"\n")
        assert len(lines) == 1
        data = orjson.loads(lines[0])
        assert data["measurement"] == "t_ping"
        assert data["fields"]["rtt_ms"] == 42.0

    @pytest.mark.asyncio
    async def test_append_multiple(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        exporter = FileExporter(path=path)

        await exporter.export([_make_metric(1.0)])
        await exporter.export([_make_metric(2.0)])

        lines = path.read_bytes().strip().split(b"\n")
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_rotation(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        # Very small max for fast rotation
        exporter = FileExporter(path=path, max_mb=0, max_files=3)

        # Write enough to trigger rotation
        for i in range(5):
            await exporter.export([_make_metric(float(i))])

        # Should have rotated files
        assert path.exists()
        rotated = list(tmp_path.glob("telemetry.jsonl.*"))
        assert len(rotated) <= 3

    @pytest.mark.asyncio
    async def test_max_files_limit(self, tmp_path):
        path = tmp_path / "telemetry.jsonl"
        exporter = FileExporter(path=path, max_mb=0, max_files=2)

        for i in range(10):
            await exporter.export([_make_metric(float(i))])

        # At most 2 rotated files + current
        rotated = list(tmp_path.glob("telemetry.jsonl.*"))
        assert len(rotated) <= 2

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "telemetry.jsonl"
        exporter = FileExporter(path=path)

        await exporter.export([_make_metric()])
        assert path.exists()

    @pytest.mark.asyncio
    async def test_close_is_noop(self, tmp_path):
        exporter = FileExporter(path=tmp_path / "test.jsonl")
        await exporter.close()  # Should not raise


class TestFileExporterRetry:
    @pytest.mark.asyncio
    async def test_export_retry_on_batch(self, tmp_path):
        """Multiple metrics in a single batch all get written."""
        path = tmp_path / "telemetry.jsonl"
        exporter = FileExporter(path=path)

        metrics = [_make_metric(float(i)) for i in range(10)]
        count = await exporter.export(metrics)
        assert count == 10

        lines = path.read_bytes().strip().split(b"\n")
        assert len(lines) == 10
