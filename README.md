# ctx

**Assemble context from diverse sources into a single LLM-ready string.**

`ctx` takes one or more sources — files, directories, repos, URLs, or stdin — and assembles them into a well-structured text document on stdout. It is the "context preparation" step before any LLM tool: pipe into `claude`, `moe`, `cat`, `wc`, or anything else that consumes text.

```bash
# Assemble documents with Anthropic XML format
ctx proposal.md rfp.txt scoring-rubric.md > grant-context.txt

# Generate repo context with a token budget
ctx --repo . --budget 80000 > repo-context.txt

# Mixed: repo + extra files
ctx --repo . spec.md plan.md > full-context.txt
```

## Installation

Requires Python 3.10+.

```bash
# Core (files, stdin, token counting)
pip install .

# With repository support (adds gitingest)
pip install ".[repo]"

# Everything
pip install ".[all]"
```

## Two Modes

**Document mode** assembles plain files into Anthropic's `<documents>` XML format — the same format used by `files-to-prompt --cxml`:

```bash
ctx proposal.md rfp.txt rubric.txt > context.txt
```

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

**Code mode** adds smart repo context assembly with token budgets and sizing strategies:

```bash
ctx --repo . --budget 80000 > repo-context.txt
```

The tool probes the repo, counts tokens, and automatically selects the best strategy to fit your budget.

## Usage

```
ctx [OPTIONS] [SOURCES]...
```

Sources are positional arguments. Each is auto-detected as a file, directory, URL, or stdin (`-`). You can mix and match freely.

### Options

| Flag                                    | Description                                              |
| --------------------------------------- | -------------------------------------------------------- |
| `--repo PATH`                           | Repository path or URL (enables smart sizing)            |
| `--budget N`                            | Target token budget; drives repo strategy selection      |
| `--repo-strategy auto\|full\|map\|tree` | Force a specific repo strategy (default: `auto`)         |
| `--include PATTERNS`                    | Comma-separated glob patterns to include (repo/dir only) |
| `--exclude PATTERNS`                    | Comma-separated glob patterns to exclude (repo/dir only) |
| `--model NAME`                          | Target LLM model for accurate token counting             |
| `--no-tags`                             | Output raw concatenation without XML tags                |
| `--separator SEP`                       | Custom separator for `--no-tags` mode                    |
| `--summary`, `-s`                       | Print source summary table to stderr                     |
| `--output-format text\|json`            | Output format (default: `text`)                          |
| `--copy`, `-c`                          | Copy output to clipboard                                 |
| `--version`, `-V`                       | Print version and exit                                   |

### Examples

**Assemble documents for a grant review:**

```bash
ctx proposal.md rfp.txt scoring-rubric.txt > grant-context.txt
```

**Check token counts without producing output:**

```bash
ctx -s proposal.md notes.md > /dev/null
```

```
┌────────────────────┬──────────┬────────┬────────┬───────────────────────┐
│ Source             │ Type     │ Tokens │  Bytes │ Notes                 │
├────────────────────┼──────────┼────────┼────────┼───────────────────────┤
│ proposal.md        │ file     │  2,340 │  12 KB │                       │
│ notes.md           │ file     │  1,200 │   6 KB │                       │
├────────────────────┼──────────┼────────┼────────┼───────────────────────┤
│ Total              │          │  3,540 │  18 KB │                       │
└────────────────────┴──────────┴────────┴────────┴───────────────────────┘
```

**Repo context with budget enforcement:**

```bash
ctx --repo . --budget 80000 -s > repo-context.txt
```

The auto strategy probes the repo and picks the best fit:

- **full** — all file contents (repo fits within budget)
- **map** — file tree + filtered file contents (too big for full, but filtered content may fit)
- **tree** — file tree only, no contents (way too big)

**Large repo with filtered extraction:**

```bash
ctx --repo . --repo-strategy map --include "src/**/*.py" > repo-context.txt
```

**Remote repository:**

```bash
ctx --repo https://github.com/user/project > repo-context.txt
```

**Pipe from stdin:**

```bash
git diff | ctx - spec.md > review-context.txt
```

**JSON output for programmatic use:**

```bash
ctx --output-format json proposal.md notes.md | jq '.total_tokens'
```

The JSON format returns an `AssemblyResult` object:

```json
{
  "output": "...assembled text...",
  "sources": [
    {"path": "proposal.md", "source_type": "file", "tokens": 2340, ...},
    {"path": "notes.md", "source_type": "file", "tokens": 1200, ...}
  ],
  "total_tokens": 3540,
  "budget_tokens": null,
  "over_budget": false
}
```

**No XML tags (plain concatenation):**

```bash
ctx --no-tags proposal.md notes.md > combined.txt
```

**Copy to clipboard:**

```bash
ctx -c proposal.md notes.md
```

## Smart Repo Sizing

When using `--repo`, ctx selects a strategy to fit the content within your token budget. The decision tree for `auto` mode:

With a `--budget`:

| Condition             | Strategy                          |
| --------------------- | --------------------------------- |
| tokens <= budget      | **full** — everything fits        |
| tokens <= budget \* 3 | **map** — tree + filtered content |
| tokens > budget \* 3  | **tree** — structure only         |

Without a `--budget`:

| Condition    | Strategy |
| ------------ | -------- |
| < 500 files  | **full** |
| >= 500 files | **map**  |

You can override this with `--repo-strategy full|map|tree`.

All strategies use [gitingest](https://github.com/cyclotruc/gitingest) under the hood. The `ingest()` call returns a `(summary, tree, content)` tuple that maps cleanly onto the three strategies.

## Token Counting

Token counts are computed via [litellm](https://github.com/BerriAI/litellm). When `--model` is specified, litellm uses the correct tokenizer for that model. Without `--model`, it falls back to tiktoken's `cl100k_base` (GPT-4 family tokenizer).

The `--budget` flag is **advisory** — ctx never truncates output. If the assembled context exceeds the budget, it prints a warning to stderr but still outputs everything. Truncation decisions belong to the downstream consumer.

## Error Handling

ctx is designed to be resilient. Individual source failures don't stop the assembly — the tool continues with remaining sources and includes XML comments for skipped sources:

```xml
<!-- source "bad-file.txt" skipped: File not found -->
```

Binary files are detected (via null-byte check in the first 8KB) and rejected with helpful messages that suggest appropriate extraction tools:

```
rfp.pdf is a binary file (PDF). Extract text first, e.g.:
  pdftext rfp.pdf | ctx - other-sources...
```

Encoding is handled gracefully: UTF-8 first, then latin-1 fallback.

| Exit code | Meaning                      |
| --------- | ---------------------------- |
| 0         | Success                      |
| 1         | All sources failed           |
| 2         | Configuration or input error |

## Project Structure

```
ctx/
├── .gitignore
├── .python-version
├── pyproject.toml           # Single config: build, deps, ruff, mypy, pytest
├── README.md
├── src/
│   └── ctx/
│       ├── __init__.py      # Data models, enums, __all__ exports
│       ├── py.typed         # PEP 561 typed package marker
│       ├── cli.py           # Typer application and entry point
│       ├── sources.py       # Source type detection and loading
│       ├── repo.py          # Smart repo sizing via gitingest
│       ├── tokens.py        # Token counting (litellm) and budget logic
│       ├── format.py        # Anthropic XML formatting and assembly
│       └── display.py       # Rich summary table (stderr)
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_cli.py
    ├── test_format.py
    ├── test_repo.py
    ├── test_sources.py
    └── test_tokens.py
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev,all]"

# Run tests
pytest

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/
```

## Design Principles

- **stdout for content, stderr for status.** Assembled context goes to stdout. Progress messages, warnings, and the summary table go to stderr. This makes piping reliable.
- **Never truncate.** The `--budget` flag drives strategy selection and warnings, not content removal. The downstream tool decides what to do with oversized context.
- **Source order is preserved.** Sources appear in the output in the order you specify them. `--repo` content always comes first.
- **No deduplication.** If the same file appears in multiple sources, it is included each time. This is intentional — you control what goes in.
- **No caching.** Each invocation reads sources fresh. Caching belongs in CI/CD wrappers if needed.
- **Text only.** Binary files (PDFs, images, DOCX, etc.) are detected and rejected with helpful messages. Use a dedicated extraction tool upstream.

## License

MIT
