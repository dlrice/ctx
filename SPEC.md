# Technical Specification: `ctx` — Context Assembly Tool

**Version:** 0.1.0
**Language:** Python 3.10+
**Package Manager:** uv
**Architecture:** Typer + Rich + gitingest + litellm (token counting)
**Principle:** Assemble context from diverse sources into a single LLM-ready string

---

## 1. What This Tool Does

`ctx` takes one or more sources (files, directories, repos, URLs, stdin) and
assembles them into a single, well-structured text document on stdout. It is the
"context preparation" step before any LLM tool — `moe`, `claude`, `spec-kit`, or
anything else that consumes text.

It is a single CLI command. It has no UI, no daemon, no database. It reads
sources, extracts text, applies a sizing strategy, tags each source for
attribution, and writes to stdout in Anthropic's recommended `<documents>` XML format.

`ctx` has two modes:

- **Code mode**: Smart repo context assembly with token budgets and sizing strategies.
- **Document mode**: Plain file assembly with Anthropic XML formatting.

```bash
# Code: generate repo context for moe
ctx --repo . --budget 80000 > repo-context.txt

# Documents: assemble with Anthropic XML format
ctx proposal.md rfp.txt scoring-rubric.md > grant-context.txt

# Mixed: repo + extra files
ctx --repo . spec.md plan.md > full-context.txt
```

---

## 2. Design Decisions

### 2.1 Why a separate tool (not built into moe)

Context assembly and expert review are different concerns:

- **ctx** decides _what text to include_ — file reading, repo digesting,
  sizing strategy, source tagging.
- **moe** decides _what to do with text_ — fan out to experts, merge reviews.

Separating them means:

- `ctx` is useful without `moe` (pipe into `claude`, `cat`, `wc`, anything).
- `moe` stays simple — it always receives a string, never opens files.
- Each tool can evolve independently.

### 2.2 Why multiple positional sources

A grant review needs: proposal + RFP + scoring rubric + budget template. A code
review might need: the diff + the full module for context + the test file. Forcing
users to concatenate manually before calling the tool defeats the purpose.

`ctx` accepts N positional arguments. Each is a source. Sources can be mixed
types (file, directory, URL, stdin via `-`).

### 2.3 Why source attribution via XML tags

When multiple sources are assembled, the downstream LLM needs to know which text
came from where. XML tags provide unambiguous boundaries. `ctx` adopts Anthropic's
recommended `<documents>` format, the same standard used by `files-to-prompt --cxml`:

```xml
<documents>
  <document index="1">
    <source>proposal.md</source>
    <document_content>
    ...content...
    </document_content>
  </document>

  <document index="2">
    <source>rfp.txt</source>
    <document_content>
    ...content...
    </document_content>
  </document>
</documents>
```

This is the established Anthropic standard — LLMs are well-trained on this format.

### 2.4 Why smart repo sizing

A 50-file module and a 10,000-file monorepo need completely different treatment.
The naive approach (dump everything) either works perfectly or blows the context
window. The smart approach:

1. **Probe first**: run `gitingest.ingest(path)` and count tokens on the
   returned content via `litellm.token_counter`. This probe count is
   approximate (±10%) — strategy selection tolerates this variance.
2. **Decide strategy** based on a configurable token budget:
   - Under budget → full content (richest signal).
   - Over budget → tree map + targeted file content with include/exclude patterns.
   - Way over budget → tree map only (structural overview, no file content).

The user can also force a strategy via `--repo-strategy full|map|tree`.

### 2.5 Why gitingest

`gitingest` is the sole repo extraction library. It is a native Python package
(`pip install gitingest`), actively maintained, and purpose-built for converting
repositories into LLM-ready text.

- **API**: `ingest(source, include_patterns=..., exclude_patterns=...)` returns
  a `(summary, tree, content)` tuple.
- **Full dumps**: Call with no patterns → returns everything.
- **Filtered extraction**: Pass include/exclude glob patterns for targeted content.
- **Remote repos**: Accepts GitHub/GitLab URLs directly.
- **Async support**: `ingest_async()` available.

The `(summary, tree, content)` tuple maps cleanly onto our three strategies:
FULL uses `content` (all file contents), MAP uses `tree + content` (with
patterns), TREE uses only `tree` (structural overview).

Token counting is handled separately by `litellm.token_counter` rather than
relying on a repo tool's built-in counting. This gives us model-specific
accuracy and keeps the dependency boundary clean.

### 2.6 Why Typer + Rich (consistency with moe)

Same libraries as `moe`. Same CLI conventions. Same stderr-for-status,
stdout-for-content pattern. A user who knows one tool knows both.

### 2.7 Why LiteLLM for token counting

`litellm.token_counter(model, text)` uses the correct tokenizer per model. When
the user specifies `--model` (the target model they'll be sending context to),
ctx can report accurate token counts and enforce a token budget. Without
`--model`, falls back to tiktoken's `cl100k_base` (GPT-4 tokenizer) as a
reasonable default.

### 2.8 Why files-to-prompt compatibility

`files-to-prompt --cxml` already produces the Anthropic `<documents>` XML format
for assembling plain text files. `ctx` adopts the same output format for
consistency. For simple file assembly without repository context, users can use
either tool. `ctx` adds value through:

- **Smart repo sizing**: Probes repos and selects strategies (full/map/tree)
  based on token budgets and file counts.
- **Token counting and budgets**: Accurate token reporting per source and
  enforcement of budget constraints.
- **Mixed sources**: Handles repos + files together in one tool, with coherent
  XML output and telemetry.

---

## 3. Library Responsibility Map

| Concern                  | Library                     | Our code                                       |
| ------------------------ | --------------------------- | ---------------------------------------------- |
| CLI argument parsing     | **Typer**                   | Define function signatures with type hints     |
| Progress/status display  | **Rich** (Console, Status)  | Call `console.status()` during processing      |
| Summary table rendering  | **Rich** (Table)            | Build rows from source metadata                |
| Full repo dump           | **gitingest** (ingest)      | Call with no patterns, receive full content    |
| Filtered repo extraction | **gitingest** (ingest)      | Pass include/exclude patterns, receive content |
| Remote repo/URL fetching | **gitingest** (ingest)      | Pass URL, receive content                      |
| Token counting           | **litellm** (token_counter) | Count per source and total                     |
| XML output formatting    | **stdlib**                  | f-strings with XML tags                        |

**What we actually write:**

- `cli.py`: Typer app, source dispatch, budget enforcement. ~100 lines.
- `sources.py`: Source type detection and loading. ~80 lines.
- `repo.py`: Smart repo sizing strategy (gitingest). ~70 lines.
- `tokens.py`: Token counting + budget logic. ~25 lines.
- `format.py`: XML source tagging and assembly. ~30 lines.
- `display.py`: Rich console, summary table. ~50 lines.

Estimated total custom code: **~355 lines**.

---

## 4. Project Structure

```
ctx/
├── pyproject.toml
├── src/
│   └── ctx/
│       ├── __init__.py
│       ├── cli.py          # Typer app definition
│       ├── sources.py      # Source type detection + loading
│       ├── repo.py         # Smart repo sizing (gitingest)
│       ├── tokens.py       # Token counting + budget
│       ├── format.py       # XML source tagging + final assembly
│       └── display.py      # Rich console, summary table
└── tests/
    ├── conftest.py
    ├── test_sources.py
    ├── test_repo.py
    ├── test_tokens.py
    ├── test_format.py
    └── test_cli.py
```

---

## 5. Data Models

### 5.1 Source (internal, per-input)

```python
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    REPO = "repo"           # Explicit --repo flag
    URL = "url"
    STDIN = "stdin"


class RepoStrategy(str, Enum):
    """Strategy for handling repository/directory sources."""
    FULL = "full"           # Dump all file contents (gitingest, no patterns)
    MAP = "map"             # Tree structure + targeted file contents (gitingest with patterns)
    TREE = "tree"           # Tree structure only, no file contents (gitingest tree only)
    AUTO = "auto"           # Let ctx decide based on token budget


class SourceResult(BaseModel):
    """Result of loading a single source."""
    path: str               # Original path/URL as provided by user
    source_type: SourceType
    content: str            # Extracted text content
    tokens: int = 0         # Token count (populated after counting)
    name: str | None = None # Optional human label (from name:path syntax)
    metadata: dict = Field(default_factory=dict)
    # metadata examples:
    #   Repo: {"strategy": "full", "total_files": 142, "file_tree": "..."}
    #   File: {"size_bytes": 4096, "encoding": "utf-8"}
    error: str | None = None
```

### 5.2 Assembly Result (returned to CLI)

```python
class AssemblyResult(BaseModel):
    """Complete result of assembling all sources."""
    output: str                      # Final assembled text
    sources: list[SourceResult]      # Per-source metadata and telemetry
    total_tokens: int = 0
    budget_tokens: int | None = None # None = no budget set
    over_budget: bool = False
```

---

## 6. Module Specifications

### 6.1 `cli.py` — Typer Application

```python
import typer
from typing import Optional
from pathlib import Path

app = typer.Typer(help="Assemble context from multiple sources for LLM consumption")


@app.command()
def assemble(
    sources: list[str] = typer.Argument(
        ..., help="Sources: file paths, directories, URLs, or '-' for stdin"
    ),
    repo: Optional[str] = typer.Option(
        None, help="Repository path or URL (uses smart sizing)"
    ),
    include: Optional[str] = typer.Option(
        None, help="Glob patterns to include (comma-separated, repo/dir only)"
    ),
    exclude: Optional[str] = typer.Option(
        None, help="Glob patterns to exclude (comma-separated, repo/dir only)"
    ),
    repo_strategy: str = typer.Option(
        "auto", "--repo-strategy",
        help="Repo sizing: auto|full|map|tree"
    ),
    budget: Optional[int] = typer.Option(
        None, help="Target token budget. Triggers smart sizing for repos."
    ),
    model: Optional[str] = typer.Option(
        None, help="Target LLM model for accurate token counting"
    ),
    no_tags: bool = typer.Option(
        False, "--no-tags",
        help="Output raw concatenation without XML source tags"
    ),
    separator: str = typer.Option(
        "\n\n---\n\n",
        help="Separator between sources when --no-tags is used"
    ),
    summary: bool = typer.Option(
        False, "--summary", "-s",
        help="Print source summary table to stderr"
    ),
    output_format: str = typer.Option(
        "text", "--output-format",
        help="Output format: text|json"
    ),
    copy: bool = typer.Option(
        False, "--copy", "-c",
        help="Copy output to clipboard (in addition to stdout)"
    ),
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=version_callback, is_eager=True
    ),
):
    """Assemble context from multiple sources into a single LLM-ready document."""
```

**Behaviour:**

- All positional arguments are treated as sources. Type is auto-detected:
  - Binary file (detected by null-byte check) → error with helpful extraction hint
  - Is a directory → directory/repo handling
  - Is `-` → stdin
  - Starts with `http://` or `https://` → URL (git repo via gitingest only;
    non-repo URLs exit with error: "ctx only supports git repository URLs")
  - Otherwise → plain file read
- The `--repo` flag explicitly provides a repo path and enables smart sizing
  (even if the path would otherwise be treated as a plain directory).
- If `--repo` is used alongside positional sources, the repo context is prepended
  before the other sources.
- `--include` and `--exclude` apply only to directory/repo sources. They are
  passed through to gitingest as glob patterns.
- `--budget` sets a target token count. For repos, this drives the auto strategy:
  if the full dump exceeds budget, fall back to map, then tree. For all sources
  combined, if total exceeds budget, print a warning (but still output — ctx
  doesn't truncate).
- Status/progress → stderr (Rich). Assembled context → stdout.
- Exit codes: 0 = success, 1 = all sources failed, 2 = config/input error,
  2 also for missing optional dependencies.
- `--output-format json` serializes `AssemblyResult` to stdout as JSON:
  ```json
  {
    "output": "...assembled text...",
    "sources": [
      {"path": "proposal.md", "source_type": "file", "tokens": 2340, ...},
      {"path": "rfp.txt", "source_type": "file", "tokens": 8100, ...}
    ],
    "total_tokens": 10440,
    "budget_tokens": null,
    "over_budget": false
  }
  ```
  Telemetry table still goes to stderr when `-s` is used, regardless of format.

**Composition with moe:**

**Code mode**: Generate repo context file, then pass it as a named context slot:

```bash
ctx --repo . --budget 80000 > repo-context.txt
moe diff.patch --repo repo-context.txt --spec spec.md --plan plan.md --runbook ...
```

**Document mode**: Assemble documents and pass as context:

```bash
ctx proposal.md rfp.txt rubric.txt > grant-context.txt
moe proposal.md --context grant-context.txt --runbook ...
```

**Note**: For simple file assembly without repos, `files-to-prompt --cxml` works
identically to `ctx` and outputs the same `<documents>` format. `ctx` adds value
through repo support, token budgeting, and mixed file+repo sources.

### 6.2 `sources.py` — Source Detection & Loading

```python
def detect_type(source: str) -> SourceType:
    """Auto-detect source type from the string.

    Detection order:
      1. '-'                          → STDIN (only one '-' allowed per invocation)
      2. Starts with http:// https:// → URL
      3. Is a directory on disk       → DIRECTORY
      4. Is a file on disk            → FILE (binary files detected and rejected)
      5. Otherwise                    → error (exit code 2)

    Binary detection: read first 8KB, check for null bytes. If binary, return
    an error with a helpful message. For known extensions like .pdf, .docx,
    .xlsx, the message suggests the appropriate extraction tool:
      "rfp.pdf is a binary file (PDF). Extract text first, e.g.:
       pdftext rfp.pdf | ctx - other-sources..."
    """


def load_source(
    source: str,
    source_type: SourceType,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    repo_strategy: RepoStrategy = RepoStrategy.AUTO,
    budget_tokens: int | None = None,
) -> SourceResult:
    """Load content from a single source.

    Dispatches to the appropriate loader based on source type.
    Returns a SourceResult (with error field set on failure, never raises).
    """
```

**Source loading details:**

| Source type | Loader               | Notes                                                                                                                                        |
| ----------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `FILE`      | `Path.read_text()`   | UTF-8 with fallback to latin-1. Binary files detected and rejected with helpful message.                                                     |
| `DIRECTORY` | `repo.load_repo()`   | Smart sizing strategy.                                                                                                                       |
| `REPO`      | `repo.load_repo()`   | Same as directory but explicitly flagged.                                                                                                    |
| `URL`       | `gitingest.ingest()` | Remote repo URL.                                                                                                                             |
| `STDIN`     | `sys.stdin.read()`   | Only one `-` source allowed per invocation. Read once at startup, before other sources. If multiple `-` are given, exit with error (code 2). |

### 6.3 `repo.py` — Smart Repo Sizing

```python
from gitingest import ingest

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

    AUTO strategy decision tree:
      1. Probe: run ingest(path) to get full content. Count tokens via
         litellm.token_counter (or tiktoken fallback). Probe timeout:
         30 seconds. If probe times out, skip to step 3b (MAP) with warning.
         Note: probe token count is approximate (±10%) — strategy
         selection tolerates this variance.
      2. If budget is set:
         a. total_tokens <= budget        → FULL (everything fits)
         b. total_tokens <= budget * 3    → MAP  (too big for full, but
            filtered content + tree may fit)
         c. total_tokens > budget * 3     → TREE (way too big, tree only)
      3. If no budget set:
         a. Count files from tree output (newline count as proxy)
         b. total_files < 500             → FULL
         c. total_files >= 500            → MAP

    When strategy is forced (not AUTO), skip the probe and go directly
    to the requested strategy.
    """
```

**Strategy implementations:**

All strategies use `gitingest.ingest()`. The returned `(summary, tree, content)`
tuple provides the building blocks:

- **FULL**: `ingest(path)` with no patterns. Return `content` (all file contents).
  Metadata includes `total_files` (from summary), `total_tokens`.

- **MAP**: `ingest(path, include_patterns=include, exclude_patterns=exclude)`.
  Return `tree + "\n\n" + content`. The tree provides structural overview, the
  content provides targeted file contents matching the patterns.

- **TREE**: `ingest(path)` but only return the `tree` component.
  No file contents — just structural overview for orientation.

**Default budget thresholds (configurable):**

```python
DEFAULT_FULL_THRESHOLD = 100_000     # tokens: below this, FULL is fine
DEFAULT_MAP_MULTIPLIER = 3           # if total > budget * 3, go TREE
DEFAULT_FILE_COUNT_THRESHOLD = 500   # files: above this, prefer MAP when no budget
```

### 6.4 `tokens.py` — Token Counting & Budget

```python
import litellm


def count_tokens(text: str, model: str | None = None) -> int:
    """Count tokens using the appropriate tokenizer.

    If model is provided, uses litellm.token_counter for model-specific counting.
    Otherwise falls back to tiktoken cl100k_base (GPT-4 family tokenizer).
    """


def check_budget(
    total_tokens: int,
    budget: int | None,
) -> tuple[bool, str]:
    """Check if total tokens exceed the budget.

    Returns (over_budget, message).
    If no budget is set, always returns (False, "").
    """
```

### 6.5 `format.py` — XML Source Tagging & Assembly

```python
def format_source(result: SourceResult, index: int, use_tags: bool = True) -> str:
    """Format a single source result for output.

    With tags (default — Anthropic documents format):
        <document index="1">
        <source>proposal.md</source>
        <document_content>
        ...content...
        </document_content>
        </document>

    Without tags (--no-tags):
        # proposal.md
        ...content...
    """


def assemble(
    results: list[SourceResult],
    *,
    use_tags: bool = True,
    separator: str = "\n\n---\n\n",
) -> str:
    """Assemble all source results into a single output string.

    With tags: wraps in <documents>...</documents>.
    Sources are output in the order they were provided.
    Empty/errored sources are skipped with a comment:
        <!-- source "bad-file.txt" skipped: File not found -->
    """
```

**Tag structure (Anthropic `<documents>` format):**

| Element                | Notes                                |
| ---------------------- | ------------------------------------ |
| `<documents>`          | Wrapper for all assembled documents  |
| `<document index="N">` | Container for each source, 1-indexed |
| `<source>`             | Source path or identifier            |
| `<document_content>`   | Extracted text content               |

### 6.6 `display.py` — Rich Console & Summary Table

```python
from rich.console import Console
from rich.table import Table

console = Console(stderr=True)


def print_summary(result: AssemblyResult) -> None:
    """Render source summary table to stderr.

    ┌────────────────────┬──────────┬────────┬────────┬──────────────────────┐
    │ Source             │ Type     │ Tokens │  Bytes │ Notes                │
    ├────────────────────┼──────────┼────────┼────────┼──────────────────────┤
    │ proposal.md        │ file     │  2,340 │  12 KB │                      │
    │ rfp.txt            │ file     │  8,100 │  42 KB │                      │
    │ scoring-rubric.md  │ file     │  1,200 │   6 KB │                      │
    │ ./ (repo)          │ repo     │ 45,000 │ 180 KB │ full strategy, 142 files │
    │ ❌ bad-file.txt    │ file     │      0 │      0 │ File not found       │
    ├────────────────────┼──────────┼────────┼────────┼──────────────────────┤
    │ Total              │          │ 56,640 │ 240 KB │ budget: 80,000 ✓     │
    └────────────────────┴──────────┴────────┴────────┴──────────────────────┘

    Bytes column shows the raw character/byte count of extracted content.
    Notes column shows:
      - Repos: strategy used + file count
      - Errors: error message
    If budget is set: total row shows budget vs actual with color (green=ok, red=over).
    """
```

---

## 7. CLI Usage Examples

### Code mode: Repository context

Generate repo context once, cache and reuse across multiple LLM invocations:

```bash
# Generate repo context (cache and reuse)
ctx --repo . --budget 80000 > repo-context.txt

# Regenerate after code changes (tests added, implementation done)
ctx --repo . --budget 80000 > repo-context.txt

# Large repo with filtered extraction
ctx --repo . --repo-strategy map --include "src/**/*.py" > repo-context.txt

# Remote repo
ctx --repo https://github.com/user/project > repo-context.txt
```

### Document mode: File assembly

Assemble documents once, cache and reuse for iterative review:

```bash
# Assemble grant context (cache and reuse)
ctx proposal.md rfp.txt scoring-rubric.txt > grant-context.txt

# Add approved sections over time
ctx rfa.txt rubric.txt specific-aims.md > grant-context.txt
ctx rfa.txt rubric.txt specific-aims.md research-strategy.md > grant-context.txt

# Mixed: repo context + document files
ctx --repo . spec.md plan.md > full-context.txt
```

### Piping to moe (legacy pattern)

For interactive one-shot review, pipe directly:

```bash
# Document review
ctx proposal.md rfp.txt rubric.txt | moe - --preset grant

# Code review with inline repo context
ctx --repo . --budget 80000 | moe - --preset code
```

### Output control

```bash
# No XML tags (plain concatenation)
ctx --no-tags proposal.md notes.md > combined.txt

# JSON output (for programmatic use)
ctx --output-format json proposal.md notes.md | jq '.total_tokens'

# Just check token counts
ctx -s proposal.md notes.md > /dev/null
```

---

## 8. Dependencies

```toml
[project]
name = "ctx"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "typer>=0.9",
    "rich>=13.0",
    "litellm>=1.0",
]

[project.optional-dependencies]
repo = [
    "gitingest>=0.1",
]
all = [
    "ctx[repo]",
]

[project.scripts]
ctx = "ctx.cli:main"
```

**Why optional dependencies:**

- Core `ctx` handles files and stdin with zero heavy dependencies.
- `ctx[repo]` adds gitingest for repo/directory handling.
- `ctx[all]` installs everything.

If a user tries to use a repo/directory source without the optional dependency,
ctx prints a clear error:
`"Repo support requires gitingest. Install with: pip install ctx[repo]"`

**Note:** `--copy` uses `subprocess.run(["pbcopy"])` on macOS,
`subprocess.run(["xclip", "-selection", "clipboard"])` on Linux, or
`subprocess.run(["clip"], input=text)` on Windows. No additional dependencies.

---

## 9. Error Handling Strategy

| Scenario                      | Behaviour                                                                                                                                       |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| File not found                | Skip source, include XML comment, warn on stderr                                                                                                |
| Binary file detected          | Skip source with helpful message naming the file type and suggesting an extraction tool (e.g., "rfp.pdf is a binary file. Extract text first.") |
| gitingest not installed       | Clear error: "Repo support requires gitingest. Install with: pip install ctx[repo]"                                                             |
| Repo probe times out (>30s)   | Fall back to MAP strategy, warn on stderr                                                                                                       |
| Non-repo URL provided         | Exit code 2: "ctx only supports git repository URLs. For raw files, download first."                                                            |
| Single source fails           | Continue with remaining sources                                                                                                                 |
| All sources fail              | Exit code 1, print error summary                                                                                                                |
| Token budget exceeded         | Warning on stderr, still output (no truncation)                                                                                                 |
| Stdin read when not provided  | Error: "No data on stdin"                                                                                                                       |
| Encoding detection failure    | Try UTF-8 → latin-1 → skip with warning                                                                                                         |
| Duplicate `-` in sources      | Exit code 2: "Only one stdin source allowed"                                                                                                    |
| Same file in multiple sources | Included multiple times (no dedup — user intent)                                                                                                |
| Single file > 10 MB           | Warn on stderr, still include                                                                                                                   |

**Key principle:** ctx never truncates output. If the assembled context is too
large, it warns but lets the downstream tool (moe) handle it. The `--budget`
flag is advisory — it drives repo strategy selection and warning messages, not
content removal.

---

## 10. Testing Strategy

- **Unit tests per module**: Each module tested independently.
- **Source detection tests**: Verify correct type inference for all input patterns.
- **Binary detection tests**: Verify PDF, DOCX, images, etc. are detected as
  binary with helpful messages. Test boundary cases (UTF-8 with BOM, etc.).
- **Repo strategy tests**: Mock gitingest. Test auto strategy decision
  tree at various token counts. Test include/exclude pattern passthrough.
- **Format tests**: Verify XML tag generation with various metadata combinations.
  Test no-tags mode. Test error source handling (XML comments).
- **Token counting tests**: Verify litellm integration and fallback to tiktoken.
- **CLI tests**: Typer's `CliRunner` for end-to-end. Test mixed sources, flags,
  output formats.
- **Integration tests**: Small real directories + text files. No mocked
  libraries. Verify end-to-end assembly.

---

## 11. What This Spec Intentionally Excludes

- **No content summarization.** ctx assembles raw text. If you want an LLM to
  summarize before review, pipe through a separate tool.
- **No content truncation.** ctx warns about budget but never removes content.
  Truncation decisions belong to the consumer.
- **No caching.** Each invocation reads sources fresh. Caching belongs in CI/CD
  wrappers if needed.
- **No web search.** ctx assembles local/cached content only.
- **No web page scraping.** URLs must be git repository URLs (via gitingest).
  Non-repo URLs (raw HTTP pages, APIs, file downloads) are rejected with a
  clear error. General web scraping is a different tool.
- **No binary file extraction.** ctx handles text files only. PDFs, DOCX,
  images, and other binary formats require a dedicated extraction tool upstream.
  ctx detects binary files and suggests the appropriate tool.
- **No recursive URL fetching.** A URL is one source, not a crawl.
- **No file watching or live reload.** This is a one-shot CLI tool.
- **No hand-rolled argument parsing.** Typer handles it.
- **No hand-rolled table formatting.** Rich handles it.
- **No hand-rolled token estimation.** LiteLLM handles it.
- **No parallel source loading.** Sources are loaded sequentially in the order
  given. Simpler, deterministic, and stdin ordering is unambiguous. Parallel
  loading is future work if latency becomes an issue with many remote sources.
- **No deduplication.** If the same file appears in multiple sources (e.g., both
  as a positional arg and inside a repo), it is included each time. This is by
  design — the user controls what goes in.
