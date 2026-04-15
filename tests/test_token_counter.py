"""Tests for repolens/context/token_counter.py."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from repolens.context.token_counter import count_tokens, estimate_cost


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_returns_positive_int_for_normal_text(self):
        result = count_tokens("Hello, world! This is a test sentence.")
        assert isinstance(result, int)
        assert result > 0

    def test_fallback_when_tiktoken_raises_import_error(self, monkeypatch):
        """If tiktoken is not importable, fall back to len(text) // 4."""
        text = "a" * 400  # 400 chars -> fallback gives 100

        # Remove tiktoken from sys.modules so the import fails inside count_tokens
        saved = sys.modules.pop("tiktoken", None)
        try:
            # Patch builtins.__import__ to raise ImportError for tiktoken
            real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

            import builtins

            original_import = builtins.__import__

            def _fake_import(name, *args, **kwargs):
                if name == "tiktoken":
                    raise ImportError("tiktoken not installed")
                return original_import(name, *args, **kwargs)

            monkeypatch.setattr(builtins, "__import__", _fake_import)

            result = count_tokens(text)
            assert isinstance(result, int)
            assert result > 0
            assert result == 100  # len("a"*400) // 4
        finally:
            if saved is not None:
                sys.modules["tiktoken"] = saved

    def test_returns_positive_int_for_empty_string(self):
        result = count_tokens("")
        assert isinstance(result, int)
        assert result >= 1

    def test_returns_positive_int_for_single_character(self):
        result = count_tokens("x")
        assert isinstance(result, int)
        assert result >= 1


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_returns_float_gte_zero(self):
        result = estimate_cost(0, 0, "claude-sonnet-4-5")
        assert isinstance(result, float)
        assert result >= 0.0

    def test_correct_for_opus(self):
        # 1M prompt + 1M completion: (1_000_000*15 + 1_000_000*75) / 1_000_000 = 90.0
        result = estimate_cost(1_000_000, 1_000_000, "claude-opus-4-5")
        assert abs(result - 90.0) < 1e-9

    def test_correct_for_sonnet(self):
        # 1M prompt + 1M completion: (1_000_000*3 + 1_000_000*15) / 1_000_000 = 18.0
        result = estimate_cost(1_000_000, 1_000_000, "claude-sonnet-4-5")
        assert abs(result - 18.0) < 1e-9

    def test_correct_for_haiku(self):
        # 1M prompt + 1M completion: (1_000_000*0.8 + 1_000_000*4) / 1_000_000 = 4.8
        result = estimate_cost(1_000_000, 1_000_000, "claude-haiku-3-5")
        assert abs(result - 4.8) < 1e-9

    def test_unknown_model_uses_sonnet_pricing(self):
        # Unknown model -> sonnet pricing (3.0 input, 15.0 output)
        sonnet_cost = estimate_cost(500_000, 200_000, "claude-sonnet-4-5")
        unknown_cost = estimate_cost(500_000, 200_000, "gpt-4-unknown-model")
        assert abs(sonnet_cost - unknown_cost) < 1e-9

    def test_zero_tokens_returns_zero(self):
        result = estimate_cost(0, 0, "claude-opus-4-5")
        assert result == 0.0

    def test_only_prompt_tokens(self):
        # 100 prompt tokens, 0 completion, sonnet: (100*3) / 1_000_000
        result = estimate_cost(100, 0, "claude-sonnet-4-5")
        assert abs(result - 0.0003) < 1e-10

    def test_only_completion_tokens(self):
        # 0 prompt, 100 completion, sonnet: (100*15) / 1_000_000
        result = estimate_cost(0, 100, "claude-sonnet-4-5")
        assert abs(result - 0.0015) < 1e-10
