"""Connection helpers for the repolens SQLite database.

Prefer :func:`open_conn` over raw ``sqlite3.connect`` in CLI and API code
— it centralises the common setup (row_factory + foreign-key enforcement)
and guarantees the connection is closed on exit.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from repolens import config


@contextmanager
def open_conn(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a configured :class:`sqlite3.Connection` and close on exit.

    The connection has:

    - ``row_factory`` set to :class:`sqlite3.Row` for dict-like access.
    - ``PRAGMA foreign_keys=ON`` so ``ON DELETE CASCADE`` fires.

    Args:
        db_path: Override the DB file location. Defaults to
            :data:`repolens.config.DB_PATH`.

    Yields:
        An open connection.  The ``with`` block is responsible for any
        transactions; this helper does not commit or rollback on exit —
        use ``with conn:`` inside for atomic writes.
    """
    path = Path(db_path) if db_path is not None else config.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
