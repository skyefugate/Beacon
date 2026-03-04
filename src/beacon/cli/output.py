"""Rich console formatting utilities for the CLI."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
err_console = Console(stderr=True)


def print_success(message: str) -> None:
    console.print(f"[green]{message}[/green]")


def print_error(message: str) -> None:
    err_console.print(f"[red]Error:[/red] {message}")


def print_warning(message: str) -> None:
    console.print(f"[yellow]{message}[/yellow]")


def print_json(data: dict) -> None:
    import json
    console.print_json(json.dumps(data, indent=2, default=str))


def print_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def print_panel(title: str, content: str, style: str = "blue") -> None:
    console.print(Panel(content, title=title, border_style=style))
