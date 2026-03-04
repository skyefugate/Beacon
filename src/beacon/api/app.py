"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from beacon import __version__
from beacon.api.middleware import RequestLoggingMiddleware
from beacon.api.routes import evidence, health, metrics, packs, telemetry_api


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Beacon",
        description="Docker-first network diagnostics platform",
        version=__version__,
    )

    app.add_middleware(RequestLoggingMiddleware)

    # API routers — registered before static mount so they take precedence
    app.include_router(health.router)
    app.include_router(packs.router)
    app.include_router(evidence.router)
    app.include_router(metrics.router)
    app.include_router(telemetry_api.router)

    # Serve the built React dashboard as static files (SPA mode).
    # Only mounted if the dist directory exists (graceful when UI isn't built).
    # Check multiple candidate paths: source tree (dev) and CWD (Docker).
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "ui" / "dist",
        Path.cwd() / "ui" / "dist",
    ]
    for ui_dist in candidates:
        if ui_dist.is_dir():
            app.mount("/", StaticFiles(directory=str(ui_dist), html=True), name="ui")
            break

    return app


app = create_app()
