"""Data access layer for repolens.

All SQL lives here. Nothing outside repolens/db/ should write raw SQL.
Every function accepts a sqlite3.Connection as its first argument.
Callers are responsible for setting conn.row_factory = sqlite3.Row if they
want dict-like rows; this module always converts results to plain dicts before
returning so callers never have to think about Row objects.
"""

import json
import sqlite3
import time
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _rows(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def _ensure_row_factory(conn: sqlite3.Connection) -> None:
    """Set row_factory if not already done by the caller."""
    if conn.row_factory is not sqlite3.Row:
        conn.row_factory = sqlite3.Row


# ---------------------------------------------------------------------------
# repos
# ---------------------------------------------------------------------------


def create_repo(conn: sqlite3.Connection, path: str, name: str) -> int:
    """Insert a new repo and return its id.

    Args:
        conn:  Open SQLite connection.
        path:  Absolute filesystem path of the repo root.
        name:  Human-readable repo name.

    Returns:
        The integer primary key of the newly created row.

    Raises:
        sqlite3.IntegrityError: if a repo with this path already exists.
    """
    _ensure_row_factory(conn)
    with conn:
        cur = conn.execute(
            "INSERT INTO repos (path, name) VALUES (?, ?)",
            (path, name),
        )
    return cur.lastrowid  # type: ignore[return-value]


def get_repo(conn: sqlite3.Connection, id_or_path: int | str) -> dict | None:
    """Fetch a single repo by integer id or string path.

    Args:
        conn:        Open SQLite connection.
        id_or_path:  Pass an int to look up by primary key, str for path.

    Returns:
        A plain dict of all repo columns, or None if not found.
    """
    _ensure_row_factory(conn)
    if isinstance(id_or_path, int):
        row = conn.execute(
            "SELECT * FROM repos WHERE id = ?", (id_or_path,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM repos WHERE path = ?", (id_or_path,)
        ).fetchone()
    return _row(row)


def get_repo_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    """Fetch a single repo by human-readable name.

    Names are not unique by schema, but in practice the CLI assigns them
    from the path basename so collisions are rare. Returns the first match
    by ascending id when duplicates exist.
    """
    _ensure_row_factory(conn)
    row = conn.execute(
        "SELECT * FROM repos WHERE name = ? ORDER BY id ASC LIMIT 1", (name,)
    ).fetchone()
    return _row(row)


def list_repos(conn: sqlite3.Connection) -> list[dict]:
    """Return all repos ordered by created_at ascending.

    Args:
        conn:  Open SQLite connection.

    Returns:
        List of plain dicts, one per repo row.
    """
    _ensure_row_factory(conn)
    rows = conn.execute(
        "SELECT * FROM repos ORDER BY created_at ASC"
    ).fetchall()
    return _rows(rows)


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------


def upsert_file(
    conn: sqlite3.Connection,
    repo_id: int,
    path: str,
    **fields: Any,
) -> int:
    """Insert or replace a file row and return its id.

    The unique constraint is (repo_id, path). If a row already exists for
    that pair all supplied keyword arguments are merged in. Columns not
    supplied are left unchanged on update (we PATCH, not overwrite).

    Supported extra fields (all optional):
        extension, size_bytes, mtime, content_hash, classification,
        importance_score, token_estimate

    Args:
        conn:     Open SQLite connection.
        repo_id:  Foreign key to repos.id.
        path:     Repo-relative file path.
        **fields: Any file column values to set.

    Returns:
        The integer primary key of the upserted row.
    """
    _ensure_row_factory(conn)

    allowed = {
        "extension", "size_bytes", "mtime", "content_hash",
        "classification", "importance_score", "token_estimate",
    }
    extra = {k: v for k, v in fields.items() if k in allowed}

    # Check if row exists so we can PATCH rather than blindly overwrite.
    existing = conn.execute(
        "SELECT id FROM files WHERE repo_id = ? AND path = ?",
        (repo_id, path),
    ).fetchone()

    with conn:
        if existing is None:
            # Fresh insert — build column list dynamically
            cols = ["repo_id", "path"] + list(extra.keys())
            placeholders = ", ".join("?" * len(cols))
            values = [repo_id, path] + list(extra.values())
            cur = conn.execute(
                f"INSERT INTO files ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid  # type: ignore[return-value]
        else:
            if extra:
                set_clause = ", ".join(f"{k} = ?" for k in extra)
                conn.execute(
                    f"UPDATE files SET {set_clause} WHERE repo_id = ? AND path = ?",
                    list(extra.values()) + [repo_id, path],
                )
            return existing["id"]


# Whitelist of values accepted by list_files(order_by=...).  The ORDER BY
# fragment is interpolated into SQL, so anything not in this set is rejected.
_ALLOWED_FILE_ORDER: frozenset[str] = frozenset(
    {
        "id", "id ASC", "id DESC",
        "path", "path ASC", "path DESC",
        "extension", "extension ASC", "extension DESC",
        "size_bytes", "size_bytes ASC", "size_bytes DESC",
        "mtime", "mtime ASC", "mtime DESC",
        "classification", "classification ASC", "classification DESC",
        "importance_score", "importance_score ASC", "importance_score DESC",
        "token_estimate", "token_estimate ASC", "token_estimate DESC",
    }
)


def list_files(
    conn: sqlite3.Connection,
    repo_id: int,
    order_by: str = "importance_score DESC",
) -> list[dict]:
    """Return all files for a repo.

    Args:
        conn:      Open SQLite connection.
        repo_id:   Filter to this repo.
        order_by:  SQL ORDER BY fragment. Must be in :data:`_ALLOWED_FILE_ORDER`;
                   otherwise :class:`ValueError` is raised.  This guards against
                   SQL injection when ``order_by`` ever flows from a caller
                   outside this module (e.g. an HTTP query parameter).

    Returns:
        List of plain dicts, one per file row.

    Raises:
        ValueError: if ``order_by`` is not an allowed column/direction pair.
    """
    if order_by not in _ALLOWED_FILE_ORDER:
        raise ValueError(f"invalid order_by: {order_by!r}")
    _ensure_row_factory(conn)
    rows = conn.execute(
        f"SELECT * FROM files WHERE repo_id = ? ORDER BY {order_by}",
        (repo_id,),
    ).fetchall()
    return _rows(rows)


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------


def upsert_summary(
    conn: sqlite3.Connection,
    repo_id: int,
    scope: str,
    target_path: str,
    summary: str,
    **fields: Any,
) -> int:
    """Insert or replace a summary row and return its id.

    Unique key: (repo_id, scope, target_path).  On conflict all supplied
    fields are merged in (PATCH semantics).

    Supported extra fields:
        model, content_hash, prompt_tokens, completion_tokens,
        cache_read_tokens, cache_creation_tokens

    Args:
        conn:         Open SQLite connection.
        repo_id:      Foreign key to repos.id.
        scope:        'repo', 'directory', or 'file'.
        target_path:  Path this summary covers ('' for repo-level).
        summary:      The generated summary text.
        **fields:     Any extra summary column values.

    Returns:
        The integer primary key of the upserted row.
    """
    _ensure_row_factory(conn)

    allowed = {
        "model",
        "content_hash",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
    }
    extra = {k: v for k, v in fields.items() if k in allowed}

    existing = conn.execute(
        "SELECT id FROM summaries WHERE repo_id = ? AND scope = ? AND target_path = ?",
        (repo_id, scope, target_path),
    ).fetchone()

    with conn:
        if existing is None:
            cols = ["repo_id", "scope", "target_path", "summary"] + list(extra.keys())
            placeholders = ", ".join("?" * len(cols))
            values = [repo_id, scope, target_path, summary] + list(extra.values())
            cur = conn.execute(
                f"INSERT INTO summaries ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid  # type: ignore[return-value]
        else:
            # Always update summary text too on conflict
            update_fields = {"summary": summary, **extra}
            set_clause = ", ".join(f"{k} = ?" for k in update_fields)
            conn.execute(
                f"UPDATE summaries SET {set_clause} WHERE repo_id = ? AND scope = ? AND target_path = ?",
                list(update_fields.values()) + [repo_id, scope, target_path],
            )
            return existing["id"]


def get_summary(
    conn: sqlite3.Connection,
    repo_id: int,
    scope: str,
    target_path: str,
) -> dict | None:
    """Fetch a single summary by its natural key.

    Args:
        conn:         Open SQLite connection.
        repo_id:      Foreign key to repos.id.
        scope:        'repo', 'directory', or 'file'.
        target_path:  Path the summary covers.

    Returns:
        Plain dict or None.
    """
    _ensure_row_factory(conn)
    row = conn.execute(
        "SELECT * FROM summaries WHERE repo_id = ? AND scope = ? AND target_path = ?",
        (repo_id, scope, target_path),
    ).fetchone()
    return _row(row)


def list_summaries_by_scope(
    conn: sqlite3.Connection,
    repo_id: int,
    scope: str,
) -> list[dict]:
    """Return all summaries for a repo filtered by scope.

    Args:
        conn:     Open SQLite connection.
        repo_id:  Filter to this repo.
        scope:    'repo', 'directory', or 'file'.

    Returns:
        List of plain dicts ordered by target_path ASC.
    """
    _ensure_row_factory(conn)
    rows = conn.execute(
        "SELECT * FROM summaries WHERE repo_id = ? AND scope = ? ORDER BY target_path ASC",
        (repo_id, scope),
    ).fetchall()
    return _rows(rows)


# ---------------------------------------------------------------------------
# context_bundles
# ---------------------------------------------------------------------------


def save_bundle(
    conn: sqlite3.Connection,
    repo_id: int,
    task_type: str,
    token_budget: int,
    token_count: int,
    content: str,
    file_paths: list[str],
) -> int:
    """Persist a context bundle and return its id.

    file_paths is stored as a JSON array so it round-trips cleanly.

    Args:
        conn:         Open SQLite connection.
        repo_id:      Foreign key to repos.id.
        task_type:    e.g. 'ask', 'review', 'implement'.
        token_budget: Target budget passed to the bundle builder.
        token_count:  Actual token count of the content.
        content:      The assembled context string.
        file_paths:   Ordered list of file paths included in the bundle.

    Returns:
        The integer primary key of the new row.
    """
    _ensure_row_factory(conn)
    file_paths_json = json.dumps(file_paths)
    with conn:
        cur = conn.execute(
            """
            INSERT INTO context_bundles
                (repo_id, task_type, token_budget, token_count, content, file_paths)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (repo_id, task_type, token_budget, token_count, content, file_paths_json),
        )
    return cur.lastrowid  # type: ignore[return-value]


def get_bundle(conn: sqlite3.Connection, bundle_id: int) -> dict | None:
    """Fetch a context bundle by id.

    file_paths is decoded back to a Python list before returning.

    Args:
        conn:       Open SQLite connection.
        bundle_id:  Primary key of the bundle.

    Returns:
        Plain dict with file_paths as list, or None.
    """
    _ensure_row_factory(conn)
    row = conn.execute(
        "SELECT * FROM context_bundles WHERE id = ?", (bundle_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("file_paths") is not None:
        d["file_paths"] = json.loads(d["file_paths"])
    return d


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


def create_run(
    conn: sqlite3.Connection,
    repo_id: int,
    task_type: str,
    task_description: str,
    model: str,
) -> int:
    """Insert a new run row with status='running' and return its id.

    Args:
        conn:             Open SQLite connection.
        repo_id:          Foreign key to repos.id.
        task_type:        e.g. 'ask', 'review'.
        task_description: Free-text description of the task.
        model:            Model identifier used for this run.

    Returns:
        The integer primary key of the new row.
    """
    _ensure_row_factory(conn)
    with conn:
        cur = conn.execute(
            """
            INSERT INTO runs (repo_id, task_type, task_description, model, status)
            VALUES (?, ?, ?, ?, 'running')
            """,
            (repo_id, task_type, task_description, model),
        )
    return cur.lastrowid  # type: ignore[return-value]


def update_run(conn: sqlite3.Connection, run_id: int, **fields: Any) -> None:
    """Update arbitrary columns on a run row.

    If 'status' is set to 'completed' or 'failed' and 'completed_at' is not
    explicitly supplied, completed_at is set to the current Unix timestamp.

    Supported fields:
        bundle_id, prompt_tokens, completion_tokens, cost_usd, result,
        status, error_message, completed_at

    Args:
        conn:    Open SQLite connection.
        run_id:  Primary key of the run to update.
        **fields: Column name / value pairs to set.

    Raises:
        ValueError: if no fields are provided.
    """
    if not fields:
        raise ValueError("update_run requires at least one field to update")

    allowed = {
        "bundle_id", "prompt_tokens", "completion_tokens",
        "cache_read_tokens", "cache_creation_tokens",
        "cost_usd", "result", "status", "error_message", "completed_at",
    }
    update = {k: v for k, v in fields.items() if k in allowed}

    # Auto-set completed_at when finishing a run
    terminal = {"completed", "failed"}
    if update.get("status") in terminal and "completed_at" not in update:
        update["completed_at"] = int(time.time())

    if not update:
        return

    set_clause = ", ".join(f"{k} = ?" for k in update)
    with conn:
        conn.execute(
            f"UPDATE runs SET {set_clause} WHERE id = ?",
            list(update.values()) + [run_id],
        )


def get_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """Return a single run row by primary key, or None if not found.

    Args:
        conn:    Open SQLite connection.
        run_id:  Primary key to look up.

    Returns:
        Plain dict of the run row, or None.
    """
    _ensure_row_factory(conn)
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(
    conn: sqlite3.Connection,
    repo_id: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return recent runs, optionally filtered by repo.

    Args:
        conn:     Open SQLite connection.
        repo_id:  If provided, filter to this repo only.
        limit:    Maximum number of rows to return (default 10).

    Returns:
        List of plain dicts ordered by created_at DESC.
    """
    _ensure_row_factory(conn)
    if repo_id is not None:
        rows = conn.execute(
            "SELECT * FROM runs WHERE repo_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (repo_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return _rows(rows)
