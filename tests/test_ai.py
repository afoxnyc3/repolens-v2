"""Tests for repolens/ai/client.py — RepolensClient wrapper."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from repolens.ai.client import RepolensClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(text: str, input_tokens: int, output_tokens: int):
    """Build a mock Anthropic messages.create() response."""
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    content_block = SimpleNamespace(text=text)
    return SimpleNamespace(content=[content_block], usage=usage)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestRepolensClientInit:
    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
            RepolensClient()

    def test_raises_not_sdk_error_when_api_key_missing(self, monkeypatch):
        """Must be a ValueError, not an SDK-level auth error."""
        import anthropic

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError):
            RepolensClient()

    def test_constructs_when_api_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.Anthropic"):
            client = RepolensClient()
        assert client is not None

    def test_default_model_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("REPOLENS_MODEL", "claude-haiku-4-5")
        with patch("anthropic.Anthropic"):
            client = RepolensClient()
        assert client._default_model == "claude-haiku-4-5"

    def test_default_model_fallback(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("REPOLENS_MODEL", raising=False)
        with patch("anthropic.Anthropic"):
            client = RepolensClient()
        assert client._default_model == "claude-opus-4-5"

    def test_default_max_tokens_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("REPOLENS_MAX_TOKENS", "1024")
        with patch("anthropic.Anthropic"):
            client = RepolensClient()
        assert client._default_max_tokens == 1024

    def test_default_max_tokens_fallback(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("REPOLENS_MAX_TOKENS", raising=False)
        with patch("anthropic.Anthropic"):
            client = RepolensClient()
        assert client._default_max_tokens == 4096


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("REPOLENS_MODEL", raising=False)
        monkeypatch.delenv("REPOLENS_MAX_TOKENS", raising=False)
        with patch("anthropic.Anthropic") as MockSdk:
            instance = MockSdk.return_value
            yield RepolensClient(), instance

    def test_returns_three_tuple(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("hello", 10, 5)
        result = repolens_client.complete("what is 2+2")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_return_types(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("hello", 10, 5)
        text, prompt_tokens, completion_tokens = repolens_client.complete("hi")
        assert isinstance(text, str)
        assert isinstance(prompt_tokens, int)
        assert isinstance(completion_tokens, int)

    def test_returns_correct_values(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("answer", 42, 7)
        text, prompt_tokens, completion_tokens = repolens_client.complete("question")
        assert text == "answer"
        assert prompt_tokens == 42
        assert completion_tokens == 7

    def test_uses_default_model(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("hello")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-5"

    def test_uses_default_max_tokens(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("hello")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 4096

    def test_model_override(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("hello", model="claude-haiku-4-5")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5"

    def test_max_tokens_override(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("hello", max_tokens=512)
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 512

    def test_prompt_passed_as_user_message(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("my prompt")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "my prompt"

    def test_no_real_api_call(self, client):
        """Verify mock intercepts — no network traffic."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("hello")
        mock_sdk.messages.create.assert_called_once()
