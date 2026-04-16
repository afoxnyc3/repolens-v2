"""Anthropic API client wrapper for Repolens."""

from __future__ import annotations

import os
from typing import NamedTuple

import anthropic


class CompletionResult(NamedTuple):
    """Outcome of a single ``client.complete()`` call.

    Fields:
        text: The assistant's response text.
        input_tokens: Base input tokens billed (excludes cache-read tokens).
        output_tokens: Output tokens billed.
        cache_read_tokens: Input tokens served from the prompt cache at the
            10% rate.  Zero when caching is off or the prefix was cold.
        cache_creation_tokens: Input tokens spent writing a new cache entry
            at the 1.25× (5-minute TTL) rate.  Zero when no cache_control
            breakpoint was included or the prefix fell below the minimum
            cacheable size for the model family.
    """

    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


# Minimum cacheable prefix size (in tokens) per model family.  Empirically
# the published 1024-token minimum is not enough for Opus 4.x to actually
# write a cache entry — observed cache_creation=0 at 1417 tokens, =N at
# 9403 tokens.  We use 2048 across the board as a conservative floor so
# small system blocks don't pay the cache-control marker round-trip cost
# without actually getting cached.  See ADR-004.
_MIN_CACHE_TOKENS_BY_FAMILY: dict[str, int] = {
    "opus": 2048,
    "sonnet": 2048,
    "haiku": 2048,
}
_DEFAULT_MIN_CACHE_TOKENS = 2048


def _min_cache_tokens_for(model: str) -> int:
    """Return the minimum cacheable prefix size for *model*.

    Uses a substring probe of the model id against known families; unknown
    families get the conservative default (1024 tokens).
    """
    m = model.lower()
    for family, threshold in _MIN_CACHE_TOKENS_BY_FAMILY.items():
        if family in m:
            return threshold
    return _DEFAULT_MIN_CACHE_TOKENS


class RepolensClient:
    """Thin wrapper around the Anthropic SDK.

    Reads configuration from environment variables:
    - ANTHROPIC_API_KEY (required)
    - REPOLENS_MODEL (optional, default: claude-opus-4-7)
    - REPOLENS_MAX_TOKENS (optional, default: 4096)
    - REPOLENS_TIMEOUT (optional, default: 60 seconds)
    - REPOLENS_MAX_RETRIES (optional, default: 2)
    """

    DEFAULT_MODEL = "claude-opus-4-7"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TIMEOUT = 60
    DEFAULT_MAX_RETRIES = 2

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        timeout = int(os.environ.get("REPOLENS_TIMEOUT", self.DEFAULT_TIMEOUT))
        max_retries = int(
            os.environ.get("REPOLENS_MAX_RETRIES", self.DEFAULT_MAX_RETRIES)
        )
        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._default_model = os.environ.get("REPOLENS_MODEL", self.DEFAULT_MODEL)
        raw_tokens = os.environ.get("REPOLENS_MAX_TOKENS")
        self._default_max_tokens = (
            int(raw_tokens) if raw_tokens else self.DEFAULT_MAX_TOKENS
        )

    @property
    def model(self) -> str:
        """The default model identifier used by this client."""
        return self._default_model

    def complete(
        self,
        prompt: str | tuple[str, str],
        model: str | None = None,
        max_tokens: int | None = None,
        cache: bool = True,
    ) -> CompletionResult:
        """Send a prompt and return a :class:`CompletionResult`.

        Accepts either a bare user prompt (legacy form) or a ``(system,
        user)`` tuple from :mod:`repolens.ai.prompts`.  The structured form
        places stable instructions (and, for task execution, the
        repository context) in the ``system`` block, which is tagged
        ``cache_control={"type": "ephemeral"}`` when:

        1. ``cache`` is True (default), and
        2. the system block's rough token size meets the model-family
           minimum (1024 for Opus/Sonnet, 2048 for Haiku — smaller blocks
           are silently uncached by the server).

        Args:
            prompt: Either a user-role string, or a ``(system, user)`` pair.
            model: Model override. Falls back to REPOLENS_MODEL env var or
                claude-opus-4-7.
            max_tokens: Max tokens override. Falls back to REPOLENS_MAX_TOKENS
                or 4096.
            cache: When True and the ``system`` block is large enough,
                attach an ephemeral cache breakpoint.

        Returns:
            A :class:`CompletionResult` with response text and the full
            four-lane token accounting (input / output / cache_read /
            cache_creation).
        """
        resolved_model = model if model is not None else self._default_model
        resolved_max_tokens = (
            max_tokens if max_tokens is not None else self._default_max_tokens
        )

        # Normalise the prompt shape.
        if isinstance(prompt, tuple):
            system_text, user_text = prompt
        else:
            system_text, user_text = "", prompt

        request: dict = {
            "model": resolved_model,
            "max_tokens": resolved_max_tokens,
            "messages": [{"role": "user", "content": user_text}],
        }

        if system_text:
            system_block: dict = {"type": "text", "text": system_text}
            if cache and self._meets_cache_threshold(system_text, resolved_model):
                system_block["cache_control"] = {"type": "ephemeral"}
            request["system"] = [system_block]

        response = self._client.messages.create(**request)

        usage = response.usage

        # Concatenate every text block; tolerate non-text blocks (tool_use,
        # thinking, etc.) and empty content lists without crashing.
        text_parts = [
            getattr(block, "text", "")
            for block in (response.content or [])
            if getattr(block, "type", "text") == "text"
        ]
        text = "".join(text_parts)

        return CompletionResult(
            text=text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            # cache_* fields arrive only when caching is enabled on the
            # request; older SDKs omit them.  Default to 0 so accounting
            # stays consistent.
            cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            cache_creation_tokens=int(
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rough_token_count(text: str) -> int:
        """Cheap local estimate: len // 4.  Used only for the cache gate."""
        return max(1, len(text) // 4)

    def _meets_cache_threshold(self, system_text: str, model: str) -> bool:
        """Return True when the system block is big enough to be cacheable."""
        return self._rough_token_count(system_text) >= _min_cache_tokens_for(model)
