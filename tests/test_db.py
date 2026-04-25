"""Tests for repolens/db/schema.py and repolens/db/repository.py."""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from repolens.db.schema import CURRENT_VERSION, get_schema_version, init_db
from repolens.db.repository import (
    create_repo,
    get_repo,
    get_repo_by_name,
    list_repos,
    upsert_file,
    list_files,
    upsert_summary,
    get_summary,
    save_bundle,
    get_bundle,
    create_run,
    update_run,
    list_runs,
)


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


def test_schema_version_is_current(initialised_db: sqlite3.Connection) -> None:
    row = initialised_db.execute(
        "SELECT version FROM schema_version WHERE version=?", (CURRENT_VERSION,)
    ).fetchone()
    assert row is not None, f"schema_version must contain version={CURRENT_VERSION}"


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


# ===========================================================================
# Repository layer tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Fixture: conn wraps initialised_db ensuring row_factory is set
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn(initialised_db: sqlite3.Connection) -> sqlite3.Connection:
    """Alias for initialised_db — row_factory already set by _open()."""
    return initialised_db


@pytest.fixture()
def repo_id(conn: sqlite3.Connection) -> int:
    """Insert a test repo and return its id."""
    return create_repo(conn, "/repos/alpha", "alpha")


# ---------------------------------------------------------------------------
# repos: create / get / list
# ---------------------------------------------------------------------------


def test_create_repo_returns_int(conn: sqlite3.Connection) -> None:
    rid = create_repo(conn, "/repos/x", "x")
    assert isinstance(rid, int)
    assert rid > 0


def test_get_repo_by_id(conn: sqlite3.Connection) -> None:
    rid = create_repo(conn, "/repos/y", "y")
    row = get_repo(conn, rid)
    assert row is not None
    assert row["path"] == "/repos/y"
    assert row["name"] == "y"


def test_get_repo_by_path(conn: sqlite3.Connection) -> None:
    create_repo(conn, "/repos/z", "z")
    row = get_repo(conn, "/repos/z")
    assert row is not None
    assert row["name"] == "z"


def test_get_repo_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert get_repo(conn, 9999) is None
    assert get_repo(conn, "/not/there") is None


def test_get_repo_by_name_returns_match(conn: sqlite3.Connection) -> None:
    create_repo(conn, "/repos/proj_a", "proj_a")
    row = get_repo_by_name(conn, "proj_a")
    assert row is not None
    assert row["path"] == "/repos/proj_a"


def test_get_repo_by_name_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert get_repo_by_name(conn, "nope") is None


def test_get_repo_by_name_returns_lowest_id_on_collision(
    conn: sqlite3.Connection,
) -> None:
    first = create_repo(conn, "/repos/dup_a", "shared")
    create_repo(conn, "/repos/dup_b", "shared")
    row = get_repo_by_name(conn, "shared")
    assert row is not None
    assert row["id"] == first


def test_get_repo_returns_plain_dict(conn: sqlite3.Connection) -> None:
    rid = create_repo(conn, "/repos/d", "d")
    row = get_repo(conn, rid)
    assert isinstance(row, dict)


def test_list_repos_empty(conn: sqlite3.Connection) -> None:
    assert list_repos(conn) == []


def test_list_repos_multiple(conn: sqlite3.Connection) -> None:
    create_repo(conn, "/repos/a", "a")
    create_repo(conn, "/repos/b", "b")
    rows = list_repos(conn)
    assert len(rows) == 2
    assert all(isinstance(r, dict) for r in rows)


def test_create_repo_duplicate_path_raises(conn: sqlite3.Connection) -> None:
    create_repo(conn, "/repos/dup", "dup")
    with pytest.raises(sqlite3.IntegrityError):
        create_repo(conn, "/repos/dup", "dup2")


# ---------------------------------------------------------------------------
# files: upsert / list
# ---------------------------------------------------------------------------


def test_upsert_file_insert(conn: sqlite3.Connection, repo_id: int) -> None:
    fid = upsert_file(conn, repo_id, "src/main.py")
    assert isinstance(fid, int) and fid > 0


def test_upsert_file_with_fields(conn: sqlite3.Connection, repo_id: int) -> None:
    fid = upsert_file(
        conn, repo_id, "src/utils.py",
        extension=".py", size_bytes=1024, importance_score=0.9,
    )
    files = list_files(conn, repo_id)
    assert len(files) == 1
    assert files[0]["id"] == fid
    assert files[0]["extension"] == ".py"
    assert files[0]["size_bytes"] == 1024
    assert files[0]["importance_score"] == pytest.approx(0.9)


def test_upsert_file_deduplication(conn: sqlite3.Connection, repo_id: int) -> None:
    """Second upsert on same (repo_id, path) must return the same id and update fields."""
    fid1 = upsert_file(conn, repo_id, "src/app.py", importance_score=0.5)
    fid2 = upsert_file(conn, repo_id, "src/app.py", importance_score=0.8)
    assert fid1 == fid2, "Upsert should return the same id for existing row"
    files = list_files(conn, repo_id)
    assert len(files) == 1
    assert files[0]["importance_score"] == pytest.approx(0.8)


def test_upsert_file_different_repos(conn: sqlite3.Connection) -> None:
    """Same path in two repos is allowed and gets different ids."""
    rid1 = create_repo(conn, "/repos/r1", "r1")
    rid2 = create_repo(conn, "/repos/r2", "r2")
    fid1 = upsert_file(conn, rid1, "main.py")
    fid2 = upsert_file(conn, rid2, "main.py")
    assert fid1 != fid2


def test_list_files_order_by_importance(conn: sqlite3.Connection, repo_id: int) -> None:
    upsert_file(conn, repo_id, "low.py", importance_score=0.1)
    upsert_file(conn, repo_id, "high.py", importance_score=0.9)
    upsert_file(conn, repo_id, "mid.py", importance_score=0.5)
    files = list_files(conn, repo_id)
    scores = [f["importance_score"] for f in files]
    assert scores == sorted(scores, reverse=True)


def test_list_files_empty_repo(conn: sqlite3.Connection, repo_id: int) -> None:
    assert list_files(conn, repo_id) == []


def test_list_files_returns_plain_dicts(conn: sqlite3.Connection, repo_id: int) -> None:
    upsert_file(conn, repo_id, "x.py")
    rows = list_files(conn, repo_id)
    assert all(isinstance(r, dict) for r in rows)


# ---------------------------------------------------------------------------
# list_files: order_by whitelist guards against SQL injection
# ---------------------------------------------------------------------------


class TestListFilesOrderByWhitelist:
    """order_by is interpolated into SQL — must be validated against a whitelist."""

    @pytest.mark.parametrize(
        "order_by",
        [
            "id",
            "path ASC",
            "importance_score DESC",
            "size_bytes ASC",
            "mtime DESC",
            "classification",
            "token_estimate ASC",
        ],
    )
    def test_accepts_allowed_columns_and_directions(
        self, conn: sqlite3.Connection, repo_id: int, order_by: str
    ) -> None:
        upsert_file(conn, repo_id, "a.py", importance_score=0.1)
        upsert_file(conn, repo_id, "b.py", importance_score=0.9)
        # Should not raise
        rows = list_files(conn, repo_id, order_by=order_by)
        assert len(rows) == 2

    @pytest.mark.parametrize(
        "bad_order",
        [
            "; DROP TABLE files; --",
            "id; SELECT 1",
            "importance_score DESC, id",  # comma-separated not allowed
            "random()",
            "NOT_A_COLUMN",
            "path DESCEND",
            "",
            " ",
            "1",
        ],
    )
    def test_rejects_injection_attempts_and_unknown_columns(
        self, conn: sqlite3.Connection, repo_id: int, bad_order: str
    ) -> None:
        upsert_file(conn, repo_id, "x.py")
        with pytest.raises(ValueError, match="invalid order_by"):
            list_files(conn, repo_id, order_by=bad_order)

    def test_rejects_case_insensitive_match(
        self, conn: sqlite3.Connection, repo_id: int
    ) -> None:
        """Whitelist is case-sensitive — lowercase direction is rejected."""
        upsert_file(conn, repo_id, "x.py")
        with pytest.raises(ValueError):
            list_files(conn, repo_id, order_by="importance_score desc")


# ---------------------------------------------------------------------------
# summaries: upsert / get
# ---------------------------------------------------------------------------


def test_upsert_summary_insert(conn: sqlite3.Connection, repo_id: int) -> None:
    sid = upsert_summary(conn, repo_id, "repo", "", "A high-level summary.")
    assert isinstance(sid, int) and sid > 0


def test_get_summary_roundtrip(conn: sqlite3.Connection, repo_id: int) -> None:
    upsert_summary(
        conn, repo_id, "file", "src/main.py",
        "File summary.", model="claude-3-5-sonnet", prompt_tokens=100,
    )
    row = get_summary(conn, repo_id, "file", "src/main.py")
    assert row is not None
    assert row["summary"] == "File summary."
    assert row["model"] == "claude-3-5-sonnet"
    assert row["prompt_tokens"] == 100


def test_get_summary_missing_returns_none(conn: sqlite3.Connection, repo_id: int) -> None:
    assert get_summary(conn, repo_id, "file", "no/such/path.py") is None


def test_upsert_summary_deduplication(conn: sqlite3.Connection, repo_id: int) -> None:
    """Second call with same natural key must return same id and update summary text."""
    sid1 = upsert_summary(conn, repo_id, "directory", "src/", "First version.")
    sid2 = upsert_summary(conn, repo_id, "directory", "src/", "Second version.")
    assert sid1 == sid2, "Upsert should return same id for existing row"
    row = get_summary(conn, repo_id, "directory", "src/")
    assert row["summary"] == "Second version."


def test_upsert_summary_updates_extra_fields(conn: sqlite3.Connection, repo_id: int) -> None:
    upsert_summary(conn, repo_id, "repo", "", "v1", completion_tokens=50)
    upsert_summary(conn, repo_id, "repo", "", "v2", completion_tokens=75)
    row = get_summary(conn, repo_id, "repo", "")
    assert row["completion_tokens"] == 75


def test_get_summary_returns_plain_dict(conn: sqlite3.Connection, repo_id: int) -> None:
    upsert_summary(conn, repo_id, "repo", "", "s")
    row = get_summary(conn, repo_id, "repo", "")
    assert isinstance(row, dict)


# ---------------------------------------------------------------------------
# context_bundles: save / get
# ---------------------------------------------------------------------------


def test_save_bundle_returns_int(conn: sqlite3.Connection, repo_id: int) -> None:
    bid = save_bundle(conn, repo_id, "ask", 8000, 4000, "context text", ["a.py", "b.py"])
    assert isinstance(bid, int) and bid > 0


def test_get_bundle_roundtrip(conn: sqlite3.Connection, repo_id: int) -> None:
    paths = ["src/main.py", "src/utils.py", "README.md"]
    bid = save_bundle(conn, repo_id, "review", 16000, 9000, "bundle content", paths)
    bundle = get_bundle(conn, bid)
    assert bundle is not None
    assert bundle["task_type"] == "review"
    assert bundle["token_budget"] == 16000
    assert bundle["token_count"] == 9000
    assert bundle["content"] == "bundle content"
    assert bundle["file_paths"] == paths


def test_get_bundle_file_paths_is_list(conn: sqlite3.Connection, repo_id: int) -> None:
    bid = save_bundle(conn, repo_id, "ask", 4000, 2000, "x", ["a.py"])
    bundle = get_bundle(conn, bid)
    assert isinstance(bundle["file_paths"], list)


def test_get_bundle_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert get_bundle(conn, 99999) is None


def test_save_bundle_empty_file_paths(conn: sqlite3.Connection, repo_id: int) -> None:
    bid = save_bundle(conn, repo_id, "ask", 4000, 0, "", [])
    bundle = get_bundle(conn, bid)
    assert bundle["file_paths"] == []


# ---------------------------------------------------------------------------
# runs: create / update / list
# ---------------------------------------------------------------------------


def test_create_run_returns_int(conn: sqlite3.Connection, repo_id: int) -> None:
    rid = create_run(conn, repo_id, "ask", "Explain the auth flow", "claude-3-5-sonnet")
    assert isinstance(rid, int) and rid > 0


def test_create_run_default_status_is_running(conn: sqlite3.Connection, repo_id: int) -> None:
    rid = create_run(conn, repo_id, "ask", "task", "model")
    runs = list_runs(conn, repo_id)
    assert runs[0]["id"] == rid
    assert runs[0]["status"] == "running"


def test_update_run_fields(conn: sqlite3.Connection, repo_id: int) -> None:
    rid = create_run(conn, repo_id, "ask", "task", "model")
    update_run(conn, rid, prompt_tokens=500, completion_tokens=200, cost_usd=0.01)
    runs = list_runs(conn, repo_id)
    row = runs[0]
    assert row["prompt_tokens"] == 500
    assert row["completion_tokens"] == 200
    assert row["cost_usd"] == pytest.approx(0.01)


def test_update_run_status_completed_sets_completed_at(
    conn: sqlite3.Connection, repo_id: int
) -> None:
    rid = create_run(conn, repo_id, "ask", "task", "model")
    update_run(conn, rid, status="completed", result="done")
    runs = list_runs(conn, repo_id)
    row = runs[0]
    assert row["status"] == "completed"
    assert row["completed_at"] is not None
    assert row["result"] == "done"


def test_update_run_status_failed_sets_completed_at(
    conn: sqlite3.Connection, repo_id: int
) -> None:
    rid = create_run(conn, repo_id, "ask", "task", "model")
    update_run(conn, rid, status="failed", error_message="timeout")
    runs = list_runs(conn, repo_id)
    row = runs[0]
    assert row["status"] == "failed"
    assert row["completed_at"] is not None
    assert row["error_message"] == "timeout"


def test_update_run_no_fields_raises(conn: sqlite3.Connection, repo_id: int) -> None:
    rid = create_run(conn, repo_id, "ask", "task", "model")
    with pytest.raises(ValueError):
        update_run(conn, rid)


def test_list_runs_all(conn: sqlite3.Connection) -> None:
    rid1 = create_repo(conn, "/repos/p", "p")
    rid2 = create_repo(conn, "/repos/q", "q")
    create_run(conn, rid1, "ask", "t", "m")
    create_run(conn, rid2, "ask", "t", "m")
    runs = list_runs(conn)
    assert len(runs) == 2


def test_list_runs_repo_filter(conn: sqlite3.Connection) -> None:
    rid1 = create_repo(conn, "/repos/p2", "p2")
    rid2 = create_repo(conn, "/repos/q2", "q2")
    create_run(conn, rid1, "ask", "t", "m")
    create_run(conn, rid1, "review", "t", "m")
    create_run(conn, rid2, "ask", "t", "m")
    runs = list_runs(conn, repo_id=rid1)
    assert len(runs) == 2
    assert all(r["repo_id"] == rid1 for r in runs)


def test_list_runs_limit(conn: sqlite3.Connection, repo_id: int) -> None:
    for i in range(5):
        create_run(conn, repo_id, "ask", f"task {i}", "model")
    runs = list_runs(conn, repo_id=repo_id, limit=3)
    assert len(runs) == 3


def test_list_runs_ordered_desc(conn: sqlite3.Connection, repo_id: int) -> None:
    r1 = create_run(conn, repo_id, "ask", "first", "model")
    r2 = create_run(conn, repo_id, "ask", "second", "model")
    runs = list_runs(conn, repo_id=repo_id, limit=10)
    ids = [r["id"] for r in runs]
    # Most recent first (highest id first for sequential inserts)
    assert ids[0] > ids[-1]


def test_list_runs_returns_plain_dicts(conn: sqlite3.Connection, repo_id: int) -> None:
    create_run(conn, repo_id, "ask", "t", "m")
    rows = list_runs(conn, repo_id=repo_id)
    assert all(isinstance(r, dict) for r in rows)
