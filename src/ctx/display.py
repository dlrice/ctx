"""Rich console and summary table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from ctx import AssemblyResult

console = Console(stderr=True)


def _format_bytes(n: int) -> str:
    """Format byte count to human readable."""
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    else:
        return f"{n / (1024 * 1024):.1f} MB"


def _source_notes(source) -> str:
    """Build notes string for a source."""
    parts: list[str] = []

    if source.error:
        return source.error

    meta = source.metadata

    if source.source_type.value in ("repo", "directory"):
        strategy = meta.get("strategy", "")
        if strategy:
            parts.append(f"{strategy} strategy")
        total_files = meta.get("total_files")
        if total_files is not None:
            parts.append(f"{total_files} files")

    return ", ".join(parts)


def print_summary(result: AssemblyResult) -> None:
    """Render source summary table to stderr."""
    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Source", style="cyan", min_width=20)
    table.add_column("Type", min_width=8)
    table.add_column("Tokens", justify="right", min_width=8)
    table.add_column("Bytes", justify="right", min_width=8)
    table.add_column("Notes", min_width=20)

    for source in result.sources:
        prefix = "\u274c " if source.error else ""
        name = source.name or source.path
        content_bytes = len(source.content.encode("utf-8")) if source.content else 0

        table.add_row(
            f"{prefix}{name}",
            source.source_type.value,
            f"{source.tokens:,}",
            _format_bytes(content_bytes),
            _source_notes(source),
        )

    # Total row
    table.add_section()

    budget_note = ""
    if result.budget_tokens is not None:
        if result.over_budget:
            budget_note = f"budget: {result.budget_tokens:,} [red]\u2717 OVER[/red]"
        else:
            budget_note = f"budget: {result.budget_tokens:,} [green]\u2713[/green]"

    total_bytes = sum(len(s.content.encode("utf-8")) for s in result.sources if s.content)

    table.add_row(
        "[bold]Total[/bold]",
        "",
        f"[bold]{result.total_tokens:,}[/bold]",
        f"[bold]{_format_bytes(total_bytes)}[/bold]",
        budget_note,
    )

    console.print(table)
