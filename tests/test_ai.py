"""Tests for repolens/ai/client.py, prompts.py, and executor.py."""

import os
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

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
    def test_returns_non_empty_string(self):
        result = file_summary_prompt("src/foo.py", "def foo(): pass")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_path(self):
        result = file_summary_prompt("src/foo.py", "def foo(): pass")
        assert "src/foo.py" in result

    def test_includes_content(self):
        content = "def foo(): pass"
        result = file_summary_prompt("src/foo.py", content)
        assert content in result

    def test_includes_language_when_provided(self):
        result = file_summary_prompt("src/foo.py", "def foo(): pass", language="Python")
        assert "Python" in result

    def test_language_defaults_to_empty(self):
        result = file_summary_prompt("src/foo.py", "def foo(): pass")
        # Should not raise; language line present but blank
        assert "Language:" in result

    def test_no_api_calls_made(self):
        """Pure function — no I/O or network."""
        with patch("anthropic.Anthropic") as mock_sdk:
            file_summary_prompt("src/foo.py", "content")
            mock_sdk.assert_not_called()


class TestDirSummaryPrompt:
    def test_returns_non_empty_string(self):
        result = dir_summary_prompt("src/utils", "foo.py: utility helpers")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_dir_path(self):
        result = dir_summary_prompt("src/utils", "foo.py: utility helpers")
        assert "src/utils" in result

    def test_includes_file_summaries_block(self):
        block = "foo.py: utility helpers\nbar.py: constants"
        result = dir_summary_prompt("src/utils", block)
        assert block in result

    def test_dir_path_has_trailing_slash(self):
        result = dir_summary_prompt("src/utils", "block")
        assert "src/utils/" in result


class TestRepoSummaryPrompt:
    def test_returns_non_empty_string(self):
        result = repo_summary_prompt("src/: core logic\ntests/: test suite")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_dir_summaries_block(self):
        block = "src/: core logic\ntests/: test suite"
        result = repo_summary_prompt(block)
        assert block in result


class TestTaskExecutionPrompt:
    def test_returns_non_empty_string(self):
        result = task_execution_prompt("context here", "what does this repo do?")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_context_bundle(self):
        bundle = "unique-context-xyz"
        result = task_execution_prompt(bundle, "some task")
        assert bundle in result

    def test_includes_task_description(self):
        task = "unique-task-description-abc"
        result = task_execution_prompt("context", task)
        assert task in result

    def test_both_inputs_clearly_delimited(self):
        result = task_execution_prompt("ctx", "task")
        assert "=== REPOSITORY CONTEXT ===" in result
        assert "=== TASK ===" in result

    def test_context_appears_before_task(self):
        bundle = "CONTEXT_MARKER"
        task = "TASK_MARKER"
        result = task_execution_prompt(bundle, task)
        assert result.index(bundle) < result.index(task)

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
            MockClient.return_value.complete.return_value = ("answer text", 50, 20)
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
            return "ok", 10, 5

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
            MockClient.return_value.complete.return_value = ("done result", 30, 15)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["status"] == "done"

    def test_run_stores_result_text(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = ("stored result", 10, 5)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["result"] == "stored result"

    def test_run_stores_token_counts(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = ("text", 111, 222)
            result = execute_task(db_conn, repo_id, "ask", "task desc")

        run = get_run(db_conn, result["run_id"])
        assert run["prompt_tokens"] == 111
        assert run["completion_tokens"] == 222

    def test_run_stores_cost(self, db_conn, repo_id, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with (
            patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
            patch("repolens.ai.executor.RepolensClient") as MockClient,
        ):
            MockClient.return_value.complete.return_value = ("text", 100, 100)
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
            MockClient.return_value.complete.return_value = ("text", 10, 5)
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
            MockClient.return_value.complete.return_value = ("text", 10, 5)
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
            MockClient.return_value.complete.return_value = ("text", 10, 5)
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
