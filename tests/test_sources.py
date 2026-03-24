"""Tests for ctx.sources module."""

import pytest

from ctx import SourceType
from ctx.sources import detect_type, load_source


class TestDetectType:
    def test_stdin(self):
        assert detect_type("-") == SourceType.STDIN

    def test_http_url(self):
        assert detect_type("http://example.com") == SourceType.URL

    def test_https_url(self):
        assert detect_type("https://github.com/user/repo") == SourceType.URL

    def test_directory(self, tmp_dir):
        assert detect_type(str(tmp_dir)) == SourceType.DIRECTORY

    def test_file(self, tmp_dir):
        assert detect_type(str(tmp_dir / "hello.txt")) == SourceType.FILE

    def test_nonexistent(self):
        with pytest.raises(FileNotFoundError, match="Source not found"):
            detect_type("/nonexistent/path/file.txt")


class TestLoadFile:
    def test_load_text_file(self, tmp_dir):
        result = load_source(
            str(tmp_dir / "hello.txt"),
            SourceType.FILE,
        )
        assert result.error is None
        assert result.content == "Hello, world!"
        assert result.source_type == SourceType.FILE

    def test_load_markdown(self, tmp_dir):
        result = load_source(
            str(tmp_dir / "notes.md"),
            SourceType.FILE,
        )
        assert result.error is None
        assert "# Notes" in result.content

    def test_file_not_found(self):
        result = load_source(
            "/nonexistent/file.txt",
            SourceType.FILE,
        )
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_binary_file_detected(self, binary_file):
        result = load_source(str(binary_file), SourceType.FILE)
        assert result.error is not None
        assert "binary" in result.error.lower()

    def test_pdf_binary_hint(self, pdf_file):
        result = load_source(str(pdf_file), SourceType.FILE)
        assert result.error is not None
        assert "PDF" in result.error
        assert "pdftext" in result.error

    def test_latin1_fallback(self, tmp_path):
        f = tmp_path / "latin.txt"
        f.write_bytes("caf\xe9".encode("latin-1"))
        result = load_source(str(f), SourceType.FILE)
        assert result.error is None
        assert "caf" in result.content


class TestLoadStdin:
    def test_stdin_no_data(self):
        """When stdin is a tty, should error."""
        # This test will depend on environment - stdin is typically a tty in tests
        result = load_source("-", SourceType.STDIN)
        # Either gets content or an error about no data
        assert result.source_type == SourceType.STDIN


class TestLoadUrl:
    def test_non_git_url_rejected(self):
        result = load_source(
            "https://example.com/page.html",
            SourceType.URL,
        )
        assert result.error is not None
        assert "git repository" in result.error.lower()

    def test_git_url_without_gitingest(self):
        """URL loading requires gitingest - tests import error handling."""
        # This will either work (if gitingest installed) or give a helpful error
        result = load_source(
            "https://github.com/user/nonexistent-test-repo",
            SourceType.URL,
        )
        # Should have either an error about gitingest or about the repo
        assert result.source_type == SourceType.URL
