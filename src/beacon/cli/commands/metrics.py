"""beacon metrics query — query InfluxDB metrics."""

from __future__ import annotations

import typer

from beacon.cli.output import print_error, print_json

metrics_app = typer.Typer(help="Query metrics")


@metrics_app.command("query")
def query(
    flux: str = typer.Argument(..., help="Flux query string"),
    server: str = typer.Option(None, "--server", "-s", help="API server URL"),
):
    """Execute a Flux query against InfluxDB."""
    if server:
        _query_via_api(flux, server)
    else:
        _query_locally(flux)


def _query_locally(flux: str) -> None:
    from beacon.config import get_settings
    from beacon.storage.influx import InfluxStorage

    settings = get_settings()
    try:
        with InfluxStorage(settings) as influx:
            results = influx.query(flux)
            print_json({"results": results})
    except Exception as e:
        print_error(f"Query failed: {e}")
        raise typer.Exit(1)


def _query_via_api(flux: str, server: str) -> None:
    import httpx

    base = server.rstrip("/")
    try:
        resp = httpx.post(
            f"{base}/metrics/query",
            json={"query": flux},
            timeout=30,
        )
        resp.raise_for_status()
        print_json(resp.json())
    except httpx.HTTPError as e:
        print_error(f"Query failed: {e}")
        raise typer.Exit(1)
