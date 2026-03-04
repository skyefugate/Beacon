"""Pack executor — orchestrates the execution of a pack's steps.

Runs collectors and runners in order, collects their PluginEnvelopes,
and delegates privileged steps to the collector sidecar via HTTP.
When the sidecar is unavailable, privileged steps fall back to local
execution (which may produce partial results without elevated privileges).
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import httpx

from beacon.models.envelope import PluginEnvelope
from beacon.packs.registry import PluginRegistry
from beacon.packs.schema import PackDefinition, StepConfig
from beacon.runners.base import RunnerConfig

logger = logging.getLogger(__name__)


class PackExecutor:
    """Executes a pack definition and returns collected envelopes."""

    def __init__(
        self,
        plugin_registry: PluginRegistry,
        collector_url: str = "http://localhost:9100",
        collector_timeout: int = 30,
    ) -> None:
        self._plugins = plugin_registry
        self._collector_url = collector_url
        self._collector_timeout = collector_timeout

    def execute(self, pack: PackDefinition, run_id: UUID | None = None) -> list[PluginEnvelope]:
        """Execute all enabled steps in a pack and return their envelopes."""
        if run_id is None:
            run_id = uuid4()

        envelopes: list[PluginEnvelope] = []

        for step in pack.steps:
            if not step.enabled:
                continue

            try:
                if step.privileged:
                    envelope = self._execute_privileged(step, run_id)
                elif step.type == "collector":
                    envelope = self._execute_collector(step, run_id)
                else:
                    envelope = self._execute_runner(step, run_id)

                envelopes.append(envelope)
                logger.info("Completed step %s (%s)", step.plugin, step.type)

            except Exception as e:
                logger.warning("Skipping step %s: %s", step.plugin, e)

        return envelopes

    def _execute_collector(self, step: StepConfig, run_id: UUID) -> PluginEnvelope:
        """Execute a local collector step."""
        collector = self._plugins.get_collector(step.plugin)
        return collector.collect(run_id)

    def _execute_runner(self, step: StepConfig, run_id: UUID) -> PluginEnvelope:
        """Execute a local runner step."""
        runner = self._plugins.get_runner(step.plugin)
        config = RunnerConfig(**step.config) if step.config else RunnerConfig()
        return runner.run(run_id, config)

    def _execute_privileged(self, step: StepConfig, run_id: UUID) -> PluginEnvelope:
        """Execute a step via the privileged collector sidecar.

        Falls back to local execution if the sidecar is unreachable.
        Local execution may produce partial results (e.g., Wi-Fi metrics
        may be unavailable without NET_ADMIN).
        """
        url = f"{self._collector_url}/collect/{step.plugin}"
        payload = {
            "run_id": str(run_id),
            "config": step.config,
        }

        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self._collector_timeout,
            )
            response.raise_for_status()
            return PluginEnvelope.model_validate(response.json())
        except httpx.ConnectError:
            logger.info(
                "Collector sidecar unavailable, running %s locally (results may be partial)",
                step.plugin,
            )
            return self._execute_local_fallback(step, run_id)
        except httpx.HTTPError as e:
            logger.warning("Privileged step %s via sidecar failed: %s", step.plugin, e)
            return self._execute_local_fallback(step, run_id)

    def _execute_local_fallback(self, step: StepConfig, run_id: UUID) -> PluginEnvelope:
        """Try to run a privileged step locally as a best-effort fallback."""
        if step.type == "collector":
            return self._execute_collector(step, run_id)
        else:
            return self._execute_runner(step, run_id)
