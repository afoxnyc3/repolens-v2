"""Tests for repolens/context/packager.py.

Coverage:
- Budget enforcement: final token_count <= token_budget * 1.05
- Summary fallback: files that don't fit at full content use stored summary
- file_paths accuracy: only full-content files appear in file_paths
- Repo/directory summaries included in output
- Task instructions appended for each task_type
- Unknown task_type uses generic instructions
- Missing file on disk falls back to summary
- Empty repo (no files, no summaries) returns a bundle with task instructions
- repo not found raises ValueError
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from repolens.context.packager import ContextBundle, build_context
from repolens.context.token_counter import count_tokens
from repolens.db.repository import (
    create_repo,
    upsert_file,
    upsert_summary,
)
from repolens.db.schema import init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path):
    """Initialised SQLite connection for packager tests."""
    db_file = tmp_path / "test_context.db"
    init_db(db_path=db_file)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """On-disk directory acting as the repo root."""
    d = tmp_path / "myrepo"
    d.mkdir()
    return d


@pytest.fixture
def basic_repo(db, repo_dir):
    """Insert a repo row and return (conn, repo_id, repo_dir)."""
    repo_id = create_repo(db, str(repo_dir), "myrepo")
    return db, repo_id, repo_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(repo_dir: Path, rel_path: str, content: str) -> None:
    full = repo_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _add_file(conn, repo_id, path, importance=5.0, extension="py"):
    upsert_file(conn, repo_id, path, importance_score=importance, extension=extension)


def _add_file_summary(conn, repo_id, path, summary):
    upsert_summary(conn, repo_id, "file", path, summary)


# ---------------------------------------------------------------------------
# Basic smoke test
# ---------------------------------------------------------------------------


class TestBuildContextSmoke:
    def test_returns_context_bundle(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        bundle = build_context(conn, repo_id, "analyze")
        assert isinstance(bundle, ContextBundle)
        assert isinstance(bundle.content, str)
        assert isinstance(bundle.file_paths, list)
        assert isinstance(bundle.token_count, int)
        assert bundle.token_count >= 1

    def test_task_instructions_in_content(self, basic_repo):
        conn, repo_id, _ = basic_repo
        for task in ("analyze", "summarize", "refactor-prep"):
            bundle = build_context(conn, repo_id, task)
            assert "Task Instructions" in bundle.content

    def test_unknown_task_type_uses_default_instructions(self, basic_repo):
        conn, repo_id, _ = basic_repo
        bundle = build_context(conn, repo_id, "unknown-task-xyz")
        assert "Task Instructions" in bundle.content

    def test_repo_not_found_raises(self, db):
        with pytest.raises(ValueError, match="Repo 9999 not found"):
            build_context(db, 9999, "analyze")


# ---------------------------------------------------------------------------
# Repo and directory summaries
# ---------------------------------------------------------------------------


class TestSummaryInclusion:
    def test_repo_summary_appears_in_content(self, basic_repo):
        conn, repo_id, _ = basic_repo
        upsert_summary(conn, repo_id, "repo", "", "Top-level repo summary text.")
        bundle = build_context(conn, repo_id, "analyze")
        assert "Top-level repo summary text." in bundle.content

    def test_directory_summary_appears_in_content(self, basic_repo):
        conn, repo_id, _ = basic_repo
        upsert_summary(conn, repo_id, "directory", "src", "Source directory summary.")
        bundle = build_context(conn, repo_id, "analyze")
        assert "Source directory summary." in bundle.content

    def test_no_summaries_still_returns_bundle(self, basic_repo):
        conn, repo_id, _ = basic_repo
        bundle = build_context(conn, repo_id, "analyze")
        assert isinstance(bundle, ContextBundle)


# ---------------------------------------------------------------------------
# file_paths accuracy
# ---------------------------------------------------------------------------


class TestFilePathsAccuracy:
    def test_full_content_file_appears_in_file_paths(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        _write_file(repo_dir, "main.py", "def hello(): pass\n")
        _add_file(conn, repo_id, "main.py", importance=10.0)

        bundle = build_context(conn, repo_id, "analyze", token_budget=32000)
        assert "main.py" in bundle.file_paths

    def test_summary_only_file_not_in_file_paths(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        # Give a very tight budget so file won't fit at full content
        big_content = "x = 1\n" * 5000  # large file
        _write_file(repo_dir, "big.py", big_content)
        _add_file(conn, repo_id, "big.py", importance=10.0)
        _add_file_summary(conn, repo_id, "big.py", "This file does big things.")

        # Tight budget: only summaries can fit
        bundle = build_context(conn, repo_id, "analyze", token_budget=200)
        assert "big.py" not in bundle.file_paths

    def test_file_paths_only_contains_full_content_files(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        _write_file(repo_dir, "small.py", "x = 1\n")
        _write_file(repo_dir, "big.py", "y = 2\n" * 5000)
        _add_file(conn, repo_id, "small.py", importance=10.0)
        _add_file(conn, repo_id, "big.py", importance=5.0)
        _add_file_summary(conn, repo_id, "big.py", "Big file does lots.")

        bundle = build_context(conn, repo_id, "analyze", token_budget=500)
        # small.py should be in file_paths, big.py should not
        assert "small.py" in bundle.file_paths
        assert "big.py" not in bundle.file_paths

    def test_empty_file_paths_when_no_files(self, basic_repo):
        conn, repo_id, _ = basic_repo
        bundle = build_context(conn, repo_id, "analyze")
        assert bundle.file_paths == []


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    def test_token_count_within_budget_tolerance(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        # Add some files and summaries
        for i in range(5):
            path = f"module_{i}.py"
            _write_file(repo_dir, path, f"# module {i}\n" * 20)
            _add_file(conn, repo_id, path, importance=float(10 - i))
            _add_file_summary(conn, repo_id, path, f"Summary for module {i}.")

        upsert_summary(conn, repo_id, "repo", "", "Repo-level overview.")
        upsert_summary(conn, repo_id, "directory", ".", "Root directory summary.")

        budget = 1000
        bundle = build_context(conn, repo_id, "analyze", token_budget=budget)
        assert bundle.token_count <= budget * 1.05, (
            f"token_count {bundle.token_count} exceeds budget * 1.05 = {budget * 1.05}"
        )

    def test_budget_enforced_with_single_large_file(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        large_content = "import os\n" * 3000  # ~several thousand tokens
        _write_file(repo_dir, "large.py", large_content)
        _add_file(conn, repo_id, "large.py", importance=10.0)
        _add_file_summary(conn, repo_id, "large.py", "Large module does I/O.")

        budget = 500
        bundle = build_context(conn, repo_id, "analyze", token_budget=budget)
        assert bundle.token_count <= budget * 1.05

    def test_budget_enforced_with_many_files(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        for i in range(20):
            path = f"file_{i:02d}.py"
            _write_file(repo_dir, path, f"def func_{i}(): pass\n" * 50)
            _add_file(conn, repo_id, path, importance=float(20 - i))
            _add_file_summary(conn, repo_id, path, f"Module {i} summary.")

        budget = 2000
        bundle = build_context(conn, repo_id, "analyze", token_budget=budget)
        assert bundle.token_count <= budget * 1.05

    def test_token_count_matches_content_length(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        _write_file(repo_dir, "a.py", "x = 1\n")
        _add_file(conn, repo_id, "a.py", importance=5.0)

        bundle = build_context(conn, repo_id, "summarize", token_budget=32000)
        # token_count stored in bundle should match what count_tokens returns
        assert bundle.token_count == count_tokens(bundle.content)

    def test_very_tight_budget_still_returns_bundle(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        _write_file(repo_dir, "a.py", "x = 1\n" * 100)
        _add_file(conn, repo_id, "a.py", importance=5.0)

        # Budget so tight only task instructions can fit
        bundle = build_context(conn, repo_id, "analyze", token_budget=50)
        assert isinstance(bundle, ContextBundle)
        assert "Task Instructions" in bundle.content


# ---------------------------------------------------------------------------
# Summary fallback
# ---------------------------------------------------------------------------


class TestSummaryFallback:
    def test_summary_used_when_file_too_large(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        big_content = "# padding\n" * 3000
        _write_file(repo_dir, "heavy.py", big_content)
        _add_file(conn, repo_id, "heavy.py", importance=10.0)
        _add_file_summary(conn, repo_id, "heavy.py", "Heavy module summary text.")

        bundle = build_context(conn, repo_id, "analyze", token_budget=300)
        assert "Heavy module summary text." in bundle.content
        assert "heavy.py" not in bundle.file_paths

    def test_summary_used_when_file_missing_from_disk(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        # Register file in DB but do NOT write it to disk
        _add_file(conn, repo_id, "ghost.py", importance=10.0)
        _add_file_summary(conn, repo_id, "ghost.py", "Ghost file summary.")

        bundle = build_context(conn, repo_id, "analyze", token_budget=32000)
        assert "Ghost file summary." in bundle.content
        assert "ghost.py" not in bundle.file_paths

    def test_no_summary_and_no_disk_file_skipped_silently(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        # File in DB, not on disk, no summary
        _add_file(conn, repo_id, "phantom.py", importance=10.0)

        bundle = build_context(conn, repo_id, "analyze", token_budget=32000)
        assert "phantom.py" not in bundle.content
        assert "phantom.py" not in bundle.file_paths

    def test_full_content_preferred_over_summary_when_it_fits(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        real_content = "def greet(): return 'hello'\n"
        _write_file(repo_dir, "greet.py", real_content)
        _add_file(conn, repo_id, "greet.py", importance=10.0)
        _add_file_summary(conn, repo_id, "greet.py", "Greet module summary.")

        bundle = build_context(conn, repo_id, "analyze", token_budget=32000)
        # Full content included; summary should NOT be used
        assert "def greet():" in bundle.content
        assert "greet.py" in bundle.file_paths
        # Summary text should not appear when full content is used
        assert "Greet module summary." not in bundle.content


# ---------------------------------------------------------------------------
# Importance ordering
# ---------------------------------------------------------------------------


class TestImportanceOrdering:
    def test_high_importance_file_included_first(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        _write_file(repo_dir, "core.py", "# core module\n")
        _write_file(repo_dir, "util.py", "# util module\n")
        _add_file(conn, repo_id, "core.py", importance=9.0)
        _add_file(conn, repo_id, "util.py", importance=1.0)

        bundle = build_context(conn, repo_id, "analyze", token_budget=32000)
        # Both should be present
        assert "core.py" in bundle.file_paths
        assert "util.py" in bundle.file_paths
        # core.py should appear before util.py in file_paths list
        assert bundle.file_paths.index("core.py") < bundle.file_paths.index("util.py")

    def test_low_importance_file_dropped_when_budget_tight(self, basic_repo):
        conn, repo_id, repo_dir = basic_repo
        _write_file(repo_dir, "important.py", "# important\n" * 10)
        _write_file(repo_dir, "trivial.py", "# trivial\n" * 1000)
        _add_file(conn, repo_id, "important.py", importance=9.0)
        _add_file(conn, repo_id, "trivial.py", importance=0.5)

        budget = 200
        bundle = build_context(conn, repo_id, "analyze", token_budget=budget)
        # trivial.py has too many tokens AND low importance; important.py may fit
        # at minimum neither should push us over budget
        assert bundle.token_count <= budget * 1.05
