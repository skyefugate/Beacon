"""Collector sidecar FastAPI server — privileged HTTP API on port 9100.

This minimal server exposes collector functionality to beacon-core.
It runs with NET_RAW and NET_ADMIN capabilities for Wi-Fi metrics,
ICMP ping, and traceroute.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from beacon import __version__
from beacon.collectors.device import DeviceCollector
from beacon.collectors.lan import LANCollector
from beacon.collectors.path import PathCollector
from beacon.collectors.wifi import WiFiCollector
from beacon.runners.base import RunnerConfig
from beacon.runners.ping import PingRunner
from beacon.runners.traceroute import TracerouteRunner

app = FastAPI(title="Beacon Collector Sidecar", version=__version__)

_COLLECTORS = {
    "device": DeviceCollector,
    "lan": LANCollector,
    "wifi": WiFiCollector,
    "path": PathCollector,
}

_RUNNERS = {
    "ping": PingRunner,
    "traceroute": TracerouteRunner,
}


class CollectRequest(BaseModel):
    run_id: str
    config: dict = {}


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__, "role": "collector"}


@app.post("/collect/{plugin_name}")
async def collect(plugin_name: str, request: CollectRequest) -> dict:
    """Execute a collector or runner and return the PluginEnvelope."""
    run_id = UUID(request.run_id)

    if plugin_name in _COLLECTORS:
        collector = _COLLECTORS[plugin_name]()
        envelope = collector.collect(run_id)
        return envelope.model_dump(mode="json")

    if plugin_name in _RUNNERS:
        runner = _RUNNERS[plugin_name]()
        config = RunnerConfig(**request.config) if request.config else RunnerConfig()
        envelope = runner.run(run_id, config)
        return envelope.model_dump(mode="json")

    raise HTTPException(status_code=404, detail=f"Unknown plugin: {plugin_name}")
