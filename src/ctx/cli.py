"""ctx CLI — Typer application for context assembly."""

from __future__ import annotations

import json
import platform
import subprocess
import sys

import typer

from ctx import AssemblyResult, RepoStrategy, SourceType, __version__
from ctx.display import console, print_summary
from ctx.format import assemble
from ctx.sources import detect_type, load_source
from ctx.tokens import check_budget, count_tokens

app = typer.Typer(
    help="Assemble context from multiple sources for LLM consumption.",
)


def version_callback(value: bool):
    if value:
        typer.echo(f"ctx {__version__}")
        raise typer.Exit()


def run():
    """Entry point for the CLI."""
    app()


@app.command()
def main(
    sources: list[str] | None = typer.Argument(
        default=None,
        help="Sources: file paths, directories, URLs, or '-' for stdin",
    ),
    repo: str | None = typer.Option(None, help="Repository path or URL (uses smart sizing)"),
    include: str | None = typer.Option(
        None, help="Glob patterns to include (comma-separated, repo/dir only)"
    ),
    exclude: str | None = typer.Option(
        None, help="Glob patterns to exclude (comma-separated, repo/dir only)"
    ),
    repo_strategy: str = typer.Option(
        "auto", "--repo-strategy", help="Repo sizing: auto|full|map|tree"
    ),
    budget: int | None = typer.Option(
        None, help="Target token budget. Triggers smart sizing for repos."
    ),
    model: str | None = typer.Option(None, help="Target LLM model for accurate token counting"),
    no_tags: bool = typer.Option(
        False, "--no-tags", help="Output raw concatenation without XML source tags"
    ),
    separator: str = typer.Option(
        "\n\n---\n\n", help="Separator between sources when --no-tags is used"
    ),
    summary: bool = typer.Option(
        False, "--summary", "-s", help="Print source summary table to stderr"
    ),
    output_format: str = typer.Option("text", "--output-format", help="Output format: text|json"),
    copy: bool = typer.Option(
        False, "--copy", "-c", help="Copy output to clipboard (in addition to stdout)"
    ),
    version: bool | None = typer.Option(
        None, "--version", "-V", callback=version_callback, is_eager=True
    ),
):
    """Assemble context from multiple sources into a single LLM-ready document."""

    # Collect all source specs
    all_sources: list[str] = []

    if sources:
        all_sources.extend(sources)

    # Validate: need at least one source
    if not all_sources and not repo:
        console.print("[red]Error: No sources provided[/red]")
        raise typer.Exit(code=2)

    # Validate repo_strategy
    try:
        strategy = RepoStrategy(repo_strategy.lower())
    except ValueError:
        msg = f"Invalid repo strategy '{repo_strategy}'. Use: auto|full|map|tree"
        console.print(f"[red]Error: {msg}[/red]")
        raise typer.Exit(code=2) from None

    # Validate output_format
    if output_format not in ("text", "json"):
        console.print(f"[red]Error: Invalid output format '{output_format}'. Use: text|json[/red]")
        raise typer.Exit(code=2)

    # Parse include/exclude patterns
    include_patterns = set(p.strip() for p in include.split(",")) if include else None
    exclude_patterns = set(p.strip() for p in exclude.split(",")) if exclude else None

    # Check for duplicate stdin sources
    stdin_count = all_sources.count("-")
    if stdin_count > 1:
        console.print("[red]Error: Only one stdin source allowed[/red]")
        raise typer.Exit(code=2)

    # Load all sources
    results = []

    # If --repo is provided, load it first
    if repo:
        console.print(f"[dim]Loading repo: {repo}[/dim]")
        repo_result = load_source(
            repo,
            SourceType.REPO,
            include=include_patterns,
            exclude=exclude_patterns,
            repo_strategy=strategy,
            budget_tokens=budget,
            model=model,
        )
        results.append(repo_result)

    # Load positional sources
    for source_str in all_sources:
        try:
            source_type = detect_type(source_str)
        except FileNotFoundError as e:
            from ctx import SourceResult

            results.append(
                SourceResult(
                    path=source_str,
                    source_type=SourceType.FILE,
                    error=str(e),
                )
            )
            continue

        console.print(f"[dim]Loading: {source_str} ({source_type.value})[/dim]")
        result = load_source(
            source_str,
            source_type,
            include=include_patterns,
            exclude=exclude_patterns,
            repo_strategy=strategy,
            budget_tokens=budget,
            model=model,
        )
        results.append(result)

    # Count tokens for sources that don't have them yet
    for result in results:
        if result.tokens == 0 and result.content and not result.error:
            result.tokens = count_tokens(result.content, model)

    # Check if all sources failed
    all_failed = all(r.error is not None for r in results)
    if all_failed:
        console.print("[red]Error: All sources failed to load[/red]")
        for r in results:
            console.print(f"  [red]{r.path}: {r.error}[/red]")
        raise typer.Exit(code=1)

    # Assemble output
    use_tags = not no_tags
    output = assemble(results, use_tags=use_tags, separator=separator)

    # Calculate totals
    total_tokens = sum(r.tokens for r in results)
    over_budget, budget_msg = check_budget(total_tokens, budget)

    # Build assembly result
    assembly = AssemblyResult(
        output=output,
        sources=results,
        total_tokens=total_tokens,
        budget_tokens=budget,
        over_budget=over_budget,
    )

    # Print budget warning if over
    if over_budget:
        console.print(f"[yellow]Warning: {budget_msg}[/yellow]")

    # Print summary table if requested
    if summary:
        print_summary(assembly)

    # Output
    if output_format == "json":
        json_out = assembly.model_dump()
        sys.stdout.write(json.dumps(json_out, indent=2, default=str) + "\n")
    else:
        sys.stdout.write(output + "\n")

    # Copy to clipboard if requested
    if copy:
        _copy_to_clipboard(output)


def _copy_to_clipboard(text: str) -> None:
    """Copy text to clipboard using platform-specific tools."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        elif system == "Linux":
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                check=True,
            )
        elif system == "Windows":
            subprocess.run(["clip"], input=text.encode(), check=True)
        else:
            console.print("[yellow]Warning: Clipboard not supported on this platform[/yellow]")
            return
        console.print("[green]Copied to clipboard[/green]")
    except FileNotFoundError:
        console.print("[yellow]Warning: Clipboard tool not found[/yellow]")
    except subprocess.CalledProcessError:
        console.print("[yellow]Warning: Failed to copy to clipboard[/yellow]")
