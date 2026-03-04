"""Evidence routes — retrieve evidence packs by run_id."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from beacon.api.deps import get_evidence_store

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/")
async def list_evidence():
    """List all stored evidence pack run IDs."""
    store = get_evidence_store()
    runs = store.list_runs()
    return {"runs": [str(r) for r in runs]}


@router.get("/{run_id}")
async def get_evidence(run_id: str):
    """Retrieve a complete evidence pack by run_id."""
    store = get_evidence_store()
    try:
        uid = UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    pack = store.load(uid)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Evidence pack '{run_id}' not found")

    return pack.model_dump(mode="json")


@router.delete("/{run_id}")
async def delete_evidence(run_id: str):
    """Delete an evidence pack by run_id."""
    store = get_evidence_store()
    try:
        uid = UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    if not store.delete(uid):
        raise HTTPException(status_code=404, detail=f"Evidence pack '{run_id}' not found")

    return {"deleted": run_id}
