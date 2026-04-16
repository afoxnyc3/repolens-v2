"""SQLite migration ladder for repolens.

Each entry in :data:`MIGRATIONS` maps a target version to a callable that
upgrades the DB from ``version - 1`` to ``version``.  Migrations must be
**idempotent**: ``ALTER TABLE ADD COLUMN`` has no ``IF NOT EXISTS`` form in
SQLite, so each step checks ``PRAGMA table_info`` before mutating.

The fresh-install path is separate: :func:`repolens.db.schema.init_db` runs
``CREATE TABLE IF NOT EXISTS`` against the latest schema, then calls
:func:`migrate`.  On a brand-new DB every migration is a no-op; only the
version stamp is inserted.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if ``table`` already has ``column``."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _current_version(conn: sqlite3.Connection) -> int:
    """Return the highest version stamped in ``schema_version`` (0 if empty)."""
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


# ---------------------------------------------------------------------------
# Version ladder
# ---------------------------------------------------------------------------


def _upgrade_to_v2(conn: sqlite3.Connection) -> None:
    """v1 → v2: add cache-token accounting columns to the ``runs`` table."""
    if not _has_column(conn, "runs", "cache_read_tokens"):
        conn.execute(
            "ALTER TABLE runs ADD COLUMN cache_read_tokens INTEGER DEFAULT 0"
        )
    if not _has_column(conn, "runs", "cache_creation_tokens"):
        conn.execute(
            "ALTER TABLE runs ADD COLUMN cache_creation_tokens INTEGER DEFAULT 0"
        )


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _upgrade_to_v2,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def migrate(conn: sqlite3.Connection, target: int) -> None:
    """Upgrade ``conn`` to schema ``target``.

    Walks :data:`MIGRATIONS` in ascending order.  Every applied migration
    writes a row into ``schema_version`` inside the same transaction.
    Idempotent: replaying on an already-current DB is a no-op.

    Args:
        conn:    Open SQLite connection with ``schema_version`` already
                 created (``_CREATE_TABLES`` handles this).
        target: Highest version to reach.  Migrations whose key is
                greater than this are skipped.

    Raises:
        sqlite3.OperationalError: if a migration step fails — the enclosing
            transaction is rolled back so the DB stays at its previous
            version.
    """
    current = _current_version(conn)

    if current == 0:
        # Fresh DB — CREATE TABLE handled the latest schema already.
        # Stamp directly to target and exit; no ALTER statements to run.
        with conn:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (target,)
            )
        return

    for version in sorted(MIGRATIONS):
        if version <= current or version > target:
            continue
        with conn:
            MIGRATIONS[version](conn)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
