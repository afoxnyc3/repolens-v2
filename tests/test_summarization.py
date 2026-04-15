"""Tests for repolens/summarization/file_summarizer.py.

Covers:
- Cache hit: cached summary returned, no AI call made
- Cache miss: AI called, result stored, summary returned
- Content hash mismatch: stale cache skipped, AI re-called, new hash stored
- Large file: content truncated before the AI call
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from repolens.db.repository import get_summary, upsert_summary
from repolens.db.schema import init_db
from repolens.ingestion.scanner import FileRecord
from repolens.summarization.file_summarizer import (
    _CONTENT_CHAR_LIMIT,
    _language_for_extension,
    summarize_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path):
    """In-memory-style SQLite connection with schema initialised."""
    db_file = tmp_path / "test.db"
    init_db(db_path=db_file)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    # Insert a repo row so foreign keys don't blow up.
    conn.execute("INSERT INTO repos (id, path, name) VALUES (1, '/repo', 'test-repo')")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """A minimal fake repo directory with one source file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main(): pass\n")
    return repo


def _make_file_record(
    repo_root: str,
    relative_path: str = "main.py",
    extension: str = ".py",
    size_bytes: int = 17,
    mtime: int = 1700000000,
    content_hash: str = "abc123",
) -> FileRecord:
    return FileRecord(
        repo_root=repo_root,
        relative_path=relative_path,
        extension=extension,
        size_bytes=size_bytes,
        mtime=mtime,
        content_hash=content_hash,
    )


def _mock_client(
    summary: str = "A short summary.",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    model: str = "claude-test-model",
) -> MagicMock:
    """Return a mock RepolensClient whose .complete() returns fixed values."""
    client = MagicMock()
    client.complete.return_value = (summary, prompt_tokens, completion_tokens)
    client.model = model
    return client


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------


class TestCacheHit:
    def test_returns_cached_summary_without_ai_call(self, db, repo_dir):
        """When hash matches the cache, return stored summary, skip AI."""
        file_record = _make_file_record(str(repo_dir), content_hash="hash-v1")
        # Pre-seed the cache with a known summary.
        upsert_summary(
            db,
            repo_id=1,
            scope="file",
            target_path="main.py",
            summary="Cached summary text.",
            content_hash="hash-v1",
        )

        client = _mock_client()
        result = summarize_file(db, 1, file_record, client)

        assert result == "Cached summary text."
        client.complete.assert_not_called()

    def test_cache_hit_does_not_update_db(self, db, repo_dir):
        """A cache hit must not write a new row."""
        file_record = _make_file_record(str(repo_dir), content_hash="hash-v1")
        upsert_summary(
            db,
            repo_id=1,
            scope="file",
            target_path="main.py",
            summary="Original summary.",
            content_hash="hash-v1",
        )

        client = _mock_client(summary="New summary from AI.")
        summarize_file(db, 1, file_record, client)

        stored = get_summary(db, 1, "file", "main.py")
        assert stored["summary"] == "Original summary."


# ---------------------------------------------------------------------------
# Cache miss (no prior entry)
# ---------------------------------------------------------------------------


class TestCacheMiss:
    def test_calls_ai_client_on_miss(self, db, repo_dir):
        """With no cached entry the AI client must be called once."""
        file_record = _make_file_record(str(repo_dir))
        client = _mock_client(summary="Fresh summary.")

        summarize_file(db, 1, file_record, client)

        client.complete.assert_called_once()

    def test_returns_ai_summary_on_miss(self, db, repo_dir):
        file_record = _make_file_record(str(repo_dir))
        client = _mock_client(summary="Fresh summary.")

        result = summarize_file(db, 1, file_record, client)

        assert result == "Fresh summary."

    def test_stores_summary_in_db_on_miss(self, db, repo_dir):
        file_record = _make_file_record(str(repo_dir), content_hash="abc123")
        client = _mock_client(summary="Stored summary.", prompt_tokens=20, completion_tokens=8)

        summarize_file(db, 1, file_record, client)

        stored = get_summary(db, 1, "file", "main.py")
        assert stored is not None
        assert stored["summary"] == "Stored summary."

    def test_stores_correct_content_hash(self, db, repo_dir):
        file_record = _make_file_record(str(repo_dir), content_hash="myhash")
        client = _mock_client()

        summarize_file(db, 1, file_record, client)

        stored = get_summary(db, 1, "file", "main.py")
        assert stored["content_hash"] == "myhash"

    def test_stores_token_counts(self, db, repo_dir):
        file_record = _make_file_record(str(repo_dir))
        client = _mock_client(prompt_tokens=42, completion_tokens=7)

        summarize_file(db, 1, file_record, client)

        stored = get_summary(db, 1, "file", "main.py")
        assert stored["prompt_tokens"] == 42
        assert stored["completion_tokens"] == 7

    def test_stores_model_name(self, db, repo_dir):
        file_record = _make_file_record(str(repo_dir))
        client = _mock_client(model="claude-opus-4-5")

        summarize_file(db, 1, file_record, client)

        stored = get_summary(db, 1, "file", "main.py")
        assert stored["model"] == "claude-opus-4-5"

    def test_second_call_is_cache_hit(self, db, repo_dir):
        """After a miss+store, the very next call should hit the cache."""
        file_record = _make_file_record(str(repo_dir), content_hash="stable")
        client = _mock_client()

        summarize_file(db, 1, file_record, client)
        summarize_file(db, 1, file_record, client)

        assert client.complete.call_count == 1


# ---------------------------------------------------------------------------
# Content hash mismatch (stale cache)
# ---------------------------------------------------------------------------


class TestHashMismatch:
    def test_stale_cache_triggers_re_summarization(self, db, repo_dir):
        """When the stored hash differs from file_record.content_hash, call AI."""
        # Seed with old hash
        upsert_summary(
            db,
            repo_id=1,
            scope="file",
            target_path="main.py",
            summary="Old summary.",
            content_hash="old-hash",
        )

        file_record = _make_file_record(str(repo_dir), content_hash="new-hash")
        client = _mock_client(summary="Updated summary.")

        result = summarize_file(db, 1, file_record, client)

        client.complete.assert_called_once()
        assert result == "Updated summary."

    def test_stale_cache_updates_stored_hash(self, db, repo_dir):
        upsert_summary(
            db,
            repo_id=1,
            scope="file",
            target_path="main.py",
            summary="Old summary.",
            content_hash="old-hash",
        )

        file_record = _make_file_record(str(repo_dir), content_hash="new-hash")
        client = _mock_client(summary="Updated summary.")

        summarize_file(db, 1, file_record, client)

        stored = get_summary(db, 1, "file", "main.py")
        assert stored["content_hash"] == "new-hash"

    def test_stale_cache_updates_stored_summary(self, db, repo_dir):
        upsert_summary(
            db,
            repo_id=1,
            scope="file",
            target_path="main.py",
            summary="Old summary.",
            content_hash="old-hash",
        )

        file_record = _make_file_record(str(repo_dir), content_hash="new-hash")
        client = _mock_client(summary="Fresh replacement.")

        summarize_file(db, 1, file_record, client)

        stored = get_summary(db, 1, "file", "main.py")
        assert stored["summary"] == "Fresh replacement."

    def test_missing_hash_in_cache_treated_as_miss(self, db, repo_dir):
        """A cached row with no content_hash should not be treated as a hit."""
        # Insert without a hash (None)
        upsert_summary(
            db,
            repo_id=1,
            scope="file",
            target_path="main.py",
            summary="Hashless summary.",
        )

        file_record = _make_file_record(str(repo_dir), content_hash="any-hash")
        client = _mock_client(summary="New summary.")

        summarize_file(db, 1, file_record, client)

        client.complete.assert_called_once()


# ---------------------------------------------------------------------------
# Large file truncation
# ---------------------------------------------------------------------------


class TestLargeFileTruncation:
    def test_large_content_is_truncated_before_api_call(self, db, tmp_path):
        """Content exceeding the char limit must be capped before the AI call."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Write a file larger than _CONTENT_CHAR_LIMIT
        large_content = "x" * (_CONTENT_CHAR_LIMIT + 10_000)
        (repo / "big.py").write_text(large_content)

        file_record = _make_file_record(
            str(repo),
            relative_path="big.py",
            size_bytes=len(large_content.encode()),
            content_hash="big-hash",
        )

        client = _mock_client(summary="Summary of large file.")
        summarize_file(db, 1, file_record, client)

        # Inspect what was actually passed to complete()
        called_prompt: str = client.complete.call_args[0][0]
        # The raw content inside the prompt must not exceed limit
        # (prompt itself adds overhead, but the file body is capped)
        assert "x" * (_CONTENT_CHAR_LIMIT + 1) not in called_prompt

    def test_small_content_is_not_truncated(self, db, tmp_path):
        """Content within the limit must be passed in full."""
        repo = tmp_path / "repo"
        repo.mkdir()

        content = "def small(): pass\n"
        (repo / "small.py").write_text(content)

        file_record = _make_file_record(
            str(repo),
            relative_path="small.py",
            size_bytes=len(content.encode()),
            content_hash="small-hash",
        )

        client = _mock_client()
        summarize_file(db, 1, file_record, client)

        called_prompt: str = client.complete.call_args[0][0]
        assert content in called_prompt

    def test_exactly_at_limit_is_not_truncated(self, db, tmp_path):
        """Content exactly at the char limit is passed unchanged."""
        repo = tmp_path / "repo"
        repo.mkdir()

        content = "y" * _CONTENT_CHAR_LIMIT
        (repo / "exact.py").write_text(content)

        file_record = _make_file_record(
            str(repo),
            relative_path="exact.py",
            size_bytes=_CONTENT_CHAR_LIMIT,
            content_hash="exact-hash",
        )

        client = _mock_client()
        summarize_file(db, 1, file_record, client)

        called_prompt: str = client.complete.call_args[0][0]
        assert "y" * _CONTENT_CHAR_LIMIT in called_prompt


# ---------------------------------------------------------------------------
# Language detection helper
# ---------------------------------------------------------------------------


class TestLanguageForExtension:
    @pytest.mark.parametrize("ext,expected", [
        (".py", "Python"),
        (".ts", "TypeScript"),
        (".tsx", "TypeScript"),
        (".js", "JavaScript"),
        (".md", "Markdown"),
        (".rs", "Rust"),
        (".go", "Go"),
        (".json", "JSON"),
        (".yaml", "YAML"),
        (".yml", "YAML"),
        (".sql", "SQL"),
        (".sh", "Shell"),
        ("py", "Python"),       # without leading dot
        ("TS", "TypeScript"),   # case-insensitive
        (".unknown", ""),       # unknown extension -> empty string
        ("", ""),               # empty -> empty string
    ])
    def test_known_extensions(self, ext, expected):
        assert _language_for_extension(ext) == expected
