"""Tests for repolens/db/schema.py — table creation, idempotency, indexes, version."""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from repolens.db.schema import CURRENT_VERSION, get_schema_version, init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row["name"] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row["name"] for row in rows}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Return a path for a fresh temp DB file (not yet created)."""
    return tmp_path / "test_repolens.db"


@pytest.fixture()
def initialised_db(db_path: Path) -> sqlite3.Connection:
    """Call init_db() and return an open connection to the result."""
    init_db(db_path)
    conn = _open(db_path)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Tests: all six tables are created
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "repos",
    "files",
    "summaries",
    "context_bundles",
    "runs",
    "schema_version",
}


def test_all_tables_created(initialised_db: sqlite3.Connection) -> None:
    assert _table_names(initialised_db) == EXPECTED_TABLES


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_individual_table_exists(initialised_db: sqlite3.Connection, table: str) -> None:
    assert table in _table_names(initialised_db)


# ---------------------------------------------------------------------------
# Tests: idempotent re-run
# ---------------------------------------------------------------------------


def test_init_db_idempotent(db_path: Path) -> None:
    """Calling init_db() twice on the same DB must not raise and must not duplicate data."""
    init_db(db_path)
    init_db(db_path)  # second call — must be silent

    conn = _open(db_path)
    try:
        tables = _table_names(conn)
        assert tables == EXPECTED_TABLES

        version_rows = conn.execute("SELECT version FROM schema_version").fetchall()
        assert len(version_rows) == 1, "schema_version should have exactly one row after two inits"
    finally:
        conn.close()


def test_init_db_idempotent_preserves_data(db_path: Path) -> None:
    """Existing data must survive a re-initialisation."""
    init_db(db_path)

    conn = _open(db_path)
    conn.execute(
        "INSERT INTO repos (path, name) VALUES (?, ?)",
        ("/some/repo", "my-repo"),
    )
    conn.commit()
    conn.close()

    init_db(db_path)  # second init

    conn = _open(db_path)
    try:
        row = conn.execute("SELECT name FROM repos WHERE path=?", ("/some/repo",)).fetchone()
        assert row is not None, "Row inserted before re-init should still exist"
        assert row["name"] == "my-repo"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests: indexes
# ---------------------------------------------------------------------------

EXPECTED_INDEXES = {
    "idx_files_repo",
    "idx_files_score",
    "idx_summaries_lookup",
    "idx_runs_repo",
}


def test_all_indexes_exist(initialised_db: sqlite3.Connection) -> None:
    assert EXPECTED_INDEXES.issubset(_index_names(initialised_db))


@pytest.mark.parametrize("idx", sorted(EXPECTED_INDEXES))
def test_individual_index_exists(initialised_db: sqlite3.Connection, idx: str) -> None:
    assert idx in _index_names(initialised_db)


# ---------------------------------------------------------------------------
# Tests: schema_version seeded correctly
# ---------------------------------------------------------------------------


def test_schema_version_row_present(initialised_db: sqlite3.Connection) -> None:
    row = initialised_db.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None, "schema_version must have at least one row after init_db()"


def test_schema_version_is_one(initialised_db: sqlite3.Connection) -> None:
    row = initialised_db.execute(
        "SELECT version FROM schema_version WHERE version=1"
    ).fetchone()
    assert row is not None, "schema_version must contain a row with version=1"


def test_get_schema_version_helper(initialised_db: sqlite3.Connection) -> None:
    assert get_schema_version(initialised_db) == CURRENT_VERSION


def test_get_schema_version_empty_db(tmp_path: Path) -> None:
    """get_schema_version on a brand-new empty DB returns None."""
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    # Create the table but insert nothing
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at INTEGER)"
    )
    conn.commit()
    assert get_schema_version(conn) is None
    conn.close()


# ---------------------------------------------------------------------------
# Tests: REPOLENS_DB env var respected
# ---------------------------------------------------------------------------


def test_init_db_uses_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """init_db() with no explicit path should use the REPOLENS_DB env var."""
    target = str(tmp_path / "env_driven.db")
    monkeypatch.setenv("REPOLENS_DB", target)

    init_db()  # no explicit path

    assert Path(target).exists(), "DB file should be created at REPOLENS_DB path"
    conn = _open(Path(target))
    try:
        assert _table_names(conn) == EXPECTED_TABLES
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests: parent directory auto-created
# ---------------------------------------------------------------------------


def test_init_db_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "repolens.db"
    init_db(nested)
    assert nested.exists()


# ---------------------------------------------------------------------------
# Tests: table columns (smoke-check a few key columns)
# ---------------------------------------------------------------------------


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def test_repos_columns(initialised_db: sqlite3.Connection) -> None:
    cols = _column_names(initialised_db, "repos")
    assert {"id", "path", "name", "file_count", "total_size_bytes",
            "ingested_at", "last_scanned_at", "created_at"}.issubset(cols)


def test_files_columns(initialised_db: sqlite3.Connection) -> None:
    cols = _column_names(initialised_db, "files")
    assert {"id", "repo_id", "path", "extension", "size_bytes", "mtime",
            "content_hash", "classification", "importance_score",
            "token_estimate"}.issubset(cols)


def test_summaries_columns(initialised_db: sqlite3.Connection) -> None:
    cols = _column_names(initialised_db, "summaries")
    assert {"id", "repo_id", "scope", "target_path", "summary", "model",
            "content_hash", "prompt_tokens", "completion_tokens",
            "created_at"}.issubset(cols)


def test_runs_columns(initialised_db: sqlite3.Connection) -> None:
    cols = _column_names(initialised_db, "runs")
    assert {"id", "repo_id", "bundle_id", "task_type", "task_description",
            "model", "prompt_tokens", "completion_tokens", "cost_usd",
            "result", "status", "error_message", "created_at",
            "completed_at"}.issubset(cols)


# ---------------------------------------------------------------------------
# Tests: foreign key cascade (basic sanity)
# ---------------------------------------------------------------------------


def test_files_cascade_on_repo_delete(initialised_db: sqlite3.Connection) -> None:
    """Deleting a repo should cascade-delete its files (FK ON DELETE CASCADE)."""
    conn = initialised_db
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT INTO repos (id, path, name) VALUES (1, '/tmp/r', 'r')")
    conn.execute(
        "INSERT INTO files (repo_id, path) VALUES (1, 'main.py')"
    )
    conn.commit()

    conn.execute("DELETE FROM repos WHERE id=1")
    conn.commit()

    rows = conn.execute("SELECT * FROM files WHERE repo_id=1").fetchall()
    assert len(rows) == 0, "Files should be deleted when their repo is deleted"
