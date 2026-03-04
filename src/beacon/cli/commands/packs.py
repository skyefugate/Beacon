"""beacon packs list/show — browse available diagnostic packs."""

from __future__ import annotations

from pathlib import Path

import typer

from beacon.cli.output import console, print_error, print_table

packs_app = typer.Typer(help="Manage diagnostic packs")


@packs_app.command("list")
def list_packs():
    """List all available packs."""
    from beacon.packs.registry import PackRegistry

    registry = PackRegistry()
    packs_dir = Path("packs")
    if packs_dir.is_dir():
        registry.load_from_directory(packs_dir)

    packs = registry.list_packs()
    if not packs:
        console.print("No packs found. Check the 'packs/' directory.")
        return

    rows = [[p.name, p.description, p.version, str(len(p.steps))] for p in packs]
    print_table("Available Packs", ["Name", "Description", "Version", "Steps"], rows)


@packs_app.command("show")
def show_pack(name: str = typer.Argument(..., help="Pack name")):
    """Show details of a specific pack."""
    from beacon.packs.registry import PackRegistry

    registry = PackRegistry()
    packs_dir = Path("packs")
    if packs_dir.is_dir():
        registry.load_from_directory(packs_dir)

    pack = registry.get(name)
    if not pack:
        print_error(f"Pack '{name}' not found")
        raise typer.Exit(1)

    console.print(f"\n[bold]{pack.name}[/bold] v{pack.version}")
    console.print(f"{pack.description}\n")

    rows = []
    for step in pack.steps:
        status = "[green]enabled[/green]" if step.enabled else "[dim]disabled[/dim]"
        priv = "[yellow]yes[/yellow]" if step.privileged else "no"
        rows.append([step.plugin, step.type, priv, status])

    print_table("Steps", ["Plugin", "Type", "Privileged", "Status"], rows)
