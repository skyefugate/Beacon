"""beacon run <pack> — execute a diagnostic pack locally or via API."""

from __future__ import annotations

import json
import time

import typer

from beacon.cli.output import console, print_error, print_success

run_app = typer.Typer(help="Run diagnostic packs")


@run_app.callback(invoke_without_command=True)
def run_pack(
    pack_name: str = typer.Argument(..., help="Name of the pack to run"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for completion"),
    output: str = typer.Option(None, "--output", "-o", help="Save evidence pack to file"),
    server: str = typer.Option(
        None, "--server", "-s", help="API server URL (runs locally if not set)"
    ),
    timeout: int = typer.Option(180, "--timeout", help="Max wait time in seconds"),
):
    """Run a diagnostic pack and produce an evidence pack."""
    if server:
        _run_via_api(pack_name, server, wait, output, timeout)
    else:
        _run_locally(pack_name, output)


def _run_locally(pack_name: str, output_path: str | None) -> None:
    """Execute a pack locally without going through the API."""
    from datetime import datetime, timezone
    from pathlib import Path
    from uuid import uuid4

    from beacon.config import get_settings
    from beacon.evidence.builder import EvidencePackBuilder
    from beacon.packs.executor import PackExecutor
    from beacon.packs.registry import PackRegistry, PluginRegistry
    from beacon.storage.evidence_store import EvidenceStore

    settings = get_settings()

    # Load packs
    registry = PackRegistry()
    packs_dir = Path("packs")
    if packs_dir.is_dir():
        registry.load_from_directory(packs_dir)

    pack = registry.get(pack_name)
    if not pack:
        print_error(f"Pack '{pack_name}' not found")
        raise typer.Exit(1)

    run_id = uuid4()
    started_at = datetime.now(timezone.utc)

    with console.status(f"Running pack '{pack_name}'..."):
        executor = PackExecutor(
            plugin_registry=PluginRegistry(),
            collector_url=settings.collector.url,
            collector_timeout=settings.collector.timeout_seconds,
        )
        envelopes = executor.execute(pack, run_id)

    with console.status("Building evidence pack..."):
        builder = EvidencePackBuilder(settings)
        evidence_pack = builder.build(run_id, pack_name, envelopes, started_at)

    # Save evidence pack
    store = EvidenceStore(settings.storage.evidence_dir)
    saved_path = store.save(evidence_pack)

    if output_path:
        import shutil

        shutil.copy2(saved_path, output_path)
        print_success(f"Evidence pack saved to {output_path}")
    else:
        print_success(f"Evidence pack saved to {saved_path}")

    # Print summary
    fd = evidence_pack.fault_domain
    total_events = sum(len(e.events) for e in evidence_pack.test_results)
    total_metrics = sum(len(e.metrics) for e in evidence_pack.test_results)

    console.print(f"\n[bold]Run ID:[/bold] {run_id}")
    console.print(f"[bold]Pack:[/bold] {pack_name}")

    if fd.fault_domain.value == "unknown" and fd.confidence == 0.0:
        if total_metrics > 0:
            console.print("[bold]Result:[/bold] [green]No faults detected[/green]")
            console.print(
                f"[bold]Detail:[/bold] {total_metrics} metrics collected, all within normal ranges"
            )
        else:
            console.print("[bold]Fault Domain:[/bold] unknown (insufficient data)")
    else:
        console.print(f"[bold]Fault Domain:[/bold] [yellow]{fd.fault_domain.value}[/yellow]")
        console.print(f"[bold]Confidence:[/bold] {fd.confidence:.1%}")
        if fd.evidence_refs:
            console.print("[bold]Evidence:[/bold]")
            for ref in fd.evidence_refs[:5]:
                console.print(f"  - {ref}")
        if fd.competing_hypotheses:
            console.print("[bold]Other possibilities:[/bold]")
            for hyp in fd.competing_hypotheses[:3]:
                console.print(f"  - {hyp.fault_domain.value}: {hyp.confidence:.1%}")

    console.print(f"[bold]Tests Run:[/bold] {len(evidence_pack.test_results)}")
    console.print(f"[bold]Events:[/bold] {total_events}")


def _run_via_api(
    pack_name: str, server: str, wait: bool, output_path: str | None, timeout: int
) -> None:
    """Execute a pack via the Beacon API."""
    import httpx

    base = server.rstrip("/")

    try:
        resp = httpx.post(f"{base}/packs/{pack_name}/run", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        print_error(f"Failed to start pack run: {e}")
        raise typer.Exit(1)

    run_id = data["run_id"]
    console.print(f"[bold]Run ID:[/bold] {run_id}")

    if not wait:
        console.print("Run started in background. Use 'beacon evidence get' to check results.")
        return

    with console.status(f"Running pack '{pack_name}'..."):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                status_resp = httpx.get(f"{base}/packs/{pack_name}/run/{run_id}", timeout=10)
                status = status_resp.json()
                if status.get("status") == "completed":
                    break
                if status.get("status") == "error":
                    print_error(f"Pack run failed: {status.get('error')}")
                    raise typer.Exit(1)
            except httpx.HTTPError:
                pass
            time.sleep(2)

    # Fetch evidence pack
    try:
        ev_resp = httpx.get(f"{base}/evidence/{run_id}", timeout=30)
        ev_resp.raise_for_status()
        evidence_data = ev_resp.json()
    except httpx.HTTPError as e:
        print_error(f"Failed to fetch evidence pack: {e}")
        raise typer.Exit(1)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(evidence_data, f, indent=2, default=str)
        print_success(f"Evidence pack saved to {output_path}")
    else:
        from beacon.cli.output import print_json

        print_json(evidence_data)
