"""Tests for ctx.tokens module."""

from ctx.tokens import check_budget, count_tokens


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_simple_text(self):
        tokens = count_tokens("Hello, world!")
        assert tokens > 0
        assert tokens < 20  # reasonable bound

    def test_longer_text(self):
        text = "The quick brown fox jumps over the lazy dog. " * 100
        tokens = count_tokens(text)
        assert tokens > 100

    def test_with_model_fallback(self):
        """Even with an invalid model, should still return a count."""
        tokens = count_tokens("Hello, world!", model="nonexistent-model-xyz")
        assert tokens > 0


class TestCheckBudget:
    def test_no_budget(self):
        over, msg = check_budget(5000, None)
        assert over is False
        assert msg == ""

    def test_within_budget(self):
        over, msg = check_budget(5000, 10000)
        assert over is False
        assert "5,000" in msg
        assert "10,000" in msg

    def test_over_budget(self):
        over, msg = check_budget(15000, 10000)
        assert over is True
        assert "exceeded" in msg.lower()
        assert "5,000" in msg  # overage

    def test_exact_budget(self):
        over, _msg = check_budget(10000, 10000)
        assert over is False
