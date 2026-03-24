"""Test fixtures for ctx."""

from __future__ import annotations

import pytest


@pytest.fixture()
def tmp_dir(tmp_path):
    """Provide a temporary directory with some test files."""
    (tmp_path / "hello.txt").write_text("Hello, world!")
    (tmp_path / "notes.md").write_text("# Notes\n\nSome notes here.\n")
    (tmp_path / "data.csv").write_text("name,age\nAlice,30\nBob,25\n")
    return tmp_path


@pytest.fixture()
def binary_file(tmp_path):
    """Create a binary file for testing."""
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    return f


@pytest.fixture()
def pdf_file(tmp_path):
    """Create a fake PDF for testing binary detection."""
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\x00some binary content")
    return f


@pytest.fixture()
def large_file(tmp_path):
    """Create a large text file (~11 MB)."""
    f = tmp_path / "large.txt"
    f.write_text("x" * (11 * 1024 * 1024))
    return f
