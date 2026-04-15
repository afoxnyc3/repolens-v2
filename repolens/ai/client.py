"""Anthropic API client wrapper for Repolens."""

import os

import anthropic


class RepolensClient:
    """Thin wrapper around the Anthropic SDK.

    Reads configuration from environment variables:
    - ANTHROPIC_API_KEY (required)
    - REPOLENS_MODEL (optional, default: claude-opus-4-5)
    - REPOLENS_MAX_TOKENS (optional, default: 4096)
    """

    DEFAULT_MODEL = "claude-opus-4-5"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=api_key)
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
        prompt: str,
        model: str = None,
        max_tokens: int = None,
    ) -> tuple[str, int, int]:
        """Send a prompt and return (response_text, prompt_tokens, completion_tokens).

        Args:
            prompt: The user prompt to send.
            model: Model override. Falls back to REPOLENS_MODEL env var or claude-opus-4-5.
            max_tokens: Max tokens override. Falls back to REPOLENS_MAX_TOKENS or 4096.

        Returns:
            Tuple of (response_text, prompt_tokens, completion_tokens).
        """
        resolved_model = model if model is not None else self._default_model
        resolved_max_tokens = (
            max_tokens if max_tokens is not None else self._default_max_tokens
        )

        response = self._client.messages.create(
            model=resolved_model,
            max_tokens=resolved_max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text
        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens

        return response_text, prompt_tokens, completion_tokens
