"""beacon server start — launches the uvicorn API server."""

from __future__ import annotations

import typer

server_app = typer.Typer(help="Beacon API server management")


@server_app.command("start")
def start(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
    log_level: str = typer.Option("info", help="Log level"),
):
    """Start the Beacon API server."""
    import uvicorn
    from beacon.cli.output import print_success

    print_success(f"Starting Beacon server on {host}:{port}")
    uvicorn.run(
        "beacon.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )
