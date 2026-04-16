"""SQLite schema definition and migration runner for repolens.

Call init_db() on startup to create tables and indexes on first use.
The function is idempotent: safe to call on an existing DB.
No raw SQL should appear outside the repolens/db/ package.
"""

import sqlite3
from pathlib import Path

from repolens.config import get_db_path
from repolens.db.migrations import migrate

# ---------------------------------------------------------------------------
# Schema version tracked in schema_version table
# ---------------------------------------------------------------------------

CURRENT_VERSION = 2

# ---------------------------------------------------------------------------
# DDL statements
# ---------------------------------------------------------------------------

_CREATE_TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS repos (
        id                  INTEGER PRIMARY KEY,
        path                TEXT    UNIQUE NOT NULL,
        name                TEXT    NOT NULL,
        file_count          INTEGER,
        total_size_bytes    INTEGER,
        ingested_at         INTEGER,
        last_scanned_at     INTEGER,
        created_at          INTEGER DEFAULT (unixepoch())
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id               INTEGER PRIMARY KEY,
        repo_id          INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
        path             TEXT    NOT NULL,
        extension        TEXT,
        size_bytes       INTEGER,
        mtime            INTEGER,
        content_hash     TEXT,
        classification   TEXT,
        importance_score REAL,
        token_estimate   INTEGER,
        UNIQUE(repo_id, path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS summaries (
        id                INTEGER PRIMARY KEY,
        repo_id           INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
        scope             TEXT    NOT NULL,
        target_path       TEXT    NOT NULL,
        summary           TEXT    NOT NULL,
        model             TEXT,
        content_hash      TEXT,
        prompt_tokens     INTEGER,
        completion_tokens INTEGER,
        created_at        INTEGER DEFAULT (unixepoch()),
        UNIQUE(repo_id, scope, target_path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_bundles (
        id           INTEGER PRIMARY KEY,
        repo_id      INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
        task_type    TEXT,
        token_budget INTEGER,
        token_count  INTEGER,
        content      TEXT    NOT NULL,
        file_paths   TEXT,
        created_at   INTEGER DEFAULT (unixepoch())
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        id                    INTEGER PRIMARY KEY,
        repo_id               INTEGER REFERENCES repos(id) ON DELETE SET NULL,
        bundle_id             INTEGER REFERENCES context_bundles(id) ON DELETE SET NULL,
        task_type             TEXT,
        task_description      TEXT,
        model                 TEXT,
        prompt_tokens         INTEGER,
        completion_tokens     INTEGER,
        cache_read_tokens     INTEGER DEFAULT 0,
        cache_creation_tokens INTEGER DEFAULT 0,
        cost_usd              REAL,
        result                TEXT,
        status                TEXT DEFAULT 'pending',
        error_message         TEXT,
        created_at            INTEGER DEFAULT (unixepoch()),
        completed_at          INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER PRIMARY KEY,
        applied_at INTEGER DEFAULT (unixepoch())
    )
    """,
]

_CREATE_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_files_repo    ON files(repo_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_score   ON files(repo_id, importance_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_summaries_lookup ON summaries(repo_id, scope, target_path)",
    "CREATE INDEX IF NOT EXISTS idx_runs_repo     ON runs(repo_id, created_at DESC)",
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_path: Path | None = None) -> None:
    """Create the DB file, all tables, all indexes, and seed schema_version.

    Safe to call on an existing database: uses IF NOT EXISTS throughout so
    it never destroys data or raises on re-runs.

    Args:
        db_path: Override the DB path. Defaults to the value returned by
                 config.get_db_path() (respects REPOLENS_DB env var).
    """
    if db_path is None:
        db_path = get_db_path()

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        # Enable WAL for better concurrent read performance and safer writes
        conn.execute("PRAGMA journal_mode=WAL")
        # Enforce foreign key constraints
        conn.execute("PRAGMA foreign_keys=ON")

        with conn:
            for stmt in _CREATE_TABLES:
                conn.execute(stmt)

            for stmt in _CREATE_INDEXES:
                conn.execute(stmt)

        # Apply the version ladder.  Fresh DBs get stamped directly to
        # CURRENT_VERSION; older DBs bridge forward via ALTER TABLE.
        migrate(conn, target=CURRENT_VERSION)
    finally:
        conn.close()


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the current schema version recorded in the DB, or None if empty."""
    row = conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()
    return row[0] if row else None
