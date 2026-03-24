"""XML source tagging and assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ctx import SourceResult


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
    label = result.name or result.path

    if use_tags:
        return (
            f'<document index="{index}">\n'
            f"<source>{label}</source>\n"
            f"<document_content>\n"
            f"{result.content}\n"
            f"</document_content>\n"
            f"</document>"
        )
    else:
        return f"# {label}\n{result.content}"


def assemble(
    results: list[SourceResult],
    *,
    use_tags: bool = True,
    separator: str = "\n\n---\n\n",
) -> str:
    """Assemble all source results into a single output string.

    With tags: wraps in <documents>...</documents>.
    Sources are output in the order they were provided.
    Empty/errored sources are skipped with a comment.
    """
    parts: list[str] = []
    doc_index = 1

    for result in results:
        if result.error:
            if use_tags:
                parts.append(f'<!-- source "{result.path}" skipped: {result.error} -->')
            else:
                parts.append(f"# {result.path} [SKIPPED: {result.error}]")
            continue

        if not result.content:
            if use_tags:
                parts.append(f'<!-- source "{result.path}" skipped: Empty content -->')
            else:
                parts.append(f"# {result.path} [SKIPPED: Empty content]")
            continue

        parts.append(format_source(result, doc_index, use_tags))
        doc_index += 1

    if use_tags:
        inner = "\n\n".join(parts)
        return f"<documents>\n{inner}\n</documents>"
    else:
        return separator.join(parts)
