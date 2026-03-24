"""Smart repo sizing with gitingest."""

from __future__ import annotations

import signal

from ctx import RepoStrategy, SourceResult, SourceType
from ctx.display import console

DEFAULT_FULL_THRESHOLD = 100_000
DEFAULT_MAP_MULTIPLIER = 3
DEFAULT_FILE_COUNT_THRESHOLD = 500

PROBE_TIMEOUT_SECONDS = 30


class _ProbeTimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _ProbeTimeoutError("Probe timed out")


def _count_tree_files(tree: str) -> int:
    """Count files from gitingest tree output (newline count as proxy)."""
    if not tree:
        return 0
    return len([line for line in tree.strip().splitlines() if line.strip()])


def load_repo(
    path: str,
    *,
    strategy: RepoStrategy = RepoStrategy.AUTO,
    budget_tokens: int | None = None,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    model: str | None = None,
) -> SourceResult:
    """Load a repository with smart sizing strategy.

    All strategies use gitingest. The (summary, tree, content) tuple
    maps directly to our three strategies.
    """
    try:
        from gitingest import ingest
    except ImportError:
        return SourceResult(
            path=path,
            source_type=SourceType.REPO,
            error='Repo support requires gitingest. Install with: pip install "ctx[repo]"',
        )

    from ctx.tokens import count_tokens

    # If strategy is forced (not AUTO), go directly to the requested strategy
    if strategy != RepoStrategy.AUTO:
        return _execute_strategy(
            path,
            strategy,
            include=include,
            exclude=exclude,
            model=model,
            ingest_fn=ingest,
        )

    # AUTO strategy: probe first, then decide
    console.status("Probing repository size...")

    probe_tree = None
    probe_content = None
    probe_timed_out = False

    try:
        # Set up timeout for probe
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(PROBE_TIMEOUT_SECONDS)
        try:
            _probe_summary, probe_tree, probe_content = ingest(path)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except _ProbeTimeoutError:
        probe_timed_out = True
        console.print(
            "[yellow]Warning: repo probe timed out, falling back to MAP strategy[/yellow]"
        )
    except Exception as e:
        return SourceResult(
            path=path,
            source_type=SourceType.REPO,
            error=f"Failed to ingest repository: {e}",
        )

    if probe_timed_out:
        # Fall back to MAP
        return _execute_strategy(
            path,
            RepoStrategy.MAP,
            include=include,
            exclude=exclude,
            model=model,
            ingest_fn=ingest,
        )

    # Count tokens on probed content
    probe_tokens = count_tokens(probe_content or "", model)
    total_files = _count_tree_files(probe_tree or "")

    # Decide strategy based on budget or file count
    if budget_tokens is not None:
        if probe_tokens <= budget_tokens:
            chosen = RepoStrategy.FULL
        elif probe_tokens <= budget_tokens * DEFAULT_MAP_MULTIPLIER:
            chosen = RepoStrategy.MAP
        else:
            chosen = RepoStrategy.TREE
    else:
        if total_files < DEFAULT_FILE_COUNT_THRESHOLD:
            chosen = RepoStrategy.FULL
        else:
            chosen = RepoStrategy.MAP

    console.print(
        f"[dim]Repo strategy: {chosen.value} ({probe_tokens:,} tokens, {total_files} files)[/dim]"
    )

    # If we chose FULL and already have the probe data, reuse it
    if chosen == RepoStrategy.FULL and probe_content is not None:
        return SourceResult(
            path=path,
            source_type=SourceType.REPO,
            content=probe_content,
            tokens=probe_tokens,
            metadata={
                "strategy": "full",
                "total_files": total_files,
                "total_tokens": probe_tokens,
            },
        )

    # If we chose TREE and have the probe tree, reuse it
    if chosen == RepoStrategy.TREE and probe_tree is not None:
        tree_tokens = count_tokens(probe_tree, model)
        return SourceResult(
            path=path,
            source_type=SourceType.REPO,
            content=probe_tree,
            tokens=tree_tokens,
            metadata={
                "strategy": "tree",
                "total_files": total_files,
                "total_tokens": tree_tokens,
            },
        )

    # Otherwise execute the chosen strategy (MAP needs patterns)
    return _execute_strategy(
        path,
        chosen,
        include=include,
        exclude=exclude,
        model=model,
        ingest_fn=ingest,
        probe_tree=probe_tree,
        probe_tokens=probe_tokens,
        total_files=total_files,
    )


def _execute_strategy(
    path: str,
    strategy: RepoStrategy,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    model: str | None = None,
    ingest_fn,
    probe_tree: str | None = None,
    probe_tokens: int | None = None,
    total_files: int | None = None,
) -> SourceResult:
    """Execute a specific repo strategy."""
    from ctx.tokens import count_tokens

    try:
        if strategy == RepoStrategy.FULL:
            _summary, tree, content = ingest_fn(path)
            files = _count_tree_files(tree)
            tokens = count_tokens(content, model)
            return SourceResult(
                path=path,
                source_type=SourceType.REPO,
                content=content,
                tokens=tokens,
                metadata={
                    "strategy": "full",
                    "total_files": files,
                    "total_tokens": tokens,
                },
            )

        elif strategy == RepoStrategy.MAP:
            kwargs = {}
            if include:
                kwargs["include_patterns"] = list(include)
            if exclude:
                kwargs["exclude_patterns"] = list(exclude)
            _summary, tree, content = ingest_fn(path, **kwargs)
            combined = tree + "\n\n" + content if content else tree
            files = total_files or _count_tree_files(tree)
            tokens = count_tokens(combined, model)
            return SourceResult(
                path=path,
                source_type=SourceType.REPO,
                content=combined,
                tokens=tokens,
                metadata={
                    "strategy": "map",
                    "total_files": files,
                    "total_tokens": tokens,
                },
            )

        elif strategy == RepoStrategy.TREE:
            _summary, tree, _content = ingest_fn(path)
            files = _count_tree_files(tree)
            tokens = count_tokens(tree, model)
            return SourceResult(
                path=path,
                source_type=SourceType.REPO,
                content=tree,
                tokens=tokens,
                metadata={
                    "strategy": "tree",
                    "total_files": files,
                    "total_tokens": tokens,
                },
            )

        else:
            return SourceResult(
                path=path,
                source_type=SourceType.REPO,
                error=f"Unknown strategy: {strategy}",
            )

    except Exception as e:
        return SourceResult(
            path=path,
            source_type=SourceType.REPO,
            error=f"Failed to ingest repository: {e}",
        )
