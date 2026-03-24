"""Tests for ctx.format module."""

from ctx import SourceResult, SourceType
from ctx.format import assemble, format_source


class TestFormatSource:
    def test_with_tags(self):
        result = SourceResult(
            path="proposal.md",
            source_type=SourceType.FILE,
            content="This is a proposal.",
        )
        out = format_source(result, 1, use_tags=True)
        assert '<document index="1">' in out
        assert "<source>proposal.md</source>" in out
        assert "<document_content>" in out
        assert "This is a proposal." in out
        assert "</document_content>" in out
        assert "</document>" in out

    def test_without_tags(self):
        result = SourceResult(
            path="proposal.md",
            source_type=SourceType.FILE,
            content="This is a proposal.",
        )
        out = format_source(result, 1, use_tags=False)
        assert out == "# proposal.md\nThis is a proposal."

    def test_uses_name_if_set(self):
        result = SourceResult(
            path="/long/path/proposal.md",
            source_type=SourceType.FILE,
            content="Content.",
            name="My Proposal",
        )
        out = format_source(result, 1, use_tags=True)
        assert "<source>My Proposal</source>" in out

    def test_indexing(self):
        result = SourceResult(
            path="file.txt",
            source_type=SourceType.FILE,
            content="Hello.",
        )
        out = format_source(result, 5, use_tags=True)
        assert '<document index="5">' in out


class TestAssemble:
    def test_single_source_with_tags(self):
        results = [
            SourceResult(
                path="file.txt",
                source_type=SourceType.FILE,
                content="Hello.",
            )
        ]
        out = assemble(results)
        assert out.startswith("<documents>")
        assert out.endswith("</documents>")
        assert '<document index="1">' in out

    def test_multiple_sources(self):
        results = [
            SourceResult(path="a.txt", source_type=SourceType.FILE, content="AAA"),
            SourceResult(path="b.txt", source_type=SourceType.FILE, content="BBB"),
        ]
        out = assemble(results)
        assert '<document index="1">' in out
        assert '<document index="2">' in out
        assert "AAA" in out
        assert "BBB" in out

    def test_errored_source_skipped(self):
        results = [
            SourceResult(path="good.txt", source_type=SourceType.FILE, content="Good"),
            SourceResult(
                path="bad.txt",
                source_type=SourceType.FILE,
                error="File not found",
            ),
        ]
        out = assemble(results)
        assert '<document index="1">' in out
        assert "Good" in out
        assert '<!-- source "bad.txt" skipped: File not found -->' in out
        assert '<document index="2">' not in out

    def test_empty_content_skipped(self):
        results = [
            SourceResult(path="empty.txt", source_type=SourceType.FILE, content=""),
        ]
        out = assemble(results)
        assert "Empty content" in out

    def test_no_tags_mode(self):
        results = [
            SourceResult(path="a.txt", source_type=SourceType.FILE, content="AAA"),
            SourceResult(path="b.txt", source_type=SourceType.FILE, content="BBB"),
        ]
        out = assemble(results, use_tags=False)
        assert "<documents>" not in out
        assert "# a.txt" in out
        assert "# b.txt" in out
        assert "---" in out  # default separator

    def test_custom_separator(self):
        results = [
            SourceResult(path="a.txt", source_type=SourceType.FILE, content="AAA"),
            SourceResult(path="b.txt", source_type=SourceType.FILE, content="BBB"),
        ]
        out = assemble(results, use_tags=False, separator="\n===\n")
        assert "\n===\n" in out
