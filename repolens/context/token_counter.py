"""Token counting and cost estimation utilities for repolens context engine.

Counting strategy
-----------------
:func:`count_tokens` defaults to the local tiktoken estimator — fast, no
network, adequate for packing decisions.  Pass ``accurate=True`` (or set
``REPOLENS_ACCURATE_TOKENS=1``) to route through the Anthropic
``messages.count_tokens`` endpoint, which is authoritative for Claude
models.  Results are cached by content hash so a repeated run in the same
process doesn't re-hit the wire.

Pricing
-------
See the ``_PRICING`` table for the rate card.  Cache-aware accounting is
in :func:`estimate_cost_detailed` (0.1× cache read, 1.25× cache write for
the 5-minute TTL — see ADR-004 for rationale).
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _env_accurate_default() -> bool:
    """Return True when REPOLENS_ACCURATE_TOKENS selects accurate counting."""
    return os.environ.get("REPOLENS_ACCURATE_TOKENS", "").lower() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Local (tiktoken) estimator
# ---------------------------------------------------------------------------


def _count_local(text: str) -> int:
    """Local tiktoken estimate.  Falls back to len // 4 if tiktoken is absent."""
    try:
        import tiktoken  # noqa: PLC0415 — lazy import, may not be installed

        encoding = tiktoken.get_encoding("cl100k_base")
        count = len(encoding.encode(text))
        return max(count, 1)
    except (ImportError, Exception):  # pragma: no cover — tiktoken is in deps
        return max(len(text) // 4, 1)


# ---------------------------------------------------------------------------
# Accurate (Anthropic) counter with content-hash cache
# ---------------------------------------------------------------------------


_accurate_cache: dict[str, int] = {}


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _count_accurate(text: str, model: str | None = None) -> int:
    """Delegate to ``anthropic.Anthropic().messages.count_tokens``.

    Falls back to the local estimator when the SDK raises (e.g. no API key,
    network error, model unknown to the server).
    """
    key = _hash_text(text)
    cached = _accurate_cache.get(key)
    if cached is not None:
        return cached

    try:
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic()
        resolved_model = model or os.environ.get(
            "REPOLENS_MODEL", "claude-opus-4-7"
        )
        response = client.messages.count_tokens(
            model=resolved_model,
            messages=[{"role": "user", "content": text}],
        )
        # Response shape: {"input_tokens": N}
        count = int(getattr(response, "input_tokens", 0) or 0)
        if count <= 0:
            count = _count_local(text)
    except Exception:
        count = _count_local(text)

    _accurate_cache[key] = count
    return count


def _clear_accurate_cache() -> None:
    """Test helper — drop all cached counts."""
    _accurate_cache.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def count_tokens(
    text: str,
    *,
    accurate: bool | None = None,
    model: str | None = None,
) -> int:
    """Return the token count for *text*.

    Args:
        text: The content to count.  Empty strings return 1.
        accurate: Force the accurate path (Anthropic SDK) when True, or
            the local tiktoken path when False.  ``None`` (default) reads
            the ``REPOLENS_ACCURATE_TOKENS`` env var, defaulting to local.
        model: Model id used only by the accurate path.  Defaults to
            ``REPOLENS_MODEL`` env var then ``claude-opus-4-7``.

    Returns:
        A positive integer — always ≥1, even for empty strings.
    """
    if not text:
        return 1

    if accurate is None:
        accurate = _env_accurate_default()

    if accurate:
        return _count_accurate(text, model=model)

    return _count_local(text)


# ---------------------------------------------------------------------------
# Pricing table — USD per 1 million base tokens (input, output).
#
# Cache pricing is derived: cache_write (5-min TTL) = input × 1.25,
# cache_write (1-hr TTL)   = input × 2.0 (not used in MVP), and
# cache_read              = input × 0.1.  See ADR-004 for rationale and
# https://platform.claude.com/docs/en/build-with-claude/prompt-caching
# for the authoritative rate card.
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    # Claude 4.x (current generation, 2026-04)
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-opus-4-6":   (15.0, 75.0),
    "claude-opus-4-5":   (15.0, 75.0),
    "claude-sonnet-4-6": (3.0,  15.0),
    "claude-sonnet-4-5": (3.0,  15.0),
    "claude-haiku-4-5":  (0.8,   4.0),
    # Legacy / deprecated — retained so historical run rows keep estimating.
    "claude-haiku-3-5":  (0.8,   4.0),
}

_DEFAULT_PRICING = _PRICING["claude-sonnet-4-6"]

# Cache-rate multipliers (applied against the model's input price).
_CACHE_WRITE_5M_MULT = 1.25
_CACHE_READ_MULT = 0.1


def _pricing_for(model: str) -> tuple[float, float]:
    """Return (input_price_per_m, output_price_per_m) for *model*."""
    return _PRICING.get(model, _DEFAULT_PRICING)


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
) -> float:
    """Return the estimated USD cost for a single API call.

    Uses base input + output prices only.  For cache-aware accounting use
    :func:`estimate_cost_detailed`.  Unknown models fall back to Sonnet
    pricing.
    """
    input_price, output_price = _pricing_for(model)
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


def estimate_cost_detailed(
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    output_tokens: int,
    model: str,
) -> float:
    """Return the estimated USD cost accounting for prompt caching.

    Applies the standard Anthropic rate structure:
    - ``input_tokens`` billed at the model's input price (these are the
      tokens that were *not* served from cache).
    - ``cache_read_tokens`` billed at 10% of input price.
    - ``cache_creation_tokens`` billed at 125% of input price (5-minute
      TTL, the MVP default).
    - ``output_tokens`` billed at the model's output price.

    Unknown models fall back to Sonnet pricing.
    """
    input_price, output_price = _pricing_for(model)

    dollars_per_input = input_price / 1_000_000
    dollars_per_output = output_price / 1_000_000

    return (
        input_tokens * dollars_per_input
        + cache_read_tokens * dollars_per_input * _CACHE_READ_MULT
        + cache_creation_tokens * dollars_per_input * _CACHE_WRITE_5M_MULT
        + output_tokens * dollars_per_output
    )
