"""Tests for ctx.cli module."""

import json

from typer.testing import CliRunner

from ctx.cli import app

runner = CliRunner()


class TestCLIBasic:
    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_no_args(self):
        result = runner.invoke(app, [])
        # Should show help or error
        assert result.exit_code == 0 or result.exit_code == 2

    def test_single_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello from test file")
        result = runner.invoke(app, [str(f)])
        assert result.exit_code == 0
        assert "Hello from test file" in result.stdout
        assert "<documents>" in result.stdout

    def test_multiple_files(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("Content A")
        f2.write_text("Content B")
        result = runner.invoke(app, [str(f1), str(f2)])
        assert result.exit_code == 0
        assert "Content A" in result.stdout
        assert "Content B" in result.stdout
        assert '<document index="1">' in result.stdout
        assert '<document index="2">' in result.stdout

    def test_nonexistent_file(self):
        result = runner.invoke(app, ["/nonexistent/file.txt"])
        # Single source fails -> exit code 1
        assert result.exit_code == 1

    def test_mixed_good_and_bad(self, tmp_path):
        f = tmp_path / "good.txt"
        f.write_text("Good content")
        result = runner.invoke(app, [str(f), "/nonexistent/bad.txt"])
        assert result.exit_code == 0
        assert "Good content" in result.stdout


class TestCLIFlags:
    def test_no_tags(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello")
        result = runner.invoke(app, [str(f), "--no-tags"])
        assert result.exit_code == 0
        assert "<documents>" not in result.stdout
        assert "# " in result.stdout

    def test_summary_flag(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello")
        result = runner.invoke(app, [str(f), "--summary"])
        assert result.exit_code == 0
        # Summary goes to stderr, content to stdout
        assert "Hello" in result.stdout

    def test_json_output(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello from JSON test")
        result = runner.invoke(app, [str(f), "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "output" in data
        assert "sources" in data
        assert "total_tokens" in data
        assert len(data["sources"]) == 1
        assert data["sources"][0]["path"] == str(f)

    def test_budget_within(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Short text")
        result = runner.invoke(app, [str(f), "--budget", "100000"])
        assert result.exit_code == 0

    def test_budget_over(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("word " * 10000)  # ~10k tokens
        result = runner.invoke(app, [str(f), "--budget", "10", "--output-format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["over_budget"] is True

    def test_invalid_strategy(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello")
        result = runner.invoke(app, [str(f), "--repo-strategy", "invalid"])
        assert result.exit_code == 2

    def test_invalid_output_format(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello")
        result = runner.invoke(app, [str(f), "--output-format", "xml"])
        assert result.exit_code == 2

    def test_duplicate_stdin(self):
        result = runner.invoke(app, ["-", "-"])
        assert result.exit_code == 2


class TestCLIIntegration:
    def test_directory_as_source(self, tmp_path):
        (tmp_path / "file1.txt").write_text("Content 1")
        (tmp_path / "file2.txt").write_text("Content 2")
        result = runner.invoke(app, [str(tmp_path)])
        # Should work if gitingest is installed, otherwise error
        # Either way, should not crash
        assert result.exit_code in (0, 1)

    def test_binary_file_skipped(self, tmp_path):
        txt = tmp_path / "good.txt"
        txt.write_text("Good content")
        binary = tmp_path / "bad.png"
        binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")

        result = runner.invoke(app, [str(txt), str(binary)])
        assert result.exit_code == 0
        assert "Good content" in result.stdout
        assert "skipped" in result.stdout.lower() or "binary" in result.stdout.lower()
