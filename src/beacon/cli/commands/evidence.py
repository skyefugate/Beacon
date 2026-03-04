"""beacon evidence get/list — browse and export evidence packs."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import typer

from beacon.cli.output import console, print_error, print_json, print_success, print_table

evidence_app = typer.Typer(help="Manage evidence packs")


@evidence_app.command("list")
def list_evidence():
    """List all stored evidence packs."""
    from beacon.config import get_settings
    from beacon.storage.evidence_store import EvidenceStore

    settings = get_settings()
    store = EvidenceStore(settings.storage.evidence_dir)
    runs = store.list_runs()

    if not runs:
        console.print("No evidence packs found.")
        return

    rows = []
    for run_id in runs:
        pack = store.load(run_id)
        if pack:
            rows.append([
                str(run_id)[:12] + "...",
                pack.pack_name,
                pack.fault_domain.fault_domain.value,
                f"{pack.fault_domain.confidence:.0%}",
                pack.completed_at.isoformat()[:19],
            ])

    print_table(
        "Evidence Packs",
        ["Run ID", "Pack", "Fault Domain", "Confidence", "Completed"],
        rows,
    )


@evidence_app.command("get")
def get_evidence(
    run_id: str = typer.Argument(..., help="Run ID (or prefix)"),
    output: str = typer.Option(None, "--output", "-o", help="Save to file"),
):
    """Get a specific evidence pack by run ID."""
    from beacon.config import get_settings
    from beacon.storage.evidence_store import EvidenceStore

    settings = get_settings()
    store = EvidenceStore(settings.storage.evidence_dir)

    # Support prefix matching, fall back to substring matching
    all_runs = store.list_runs()
    matches = [r for r in all_runs if str(r).startswith(run_id)]

    if not matches:
        # Fall back to substring/contains matching
        matches = [r for r in all_runs if run_id in str(r)]

    if not matches:
        print_error(f"No evidence pack matching '{run_id}'")
        raise typer.Exit(1)
    if len(matches) > 1:
        print_error(f"Ambiguous run ID prefix '{run_id}' — matches {len(matches)} packs")
        raise typer.Exit(1)

    pack = store.load(matches[0])
    if not pack:
        print_error(f"Failed to load evidence pack {matches[0]}")
        raise typer.Exit(1)

    data = pack.model_dump(mode="json")

    if output:
        with open(output, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print_success(f"Evidence pack saved to {output}")
    else:
        print_json(data)
