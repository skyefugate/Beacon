"""Health check routes — /health and /ready."""

from __future__ import annotations

from fastapi import APIRouter

from beacon import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness check — always returns OK if the server is running."""
    return {
        "status": "ok",
        "version": __version__,
    }


@router.get("/ready")
async def ready():
    """Readiness check — verifies dependencies are available."""
    from beacon.api.deps import get_influx_storage

    checks: dict[str, str] = {}

    influx = get_influx_storage()
    checks["influxdb"] = "ok" if influx else "unavailable"
    if influx:
        influx.close()

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }
