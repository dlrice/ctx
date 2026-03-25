"""Smart repo sizing with gitingest."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path

from ctx import RepoStrategy, SourceResult, SourceType
from ctx.display import console

DEFAULT_FULL_THRESHOLD = 100_000
DEFAULT_MAP_MULTIPLIER = 3
DEFAULT_FILE_COUNT_THRESHOLD = 500

PROBE_TIMEOUT_SECONDS = 30
DIFF_MAX_BYTES = 50_000  # Truncate diffs larger than this to avoid blowing token budgets


class _ProbeTimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _ProbeTimeoutError("Probe timed out")


def _count_tree_files(tree: str) -> int:
    """Count files from gitingest tree output (newline count as proxy)."""
    if not tree:
        return 0
    return len([line for line in tree.strip().splitlines() if line.strip()])


def _detect_default_branch(repo_path: str) -> str | None:
    """Auto-detect the default branch (main or master) of a local git repo."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        if result.returncode == 0:
            # e.g. "refs/remotes/origin/main" → "main"
            return result.stdout.strip().rsplit("/", 1)[-1]
    except Exception:
        pass

    # Fallback: check if main or master exist
    for branch in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=5,
            )
            if result.returncode == 0:
                return branch
        except Exception:
            pass
    return None


def _get_git_diff(repo_path: str, diff_base: str | None = None) -> str | None:
    """Get the git diff for the repo against a base branch.

    Returns the unified diff output, or None if not a git repo or no changes.
    Truncates output to DIFF_MAX_BYTES to avoid blowing token budgets.
    """
    path = Path(repo_path).resolve()
    if not (path / ".git").exists() and not (path / ".git").is_file():
        return None

    repo_dir = str(path)

    # Resolve base branch
    base = diff_base or _detect_default_branch(repo_dir)
    if not base:
        return None

    try:
        # Get the merge-base to diff only changes on current branch
        merge_base_result = subprocess.run(
            ["git", "merge-base", base, "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_dir,
            timeout=10,
        )
        if merge_base_result.returncode != 0:
            # Maybe same branch or no common ancestor — try diffing against base directly
            ref = base
        else:
            ref = merge_base_result.stdout.strip()

        # Get the actual diff
        diff_result = subprocess.run(
            ["git", "diff", ref, "--stat", "--patch"],
            capture_output=True,
            text=True,
            cwd=repo_dir,
            timeout=30,
        )
        if diff_result.returncode != 0 or not diff_result.stdout.strip():
            return None

        diff_text = diff_result.stdout
        if len(diff_text.encode("utf-8", errors="replace")) > DIFF_MAX_BYTES:
            # Truncate and note it
            truncated = diff_text[:DIFF_MAX_BYTES]
            # Cut at last newline for cleanliness
            last_nl = truncated.rfind("\n")
            if last_nl > 0:
                truncated = truncated[:last_nl]
            diff_text = truncated + "\n\n... (diff truncated — exceeded 50KB limit)"

        return diff_text

    except Exception:
        return None


def load_repo(
    path: str,
    *,
    strategy: RepoStrategy = RepoStrategy.AUTO,
    budget_tokens: int | None = None,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    model: str | None = None,
    diff_base: str | None = None,
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
            diff_base=diff_base,
        )

    # AUTO strategy: probe first, then decide
    console.print("[dim]Probing repository size...[/dim]")

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
            diff_base=diff_base,
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

    # If we chose FULL and already have the probe data, reuse it (but still collect diff)
    if chosen == RepoStrategy.FULL and probe_content is not None:
        content = probe_content
        diff_text = _get_git_diff(path, diff_base)
        if diff_text:
            console.print("[dim]Including git diff in output[/dim]")
            diff_section = (
                "## Recent Changes (git diff)\n\n"
                "The following diff shows uncommitted or branch changes. "
                "Prioritize reviewing these areas.\n\n"
                f"```diff\n{diff_text}\n```\n\n---\n\n"
            )
            content = diff_section + content
            probe_tokens = count_tokens(content, model)
        return SourceResult(
            path=path,
            source_type=SourceType.REPO,
            content=content,
            tokens=probe_tokens,
            metadata={
                "strategy": "full",
                "total_files": total_files,
                "total_tokens": probe_tokens,
                "has_diff": bool(diff_text),
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
        diff_base=diff_base,
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
    diff_base: str | None = None,
) -> SourceResult:
    """Execute a specific repo strategy."""
    from ctx.tokens import count_tokens

    try:
        if strategy == RepoStrategy.FULL:
            _summary, tree, content = ingest_fn(path)
            files = _count_tree_files(tree)
            # Prepend diff section if available (helps reviewers focus on changes)
            diff_section = ""
            diff_text = _get_git_diff(path, diff_base)
            if diff_text:
                console.print("[dim]Including git diff in output[/dim]")
                diff_section = (
                    "## Recent Changes (git diff)\n\n"
                    "The following diff shows uncommitted or branch changes. "
                    "Prioritize reviewing these areas.\n\n"
                    f"```diff\n{diff_text}\n```\n\n---\n\n"
                )
                content = diff_section + content
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
                    "has_diff": bool(diff_text),
                },
            )

        elif strategy == RepoStrategy.MAP:
            kwargs = {}
            if include:
                kwargs["include_patterns"] = list(include)
            if exclude:
                kwargs["exclude_patterns"] = list(exclude)
            _summary, tree, content = ingest_fn(path, **kwargs)
            # Prepend diff section so reviewers can focus on changed code
            diff_section = ""
            diff_text = _get_git_diff(path, diff_base)
            if diff_text:
                console.print("[dim]Including git diff in output[/dim]")
                diff_section = (
                    "## Recent Changes (git diff)\n\n"
                    "The following diff shows uncommitted or branch changes. "
                    "Prioritize reviewing these areas.\n\n"
                    f"```diff\n{diff_text}\n```\n\n---\n\n"
                )
            combined = diff_section + tree + "\n\n" + content if content else tree
            if diff_section and not content:
                combined = diff_section + tree
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
                    "has_diff": bool(diff_text),
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
