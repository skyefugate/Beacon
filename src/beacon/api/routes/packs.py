"""Pack routes — list packs and trigger pack runs."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException

from beacon.api.deps import (
    get_evidence_builder,
    get_evidence_store,
    get_pack_executor,
    get_pack_registry,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/packs", tags=["packs"])

_MAX_STATUS_ENTRIES = 500
_STATUS_TTL_SECONDS = 3600  # evict completed/error runs after 1 hour

# In-memory run status tracking (MVP-0 — single process)
_run_status: dict[str, dict] = {}


def _evict_old_runs() -> None:
    """Evict completed/error runs older than TTL; cap total entries at max size."""
    now = time.monotonic()
    stale = [
        k
        for k, v in _run_status.items()
        if v.get("status") in ("completed", "error")
        and now - v.get("_ts", now) > _STATUS_TTL_SECONDS
    ]
    for k in stale:
        del _run_status[k]
    if len(_run_status) > _MAX_STATUS_ENTRIES:
        completed = sorted(
            [(k, v) for k, v in _run_status.items() if v.get("status") != "running"],
            key=lambda x: x[1].get("_ts", 0),
        )
        for k, _ in completed[: len(_run_status) - _MAX_STATUS_ENTRIES]:
            del _run_status[k]


@router.get("/")
async def list_packs():
    """List all available packs."""
    registry = get_pack_registry()
    packs = registry.list_packs()
    return {
        "packs": [
            {
                "name": p.name,
                "description": p.description,
                "version": p.version,
                "steps": len(p.steps),
                "timeout_seconds": p.timeout_seconds,
            }
            for p in packs
        ]
    }


@router.get("/{name}")
async def get_pack(name: str):
    """Get details of a specific pack."""
    registry = get_pack_registry()
    pack = registry.get(name)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found")
    return pack.model_dump()


@router.post("/{name}/run")
async def run_pack(name: str, background_tasks: BackgroundTasks):
    """Trigger a pack run. Returns immediately with a run_id."""
    registry = get_pack_registry()
    pack = registry.get(name)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found")

    # Concurrency limit: one active run per pack name
    already_running = any(
        v.get("pack") == name and v.get("status") == "running" for v in _run_status.values()
    )
    if already_running:
        raise HTTPException(
            status_code=429,
            detail=f"Pack '{name}' is already running. Wait for it to complete.",
        )

    run_id = uuid4()
    _run_status[str(run_id)] = {"status": "running", "pack": name, "_ts": time.monotonic()}

    background_tasks.add_task(_execute_pack_run, str(run_id), name)

    return {
        "run_id": str(run_id),
        "status": "running",
        "pack": name,
    }


@router.get("/{name}/run/{run_id}")
async def get_run_status(name: str, run_id: str):
    """Check the status of a pack run."""
    status = _run_status.get(run_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return status


def _execute_pack_run(run_id_str: str, pack_name: str) -> None:
    """Background task that executes a pack run."""
    from uuid import UUID

    try:
        run_id = UUID(run_id_str)
        registry = get_pack_registry()
        pack = registry.get(pack_name)
        if not pack:
            _run_status[run_id_str] = {"status": "error", "error": "Pack not found"}
            return

        executor = get_pack_executor()
        started_at = datetime.now(timezone.utc)
        envelopes = executor.execute(pack, run_id)

        builder = get_evidence_builder()
        evidence_pack = builder.build(run_id, pack_name, envelopes, started_at)

        store = get_evidence_store()
        path = store.save(evidence_pack)

        _run_status[run_id_str] = {
            "status": "completed",
            "pack": pack_name,
            "run_id": run_id_str,
            "evidence_path": str(path),
            "_ts": time.monotonic(),
        }
        _evict_old_runs()

    except Exception as e:
        logger.error("Pack run %s failed: %s", run_id_str, e, exc_info=True)
        _run_status[run_id_str] = {
            "status": "error",
            "pack": pack_name,
            "error": str(e),
            "_ts": time.monotonic(),
        }
        _evict_old_runs()
