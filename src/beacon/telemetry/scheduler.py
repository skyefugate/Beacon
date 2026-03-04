"""TelemetryScheduler — asyncio task manager for the telemetry subsystem.

Creates per-sampler tasks, an aggregation task, and an export task.
Provides start()/stop() lifecycle and dynamic interval adjustment
for escalation support.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from beacon.config import BeaconSettings
from beacon.models.envelope import Metric
from beacon.telemetry.aggregator import WindowAggregator
from beacon.telemetry.buffer import SQLiteBuffer
from beacon.telemetry.export.base import BaseExporter
from beacon.telemetry.sampler import BaseSampler

logger = logging.getLogger(__name__)


class TelemetryScheduler:
    """Manages the lifecycle of all telemetry samplers, aggregation, and export."""

    def __init__(
        self,
        settings: BeaconSettings,
        samplers: list[BaseSampler],
        buffer: SQLiteBuffer,
        exporters: list[BaseExporter] | None = None,
    ) -> None:
        self._settings = settings
        self._samplers = samplers
        self._buffer = buffer
        self._exporters = exporters or []
        self._aggregator = WindowAggregator(settings.telemetry.window_seconds)
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._interval_overrides: dict[str, int] = {}

    @property
    def running(self) -> bool:
        return self._running

    @property
    def aggregator(self) -> WindowAggregator:
        return self._aggregator

    async def start(self) -> None:
        """Start all sampler tasks, aggregation loop, and export loop."""
        if self._running:
            return

        self._running = True
        self._buffer.open()

        # Create per-sampler tasks
        for sampler in self._samplers:
            task = asyncio.create_task(
                self._sampler_loop(sampler),
                name=f"sampler-{sampler.name}",
            )
            self._tasks.append(task)

        # Aggregation task
        self._tasks.append(asyncio.create_task(
            self._aggregation_loop(),
            name="aggregation",
        ))

        # Export task
        if self._exporters:
            self._tasks.append(asyncio.create_task(
                self._export_loop(),
                name="export",
            ))

        logger.info(
            "Telemetry scheduler started with %d samplers, %d exporters",
            len(self._samplers), len(self._exporters),
        )

    async def stop(self) -> None:
        """Stop all tasks and clean up."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Final flush
        try:
            windows = self._aggregator.flush()
            if windows:
                await self._export_windows(windows)
        except Exception as e:
            logger.debug("Final flush error: %s", e)

        for exporter in self._exporters:
            try:
                await exporter.close()
            except Exception as e:
                logger.debug("Exporter close error: %s", e)

        self._buffer.close()
        logger.info("Telemetry scheduler stopped")

    def set_interval(self, sampler_name: str, interval: int) -> None:
        """Override the interval for a sampler (used by escalation engine)."""
        self._interval_overrides[sampler_name] = interval

    def clear_interval_override(self, sampler_name: str) -> None:
        """Remove an interval override, reverting to default."""
        self._interval_overrides.pop(sampler_name, None)

    def add_sampler(self, sampler: BaseSampler) -> None:
        """Dynamically add and start a sampler (used by escalation to enable tiers)."""
        self._samplers.append(sampler)
        if self._running:
            task = asyncio.create_task(
                self._sampler_loop(sampler),
                name=f"sampler-{sampler.name}",
            )
            self._tasks.append(task)

    def remove_sampler(self, name: str) -> None:
        """Remove a sampler by name (used by escalation to disable tiers)."""
        self._samplers = [s for s in self._samplers if s.name != name]
        # The task will exit on next iteration when it checks _running

    async def _sampler_loop(self, sampler: BaseSampler) -> None:
        """Repeatedly sample at the configured interval."""
        while self._running:
            try:
                metrics = await sampler.sample()
                if metrics:
                    self._aggregator.push(metrics)
                    await self._buffer.write_points(metrics)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Sampler %s error: %s", sampler.name, e)

            interval = self._interval_overrides.get(
                sampler.name, sampler.default_interval,
            )
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _aggregation_loop(self) -> None:
        """Flush aggregated windows periodically."""
        while self._running:
            try:
                await asyncio.sleep(self._settings.telemetry.window_seconds)
            except asyncio.CancelledError:
                break

            try:
                windows = self._aggregator.flush()
                if windows:
                    await self._export_windows(windows)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Aggregation error: %s", e)

    async def _export_loop(self) -> None:
        """Periodically flush buffered points to exporters."""
        while self._running:
            try:
                await asyncio.sleep(self._settings.telemetry.export_flush_interval)
            except asyncio.CancelledError:
                break

            for exporter in self._exporters:
                try:
                    if hasattr(exporter, "flush_buffer"):
                        await exporter.flush_buffer()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("Export %s error: %s", exporter.name, e)

    async def _export_windows(self, windows: list[Any]) -> None:
        """Convert aggregated windows to Metrics and export them."""
        from datetime import datetime, timezone
        agg_metrics = []
        for w in windows:
            agg_metrics.append(Metric(
                measurement=f"{w.measurement}_agg",
                fields={
                    f"{w.field_name}_p50": w.p50,
                    f"{w.field_name}_p95": w.p95,
                    f"{w.field_name}_p99": w.p99,
                    f"{w.field_name}_min": w.min,
                    f"{w.field_name}_max": w.max,
                    f"{w.field_name}_mean": w.mean,
                    f"{w.field_name}_jitter": w.jitter,
                    f"{w.field_name}_count": w.count,
                },
                tags=w.tags,
                timestamp=w.window_end,
            ))

        for exporter in self._exporters:
            try:
                await exporter.export(agg_metrics)
            except Exception as e:
                logger.warning("Window export %s error: %s", exporter.name, e)
