"""Token counting and cost estimation utilities for repolens context engine."""

from __future__ import annotations


def count_tokens(text: str) -> int:
    """Return the token count for *text*.

    Tries tiktoken (cl100k_base encoding) first.  Falls back to a simple
    character-based estimate (len // 4) if tiktoken is unavailable or raises
    any error.  Always returns a positive integer — minimum 1.
    """
    if not text:
        return 1

    try:
        import tiktoken  # noqa: PLC0415 — lazy import, may not be installed

        encoding = tiktoken.get_encoding("cl100k_base")
        count = len(encoding.encode(text))
        return max(count, 1)
    except (ImportError, Exception):  # pragma: no cover — tiktoken IS installed in CI
        count = len(text) // 4
        return max(count, 1)


# ---------------------------------------------------------------------------
# Pricing table — USD per 1 million tokens (input, output)
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-5":    (15.0, 75.0),
    "claude-sonnet-4-5":  (3.0,  15.0),
    "claude-haiku-3-5":   (0.8,   4.0),
}

_DEFAULT_PRICING = _PRICING["claude-sonnet-4-5"]


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
) -> float:
    """Return the estimated USD cost for a single API call.

    Args:
        prompt_tokens:     Number of input / prompt tokens consumed.
        completion_tokens: Number of output / completion tokens generated.
        model:             Model identifier string.  Unknown models fall back
                           to claude-sonnet-4-5 pricing.

    Returns:
        Estimated cost in USD as a float.
    """
    input_price, output_price = _PRICING.get(model, _DEFAULT_PRICING)
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
