"""Tests for repolens/ai/client.py, prompts.py, and executor.py."""

import os
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from repolens.ai.client import CompletionResult, RepolensClient


def _cr(text: str, input_tokens: int, output_tokens: int,
        cache_read: int = 0, cache_creation: int = 0) -> CompletionResult:
    """Short-form factory for CompletionResult instances in test mocks."""
    return CompletionResult(text, input_tokens, output_tokens, cache_read, cache_creation)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    text: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
):
    """Build a mock Anthropic messages.create() response.

    Cache fields default to 0 to mirror a non-caching call; pass explicit
    values to exercise the cache-aware paths.
    """
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
    )
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
        assert client._default_model == "claude-opus-4-7"

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

    def test_returns_completion_result_named_tuple(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("hello", 10, 5)
        result = repolens_client.complete("what is 2+2")
        # CompletionResult is a NamedTuple with 5 fields.
        assert isinstance(result, tuple)
        assert len(result) == 5
        assert hasattr(result, "text")
        assert hasattr(result, "input_tokens")
        assert hasattr(result, "output_tokens")
        assert hasattr(result, "cache_read_tokens")
        assert hasattr(result, "cache_creation_tokens")

    def test_return_types(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("hello", 10, 5)
        result = repolens_client.complete("hi")
        assert isinstance(result.text, str)
        assert isinstance(result.input_tokens, int)
        assert isinstance(result.output_tokens, int)
        assert isinstance(result.cache_read_tokens, int)
        assert isinstance(result.cache_creation_tokens, int)

    def test_returns_correct_values(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("answer", 42, 7)
        result = repolens_client.complete("question")
        assert result.text == "answer"
        assert result.input_tokens == 42
        assert result.output_tokens == 7
        assert result.cache_read_tokens == 0
        assert result.cache_creation_tokens == 0

    def test_captures_cache_read_tokens(self, client):
        """Cache read tokens from usage must flow through to the result."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response(
            "ok", 100, 20, cache_read_input_tokens=900
        )
        result = repolens_client.complete("hi")
        assert result.cache_read_tokens == 900

    def test_captures_cache_creation_tokens(self, client):
        """Cache creation tokens from usage must flow through to the result."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response(
            "ok", 100, 20, cache_creation_input_tokens=1500
        )
        result = repolens_client.complete("hi")
        assert result.cache_creation_tokens == 1500

    def test_cache_fields_default_to_zero_when_missing_from_usage(self, client):
        """Older SDKs omit cache_* fields — guard with getattr defaulting to 0."""
        repolens_client, mock_sdk = client
        bare_usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        bare_response = SimpleNamespace(
            content=[SimpleNamespace(text="ok")], usage=bare_usage
        )
        mock_sdk.messages.create.return_value = bare_response
        result = repolens_client.complete("hi")
        assert result.cache_read_tokens == 0
        assert result.cache_creation_tokens == 0

    def test_uses_default_model(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("hello")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-7"

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

    def test_bare_string_prompt_omits_system_block(self, client):
        """Bare-string form keeps backwards-compatible behaviour (no system)."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("bare")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    def test_tuple_prompt_splits_system_and_user(self, client):
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete(("sys text", "user text"))
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert call_kwargs["system"][0]["text"] == "sys text"
        assert call_kwargs["messages"][0]["content"] == "user text"

    def test_large_system_block_gets_cache_control(self, client):
        """System blocks above the min-tokens threshold get ephemeral caching."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        # 10000 characters → ~2500 tokens via the rough len//4 estimate,
        # comfortably over the 2048 floor used for every family.
        big_system = "x" * 10000
        repolens_client.complete((big_system, "u"), model="claude-opus-4-7")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert call_kwargs["system"][0].get("cache_control") == {"type": "ephemeral"}

    def test_small_system_block_skips_cache_control(self, client):
        """System blocks below the threshold are not cached (server would no-op)."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        tiny_system = "short"  # way under 2048 tokens
        repolens_client.complete((tiny_system, "u"), model="claude-opus-4-7")
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert "cache_control" not in call_kwargs["system"][0]

    def test_cache_false_disables_breakpoint(self, client):
        """cache=False must omit cache_control even on large system blocks."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        big_system = "x" * 10000
        repolens_client.complete(
            (big_system, "u"), model="claude-opus-4-7", cache=False
        )
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert "cache_control" not in call_kwargs["system"][0]

    def test_borderline_block_below_2048_tokens_skips_cache(self, client):
        """A block at ~1250 tokens (5000 chars / 4) is below the 2048 floor
        and must not get a cache breakpoint, regardless of model family."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        borderline = "x" * 5000  # ~1250 tokens
        repolens_client.complete(
            (borderline, "u"), model="claude-haiku-4-5"
        )
        call_kwargs = mock_sdk.messages.create.call_args.kwargs
        assert "cache_control" not in call_kwargs["system"][0]

    def test_no_real_api_call(self, client):
        """Verify mock intercepts — no network traffic."""
        repolens_client, mock_sdk = client
        mock_sdk.messages.create.return_value = _make_response("ok", 1, 1)
        repolens_client.complete("hello")
        mock_sdk.messages.create.assert_called_once()


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------


from repolens.ai.prompts import (  # noqa: E402
    dir_summary_prompt,
    file_summary_prompt,
    repo_summary_prompt,
    task_execution_prompt,
)


class TestFileSummaryPrompt:
    def test_returns_system_user_tuple(self):
        result = file_summary_prompt("src/foo.py", "def foo(): pass")
        assert isinstance(result, tuple)
        assert len(result) == 2
        system, user = result
        assert isinstance(system, str) and isinstance(user, str)
        assert len(system) > 0 and len(user) > 0

    def test_path_goes_in_user_block(self):
        system, user = file_summary_prompt("src/foo.py", "def foo(): pass")
        assert "src/foo.py" in user

    def test_content_goes_in_user_block(self):
        content = "def foo(): pass"
        system, user = file_summary_prompt("src/foo.py", content)
        assert content in user

    def test_system_is_invariant_across_calls(self):
        """System block must be identical regardless of file payload — this is
        what makes prompt caching effective."""
        sys1, _ = file_summary_prompt("a.py", "x")
        sys2, _ = file_summary_prompt("b.py", "completely different")
        assert sys1 == sys2

    def test_language_appears_in_user_block(self):
        system, user = file_summary_prompt(
            "src/foo.py", "def foo(): pass", language="Python"
        )
        assert "Python" in user

    def test_language_label_always_present_in_user(self):
        system, user = file_summary_prompt("src/foo.py", "def foo(): pass")
        assert "Language:" in user

    def test_no_api_calls_made(self):
        """Pure function — no I/O or network."""
        with patch("anthropic.Anthropic") as mock_sdk:
            file_summary_prompt("src/foo.py", "content")
            mock_sdk.assert_not_called()


class TestDirSummaryPrompt:
    def test_returns_system_user_tuple(self):
        result = dir_summary_prompt("src/utils", "foo.py: utility helpers")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_dir_path_goes_in_user_block(self):
        system, user = dir_summary_prompt("src/utils", "foo.py: utility helpers")
        assert "src/utils" in user

    def test_file_summaries_block_goes_in_user(self):
        block = "foo.py: utility helpers\nbar.py: constants"
        system, user = dir_summary_prompt("src/utils", block)
        assert block in user

    def test_dir_path_has_trailing_slash_in_user(self):
        system, user = dir_summary_prompt("src/utils", "block")
        assert "src/utils/" in user

    def test_system_is_invariant(self):
        sys1, _ = dir_summary_prompt("a/", "x")
        sys2, _ = dir_summary_prompt("b/c/", "y")
        assert sys1 == sys2


class TestRepoSummaryPrompt:
    def test_returns_system_user_tuple(self):
        result = repo_summary_prompt("src/: core\ntests/: suite")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_dir_summaries_block_goes_in_user(self):
        block = "src/: core logic\ntests/: test suite"
        system, user = repo_summary_prompt(block)
        assert block in user

    def test_system_is_invariant(self):
        sys1, _ = repo_summary_prompt("a")
        sys2, _ = repo_summary_prompt("b")
        assert sys1 == sys2


class TestTaskExecutionPrompt:
    def test_returns_system_user_tuple(self):
        result = task_execution_prompt("context here", "what does this repo do?")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_context_bundle_goes_in_system_for_caching(self):
        """Stable repo context lives in the system block so it can be cached
        across multiple tasks run against the same repo."""
        bundle = "unique-context-xyz"
        system, user = task_execution_prompt(bundle, "some task")
        assert bundle in system

    def test_task_description_goes_in_user_block(self):
        task = "unique-task-description-abc"
        system, user = task_execution_prompt("context", task)
        assert task in user

    def test_context_section_header_in_system(self):
        system, user = task_execution_prompt("ctx", "task")
        assert "=== REPOSITORY CONTEXT ===" in system

    def test_task_section_header_in_user(self):
        system, user = task_execution_prompt("ctx", "task")
        assert "=== TASK ===" in user

    def test_no_api_calls_made(self):
        """Pure function — no I/O or network."""
        with patch("anthropic.Anthropic") as mock_sdk:
            task_execution_prompt("ctx", "task")
            mock_sdk.assert_not_called()


# ---------------------------------------------------------------------------
# execute_task()
# ---------------------------------------------------------------------------

from repolens.ai.executor import execute_task  # noqa: E402
from repolens.db.repository import create_repo, get_run  # noqa: E402
from repolens.db.schema import init_db  # noqa: E402


def _make_initialised_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a schema-initialised SQLite connection in a temp file."""
    db_path = tmp_path / "test_executor.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _make_bundle(content: str = "repo context here"):
    """Minimal ContextBundle-like namespace accepted by execute_task."""
    return SimpleNamespace(content=content, file_paths=[], token_count=100)


class TestExecuteTaskSuccess:
    """Run lifecycle: run created before API call, updated to done on success."""

    @pytest.fixture
    def db_conn(self, tmp_path):
        conn = _make_initialised_conn(tmp_path)
        yield conn
        conn.close()

    @pytest.fixture
    def repo_id(self, db_conn, sample_repo_path):
        return create_repo(db_conn, str(sample_repo_path), "test-repo")

    def test_returns_run_id_and_result(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("answer text", 50, 20)
            result = execute_task(db_conn, repo_id, "ask", "what does this do?")

        assert "run_id" in result
        assert result["result"] == "answer text"
        assert result["prompt_tokens"] == 50
        assert result["completion_tokens"] == 20

    def test_run_created_before_api_call(self, db_conn, repo_id, monkeypatch):
        """Run row must exist in the DB before the AI client is called."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        captured_run_id: list[int] = []

        def fake_complete(prompt, model=None):
            # At this point the run row should already exist
            run = get_run(db_conn, 1)
            captured_run_id.append(run["id"] if run else None)
            return _cr("ok", 10, 5)

        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.side_effect = fake_complete
            execute_task(db_conn, repo_id, "ask", "some task")

        assert captured_run_id[0] is not None, "Run row was not present during API call"

    def test_run_status_done_after_success(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("done result", 30, 15)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["status"] == "done"

    def test_run_stores_result_text(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("stored result", 10, 5)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["result"] == "stored result"

    def test_run_stores_token_counts(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("text", 111, 222)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["prompt_tokens"] == 111
        assert run["completion_tokens"] == 222

    def test_run_stores_cache_tokens(self, db_conn, repo_id, monkeypatch):
        """Cache read + creation tokens from the API must land in the runs row."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr(
                "text", 100, 50, cache_read=800, cache_creation=1200
            )
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["cache_read_tokens"] == 800
        assert run["cache_creation_tokens"] == 1200
        # Return dict also surfaces cache fields
        assert result["cache_read_tokens"] == 800
        assert result["cache_creation_tokens"] == 1200

    def test_run_cache_tokens_default_to_zero(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("text", 10, 5)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["cache_read_tokens"] == 0
        assert run["cache_creation_tokens"] == 0

    def test_run_stores_cost(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("text", 100, 100)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["cost_usd"] is not None
        assert run["cost_usd"] > 0

    def test_model_default_from_config(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("REPOLENS_MODEL", "claude-haiku-test")
        import repolens.config as cfg
        import importlib
        importlib.reload(cfg)

        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("text", 10, 5)
            execute_task(db_conn, repo_id, "ask", "task desc")
            call_kwargs = MockClient.return_value.complete.call_args
            used_model = call_kwargs[1].get("model") or call_kwargs[0][1]

        # Reload config back to defaults for isolation
        importlib.reload(cfg)
        assert used_model == "claude-haiku-test"

    def test_model_override_passed_through(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("text", 10, 5)
            execute_task(
                db_conn, repo_id, "ask", "task desc", model="claude-override-model"
            )
            call_kwargs = MockClient.return_value.complete.call_args
            used_model = call_kwargs[1].get("model") or call_kwargs[0][1]

        assert used_model == "claude-override-model"

    def test_token_budget_passed_to_build_context(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch(
                "repolens.ai.executor.build_context", return_value=_make_bundle()
            ) as mock_build,
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = _cr("text", 10, 5)
            execute_task(db_conn, repo_id, "ask", "task desc", token_budget=8000)

        _, call_kwargs = mock_build.call_args
        assert call_kwargs.get("token_budget") == 8000 or mock_build.call_args[0][3] == 8000


class TestExecuteTaskFailure:
    """Error path: run updated to failed with error_message set, exception re-raised."""

    @pytest.fixture
    def db_conn(self, tmp_path):
        conn = _make_initialised_conn(tmp_path)
        yield conn
        conn.close()

    @pytest.fixture
    def repo_id(self, db_conn, sample_repo_path):
        return create_repo(db_conn, str(sample_repo_path), "test-repo")

    def test_exception_is_reraised(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.side_effect = RuntimeError("API down")
            with pytest.raises(RuntimeError, match="API down"):
                execute_task(db_conn, repo_id, "ask", "task desc")

    def test_run_status_failed_on_exception(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        run_id_holder: list[int] = []

        def fake_complete(prompt, model=None):
            raise ValueError("timeout")

        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.side_effect = fake_complete
            with pytest.raises(ValueError):
                result = execute_task(db_conn, repo_id, "ask", "task desc")

        # Fetch the run we know was created (it will be run id 1 for a fresh DB)
        run = get_run(db_conn, 1)
        assert run is not None
        assert run["status"] == "failed"

    def test_error_message_stored_on_failure(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.side_effect = RuntimeError(
                "connection refused"
            )
            with pytest.raises(RuntimeError):
                execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, 1)
        assert run["error_message"] == "connection refused"

    def test_run_created_even_when_build_context_fails(
        self, db_conn, repo_id, monkeypatch
    ):
        """Run row is logged before context build, so it exists even if build fails."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch(
            "repolens.ai.executor.build_context",
            side_effect=ValueError("repo not found"),
        ):
            with pytest.raises(ValueError):
                execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, 1)
        assert run is not None
        assert run["status"] == "failed"
        assert "repo not found" in run["error_message"]
