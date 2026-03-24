"""Token counting and budget logic."""

from __future__ import annotations


def count_tokens(text: str, model: str | None = None) -> int:
    """Count tokens using the appropriate tokenizer.

    If model is provided, uses litellm.token_counter for model-specific counting.
    Otherwise falls back to tiktoken cl100k_base (GPT-4 family tokenizer).
    """
    if not text:
        return 0

    if model:
        try:
            import litellm

            return litellm.token_counter(model=model, text=text)
        except Exception:
            pass

    # Fallback to tiktoken cl100k_base
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # Last resort: rough estimate (~4 chars per token)
        return len(text) // 4


def check_budget(total_tokens: int, budget: int | None) -> tuple[bool, str]:
    """Check if total tokens exceed the budget.

    Returns (over_budget, message).
    If no budget is set, always returns (False, "").
    """
    if budget is None:
        return False, ""

    if total_tokens > budget:
        overage = total_tokens - budget
        pct = (overage / budget) * 100
        return True, (
            f"Token budget exceeded: {total_tokens:,} tokens "
            f"(budget: {budget:,}, over by {overage:,} / {pct:.0f}%)"
        )

    remaining = budget - total_tokens
    return False, f"Within budget: {total_tokens:,} / {budget:,} tokens ({remaining:,} remaining)"
