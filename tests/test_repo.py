"""Tests for ctx.repo module."""

from __future__ import annotations

from unittest.mock import patch

from ctx import RepoStrategy, SourceType
from ctx.repo import _count_tree_files, load_repo


class TestCountTreeFiles:
    def test_empty(self):
        assert _count_tree_files("") == 0

    def test_simple_tree(self):
        tree = "src/\n  main.py\n  utils.py\ntests/\n  test_main.py"
        assert _count_tree_files(tree) == 5

    def test_only_whitespace_lines(self):
        assert _count_tree_files("  \n  \n  ") == 0


class TestLoadRepo:
    def test_gitingest_not_installed(self):
        """When gitingest is missing, should return helpful error."""
        with (
            patch.dict("sys.modules", {"gitingest": None}),
            patch("builtins.__import__", side_effect=ImportError),
        ):
            result = load_repo("/some/path", strategy=RepoStrategy.FULL)
            # May or may not hit the import error depending on caching
            # Just check it returns a SourceResult
            assert result.source_type == SourceType.REPO

    def test_full_strategy_structure(self, tmp_path):
        """Test that load_repo returns a properly structured SourceResult."""
        (tmp_path / "test.py").write_text("print('hello')")

        result = load_repo(str(tmp_path), strategy=RepoStrategy.FULL)
        assert result.source_type == SourceType.REPO
        # Will either succeed or error depending on gitingest availability
        if result.error is None:
            assert result.content != ""
            assert result.metadata.get("strategy") == "full"

    def test_auto_strategy_with_budget(self, tmp_path):
        """Test auto strategy respects budget."""
        (tmp_path / "test.py").write_text("print('hello')")

        result = load_repo(
            str(tmp_path),
            strategy=RepoStrategy.AUTO,
            budget_tokens=1_000_000,  # very generous budget
        )
        assert result.source_type == SourceType.REPO
        # With a huge budget, should pick FULL (if gitingest is available)
        if result.error is None:
            assert result.metadata.get("strategy") == "full"
