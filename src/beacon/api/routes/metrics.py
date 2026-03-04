"""Metrics query route — proxy Flux queries to InfluxDB."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from beacon.api.deps import get_influx_storage

router = APIRouter(prefix="/metrics", tags=["metrics"])


class FluxQuery(BaseModel):
    query: str


@router.post("/query")
async def query_metrics(body: FluxQuery):
    """Execute a Flux query against InfluxDB."""
    influx = get_influx_storage()
    if not influx:
        raise HTTPException(
            status_code=503,
            detail="InfluxDB is not available",
        )

    try:
        results = influx.query(body.query)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        influx.close()
