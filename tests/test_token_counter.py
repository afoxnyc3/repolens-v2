"""Tests for repolens/context/token_counter.py."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from repolens.context.token_counter import (
    _clear_accurate_cache,
    count_tokens,
    estimate_cost,
    estimate_cost_detailed,
)


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
# count_tokens accurate path (Anthropic SDK)
# ---------------------------------------------------------------------------


class TestCountTokensAccurate:
    """accurate=True routes through anthropic.messages.count_tokens."""

    def setup_method(self):
        _clear_accurate_cache()

    def test_accurate_delegates_to_sdk(self, monkeypatch):
        import anthropic
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        fake_response = SimpleNamespace(input_tokens=42)
        mock_client = MagicMock()
        mock_client.messages.count_tokens.return_value = fake_response

        monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=mock_client))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        result = count_tokens("hello", accurate=True)
        assert result == 42
        mock_client.messages.count_tokens.assert_called_once()

    def test_accurate_caches_by_content_hash(self, monkeypatch):
        import anthropic
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        call_counter = {"n": 0}

        def count_side_effect(**kwargs):
            call_counter["n"] += 1
            return SimpleNamespace(input_tokens=7)

        mock_client = MagicMock()
        mock_client.messages.count_tokens.side_effect = count_side_effect

        monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=mock_client))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        count_tokens("same text", accurate=True)
        count_tokens("same text", accurate=True)
        count_tokens("same text", accurate=True)
        assert call_counter["n"] == 1  # subsequent calls hit the cache

    def test_accurate_falls_back_to_local_on_error(self, monkeypatch):
        import anthropic
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.messages.count_tokens.side_effect = RuntimeError("network")
        monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=mock_client))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        # Should not raise — returns a local estimate >= 1.
        result = count_tokens("hello world", accurate=True)
        assert result >= 1

    def test_env_var_enables_accurate_path(self, monkeypatch):
        import anthropic
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        mock_client = MagicMock()
        mock_client.messages.count_tokens.return_value = SimpleNamespace(
            input_tokens=11
        )
        monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=mock_client))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("REPOLENS_ACCURATE_TOKENS", "1")

        result = count_tokens("hi")  # no explicit accurate= kwarg
        assert result == 11


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

    def test_recognises_current_model_ids(self):
        """Current Claude 4.x model IDs resolve to known pricing, not fallback."""
        # Opus: (15, 75) per M tokens
        opus = estimate_cost(1_000_000, 1_000_000, "claude-opus-4-7")
        assert abs(opus - 90.0) < 1e-9
        # Sonnet: (3, 15) per M tokens
        sonnet = estimate_cost(1_000_000, 1_000_000, "claude-sonnet-4-6")
        assert abs(sonnet - 18.0) < 1e-9
        # Haiku: (0.8, 4) per M tokens
        haiku = estimate_cost(1_000_000, 1_000_000, "claude-haiku-4-5")
        assert abs(haiku - 4.8) < 1e-9


# ---------------------------------------------------------------------------
# estimate_cost_detailed — cache-aware pricing
# ---------------------------------------------------------------------------


class TestEstimateCostDetailed:
    """Cache-aware cost model: 0.1× read, 1.25× creation, 1× input, 1× output."""

    def test_zero_inputs_returns_zero(self):
        assert estimate_cost_detailed(0, 0, 0, 0, "claude-opus-4-7") == 0.0

    def test_matches_estimate_cost_when_no_cache(self):
        """With zero cache tokens, detailed must match the simple form."""
        simple = estimate_cost(500, 200, "claude-opus-4-7")
        detailed = estimate_cost_detailed(500, 0, 0, 200, "claude-opus-4-7")
        assert abs(simple - detailed) < 1e-12

    def test_cache_read_charged_at_10pct_of_input(self):
        """Opus input = $15/M. 1,000,000 cache_read tokens → $1.50."""
        cost = estimate_cost_detailed(0, 1_000_000, 0, 0, "claude-opus-4-7")
        assert abs(cost - 1.5) < 1e-9

    def test_cache_creation_charged_at_125pct_of_input(self):
        """Opus input = $15/M. 1,000,000 cache_creation tokens → $18.75."""
        cost = estimate_cost_detailed(0, 0, 1_000_000, 0, "claude-opus-4-7")
        assert abs(cost - 18.75) < 1e-9

    def test_all_lanes_combined(self):
        """Opus: 100K input + 900K cache_read + 500K cache_creation + 50K output."""
        cost = estimate_cost_detailed(
            100_000, 900_000, 500_000, 50_000, "claude-opus-4-7"
        )
        # base input:      100_000 * 15  / 1M = 1.50
        # cache read:      900_000 * 15 * 0.10 / 1M = 1.35
        # cache creation:  500_000 * 15 * 1.25 / 1M = 9.375
        # output:           50_000 * 75 / 1M = 3.75
        expected = 1.50 + 1.35 + 9.375 + 3.75
        assert abs(cost - expected) < 1e-9

    def test_unknown_model_uses_sonnet_pricing(self):
        cost = estimate_cost_detailed(
            100_000, 100_000, 100_000, 100_000, "gpt-4-unknown"
        )
        sonnet = estimate_cost_detailed(
            100_000, 100_000, 100_000, 100_000, "claude-sonnet-4-6"
        )
        assert abs(cost - sonnet) < 1e-12
