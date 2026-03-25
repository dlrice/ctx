"""Source type detection and loading."""

from __future__ import annotations

import sys
from pathlib import Path

from ctx import RepoStrategy, SourceResult, SourceType
from ctx.display import console

# Binary detection hints for known extensions
BINARY_HINTS: dict[str, str] = {
    ".pdf": "PDF",
    ".docx": "Word document",
    ".xlsx": "Excel spreadsheet",
    ".pptx": "PowerPoint presentation",
    ".doc": "Word document",
    ".xls": "Excel spreadsheet",
    ".ppt": "PowerPoint presentation",
    ".zip": "ZIP archive",
    ".tar": "TAR archive",
    ".gz": "gzip archive",
    ".png": "PNG image",
    ".jpg": "JPEG image",
    ".jpeg": "JPEG image",
    ".gif": "GIF image",
    ".bmp": "BMP image",
    ".ico": "ICO image",
    ".mp3": "MP3 audio",
    ".mp4": "MP4 video",
    ".wav": "WAV audio",
    ".avi": "AVI video",
    ".exe": "executable",
    ".dll": "DLL library",
    ".so": "shared library",
    ".dylib": "dynamic library",
    ".o": "object file",
    ".pyc": "compiled Python",
    ".class": "compiled Java",
    ".wasm": "WebAssembly",
}

# Large file warning threshold
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10 MB


def detect_type(source: str) -> SourceType:
    """Auto-detect source type from the string.

    Detection order:
      1. '-'                          -> STDIN
      2. Starts with http:// https:// -> URL
      3. Is a directory on disk       -> DIRECTORY
      4. Is a file on disk            -> FILE
      5. Otherwise                    -> error
    """
    if source == "-":
        return SourceType.STDIN

    if source.startswith("http://") or source.startswith("https://"):
        return SourceType.URL

    p = Path(source)
    if p.is_dir():
        return SourceType.DIRECTORY

    if p.is_file():
        return SourceType.FILE

    # Not found — could be a typo or nonexistent path
    raise FileNotFoundError(f"Source not found: {source}")


def _is_binary(path: Path) -> bool:
    """Check if a file is binary by reading first 8KB and looking for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except Exception:
        return False


def _binary_hint(path: Path) -> str:
    """Get a helpful message for a binary file."""
    ext = path.suffix.lower()
    filetype = BINARY_HINTS.get(ext, "binary")
    name = path.name
    hint = f"{name} is a binary file ({filetype}). Extract text first"
    if ext == ".pdf":
        hint += f", e.g.:\n  pdftext {name} | ctx - other-sources..."
    elif ext in (".docx", ".doc"):
        hint += f", e.g.:\n  pandoc -t plain {name} | ctx - other-sources..."
    return hint


def load_source(
    source: str,
    source_type: SourceType,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    repo_strategy: RepoStrategy = RepoStrategy.AUTO,
    budget_tokens: int | None = None,
    model: str | None = None,
    diff_base: str | None = None,
) -> SourceResult:
    """Load content from a single source.

    Dispatches to the appropriate loader based on source type.
    Returns a SourceResult (with error field set on failure, never raises).
    """
    try:
        if source_type == SourceType.STDIN:
            return _load_stdin(source)
        elif source_type == SourceType.FILE:
            return _load_file(source)
        elif source_type in (SourceType.DIRECTORY, SourceType.REPO):
            return _load_repo(
                source,
                source_type=source_type,
                strategy=repo_strategy,
                budget_tokens=budget_tokens,
                include=include,
                exclude=exclude,
                model=model,
                diff_base=diff_base,
            )
        elif source_type == SourceType.URL:
            return _load_url(source, model=model)
        else:
            return SourceResult(
                path=source,
                source_type=source_type,
                error=f"Unknown source type: {source_type}",
            )
    except Exception as e:
        return SourceResult(
            path=source,
            source_type=source_type,
            error=str(e),
        )


def _load_stdin(source: str) -> SourceResult:
    """Read from stdin."""
    if sys.stdin.isatty():
        return SourceResult(
            path=source,
            source_type=SourceType.STDIN,
            error="No data on stdin",
        )

    content = sys.stdin.read()
    return SourceResult(
        path="stdin",
        source_type=SourceType.STDIN,
        content=content,
    )


def _load_file(source: str) -> SourceResult:
    """Read a plain text file."""
    p = Path(source)

    if not p.exists():
        return SourceResult(
            path=source,
            source_type=SourceType.FILE,
            error="File not found",
        )

    if _is_binary(p):
        return SourceResult(
            path=source,
            source_type=SourceType.FILE,
            error=_binary_hint(p),
        )

    # Warn for large files
    size = p.stat().st_size
    if size > LARGE_FILE_THRESHOLD:
        console.print(f"[yellow]Warning: {p.name} is {size / (1024 * 1024):.1f} MB[/yellow]")

    # Try UTF-8 first, fall back to latin-1
    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = p.read_text(encoding="latin-1")
        except Exception as e:
            return SourceResult(
                path=source,
                source_type=SourceType.FILE,
                error=f"Encoding error: {e}",
            )

    return SourceResult(
        path=source,
        source_type=SourceType.FILE,
        content=content,
        metadata={"size_bytes": size, "encoding": "utf-8"},
    )


def _load_repo(
    source: str,
    *,
    source_type: SourceType,
    strategy: RepoStrategy,
    budget_tokens: int | None,
    include: set[str] | None,
    exclude: set[str] | None,
    model: str | None,
    diff_base: str | None = None,
) -> SourceResult:
    """Load a directory/repo via repo.py."""
    from ctx.repo import load_repo

    result = load_repo(
        source,
        strategy=strategy,
        budget_tokens=budget_tokens,
        include=include,
        exclude=exclude,
        model=model,
        diff_base=diff_base,
    )
    # Override source_type to match what was detected
    result.source_type = source_type
    return result


def _load_url(source: str, *, model: str | None = None) -> SourceResult:
    """Load a URL via gitingest (git repos only)."""
    # Check if it looks like a git repo URL
    git_hosts = ("github.com", "gitlab.com", "bitbucket.org")
    is_git = any(host in source for host in git_hosts)

    if not is_git:
        return SourceResult(
            path=source,
            source_type=SourceType.URL,
            error="ctx only supports git repository URLs. For raw files, download first.",
        )

    try:
        from gitingest import ingest
    except ImportError:
        return SourceResult(
            path=source,
            source_type=SourceType.URL,
            error='Repo support requires gitingest. Install with: pip install "ctx[repo]"',
        )

    try:
        summary, _tree, content = ingest(source)
        from ctx.tokens import count_tokens

        tokens = count_tokens(content or "", model)
        return SourceResult(
            path=source,
            source_type=SourceType.URL,
            content=content or "",
            tokens=tokens,
            metadata={"summary": summary},
        )
    except Exception as e:
        return SourceResult(
            path=source,
            source_type=SourceType.URL,
            error=f"Failed to fetch URL: {e}",
        )
