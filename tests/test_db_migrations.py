"""Tests for repolens/db/migrations.py — schema version ladder."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from repolens.db.migrations import (
    MIGRATIONS,
    _current_version,
    _has_column,
    migrate,
)
from repolens.db.schema import CURRENT_VERSION, init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "migration_test.db"


@pytest.fixture()
def fresh_conn(db_path: Path):
    """Run init_db and return a connection — schema is at CURRENT_VERSION."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture()
def legacy_v1_conn(db_path: Path):
    """Simulate a v1 database: tables + indexes, runs lacks cache columns."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE repos (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            file_count INTEGER,
            total_size_bytes INTEGER,
            ingested_at INTEGER,
            last_scanned_at INTEGER,
            created_at INTEGER DEFAULT (unixepoch())
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER,
            bundle_id INTEGER,
            task_type TEXT,
            task_description TEXT,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            cost_usd REAL,
            result TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at INTEGER DEFAULT (unixepoch()),
            completed_at INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER DEFAULT (unixepoch())
        )
        """
    )
    with conn:
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# _has_column
# ---------------------------------------------------------------------------


class TestHasColumn:
    def test_returns_true_for_existing_column(self, fresh_conn):
        assert _has_column(fresh_conn, "runs", "id")

    def test_returns_false_for_missing_column(self, fresh_conn):
        assert not _has_column(fresh_conn, "runs", "no_such_column")

    def test_detects_cache_columns_after_fresh_init(self, fresh_conn):
        assert _has_column(fresh_conn, "runs", "cache_read_tokens")
        assert _has_column(fresh_conn, "runs", "cache_creation_tokens")


# ---------------------------------------------------------------------------
# _current_version
# ---------------------------------------------------------------------------


class TestCurrentVersion:
    def test_returns_zero_for_empty_schema_version_table(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        try:
            assert _current_version(conn) == 0
        finally:
            conn.close()

    def test_returns_max_version_seen(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        with conn:
            conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        try:
            assert _current_version(conn) == 2
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# migrate — fresh install path
# ---------------------------------------------------------------------------


class TestMigrateFreshInstall:
    def test_fresh_init_stamps_current_version(self, fresh_conn):
        assert _current_version(fresh_conn) == CURRENT_VERSION

    def test_fresh_init_creates_cache_columns(self, fresh_conn):
        assert _has_column(fresh_conn, "runs", "cache_read_tokens")
        assert _has_column(fresh_conn, "runs", "cache_creation_tokens")

    def test_cache_columns_default_to_zero(self, fresh_conn):
        with fresh_conn:
            fresh_conn.execute(
                "INSERT INTO repos (path, name) VALUES (?, ?)", ("/p", "r")
            )
            fresh_conn.execute(
                "INSERT INTO runs (repo_id, status) VALUES (1, 'done')"
            )
        row = fresh_conn.execute(
            "SELECT cache_read_tokens, cache_creation_tokens FROM runs WHERE id = 1"
        ).fetchone()
        assert row["cache_read_tokens"] == 0
        assert row["cache_creation_tokens"] == 0

    def test_fresh_init_is_idempotent(self, db_path):
        init_db(db_path)
        init_db(db_path)  # second call must not double-stamp
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT version FROM schema_version").fetchall()
            # exactly one stamp per version applied
            versions = [r["version"] for r in rows]
            assert versions == [CURRENT_VERSION]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# migrate — upgrade path (v1 → v2)
# ---------------------------------------------------------------------------


class TestMigrateUpgrade:
    def test_v1_db_is_detected(self, legacy_v1_conn):
        assert _current_version(legacy_v1_conn) == 1
        assert not _has_column(legacy_v1_conn, "runs", "cache_read_tokens")

    def test_upgrade_adds_cache_columns(self, legacy_v1_conn):
        migrate(legacy_v1_conn, target=2)
        assert _has_column(legacy_v1_conn, "runs", "cache_read_tokens")
        assert _has_column(legacy_v1_conn, "runs", "cache_creation_tokens")

    def test_upgrade_stamps_version_2(self, legacy_v1_conn):
        migrate(legacy_v1_conn, target=2)
        assert _current_version(legacy_v1_conn) == 2

    def test_upgrade_preserves_existing_rows(self, legacy_v1_conn):
        with legacy_v1_conn:
            legacy_v1_conn.execute(
                "INSERT INTO repos (path, name) VALUES (?, ?)", ("/a", "a")
            )
            legacy_v1_conn.execute(
                "INSERT INTO runs (repo_id, status, result) VALUES (1, 'done', 'hi')"
            )
        migrate(legacy_v1_conn, target=2)
        row = legacy_v1_conn.execute(
            "SELECT result, cache_read_tokens FROM runs WHERE id = 1"
        ).fetchone()
        assert row["result"] == "hi"
        assert row["cache_read_tokens"] == 0  # default applied

    def test_upgrade_is_idempotent(self, legacy_v1_conn):
        migrate(legacy_v1_conn, target=2)
        migrate(legacy_v1_conn, target=2)  # second call must not re-apply
        rows = legacy_v1_conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in rows]
        assert versions == [1, 2]


# ---------------------------------------------------------------------------
# MIGRATIONS registry hygiene
# ---------------------------------------------------------------------------


def test_migrations_registry_has_v2():
    assert 2 in MIGRATIONS
    assert callable(MIGRATIONS[2])


def test_migrations_keys_are_sequential_positive_ints():
    assert all(isinstance(k, int) and k >= 2 for k in MIGRATIONS)
