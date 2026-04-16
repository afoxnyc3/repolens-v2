"""FastAPI application for repolens.

Exposes HTTP endpoints that mirror the CLI's repo management commands:
/repos (GET/POST), /repos/{id} (GET), /repos/{id}/scan (POST),
/repos/{id}/classify (POST).

Run locally with:
    uvicorn repolens.api.main:app --port 8765
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from repolens import config
from repolens.ai.executor import execute_task
from repolens.classification.classifier import classify_file, score_file
from repolens.context.packager import build_context
from repolens.db.repository import (
    create_repo,
    get_repo,
    get_run,
    list_files,
    list_repos,
    list_runs,
    save_bundle,
    upsert_file,
)
from repolens.db.schema import init_db
from repolens.ingestion.scanner import scan_repo


# ---------------------------------------------------------------------------
# Lifespan: init the DB schema on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the schema exists before serving requests."""
    init_db()
    yield


app = FastAPI(
    title="Repolens API",
    description="HTTP interface for the Repolens repo intelligence CLI.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Connection dependency
# ---------------------------------------------------------------------------


def get_conn():
    """Yield a per-request SQLite connection with row_factory + FK enforcement."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class RepoOut(BaseModel):
    id: int
    path: str
    name: str
    file_count: Optional[int] = None
    total_size_bytes: Optional[int] = None
    ingested_at: Optional[int] = None
    last_scanned_at: Optional[int] = None
    created_at: Optional[int] = None


class RepoIn(BaseModel):
    path: str = Field(..., description="Absolute or relative path to the repo root.")
    name: Optional[str] = Field(None, description="Human-readable name; defaults to dirname.")
    ignore: Optional[list[str]] = Field(
        None, description="Extra ignore patterns applied on top of .gitignore."
    )


class ScanResult(BaseModel):
    repo_id: int
    scanned: int
    skipped: int


class ClassifyResult(BaseModel):
    repo_id: int
    classified: int
    categories: dict[str, int]


class ContextOut(BaseModel):
    repo_id: int
    task: str
    token_budget: int
    token_count: int
    file_paths: list[str]
    content: str
    bundle_id: int


class RunIn(BaseModel):
    task_type: str = Field(..., description="Task category e.g. 'analyze', 'ask'.")
    description: Optional[str] = Field(
        None, description="Free-text task description; defaults to task_type."
    )
    budget: int = Field(32000, description="Token budget for context assembly.")
    model: Optional[str] = Field(None, description="Override REPOLENS_MODEL.")


class RunOut(BaseModel):
    id: int
    repo_id: Optional[int] = None
    bundle_id: Optional[int] = None
    task_type: Optional[str] = None
    task_description: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    result: Optional[str] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[int] = None
    completed_at: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_repo(conn: sqlite3.Connection, repo_id: int) -> dict:
    row = get_repo(conn, repo_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"repo {repo_id} not found",
        )
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/repos", response_model=list[RepoOut])
def get_repos(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    """Return all tracked repositories."""
    return list_repos(conn)


@app.post(
    "/repos",
    response_model=RepoOut,
    status_code=status.HTTP_201_CREATED,
)
def post_repo(
    body: RepoIn,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """Register a new repository and run an initial scan.

    Mirrors `repolens ingest`: walks the tree, applies ignore rules, upserts
    file metadata, and refreshes repo-level aggregate stats.
    """
    abs_path = Path(body.path).resolve()
    if not abs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"path does not exist: {abs_path}",
        )
    if not abs_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"path is not a directory: {abs_path}",
        )

    existing = get_repo(conn, str(abs_path))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"repo already registered at {abs_path} (id={existing['id']})",
        )

    repo_name = body.name or abs_path.name
    repo_id = create_repo(conn, str(abs_path), repo_name)

    custom_ignores = list(body.ignore) if body.ignore else []
    records = scan_repo(str(abs_path), custom_ignores)

    for rec in records:
        upsert_file(
            conn,
            repo_id,
            rec.relative_path,
            extension=rec.extension,
            size_bytes=rec.size_bytes,
            mtime=rec.mtime,
            content_hash=rec.content_hash,
        )

    now = int(time.time())
    total_size = sum(r.size_bytes for r in records)
    with conn:
        conn.execute(
            """
            UPDATE repos
            SET file_count = ?,
                total_size_bytes = ?,
                last_scanned_at = ?,
                ingested_at = COALESCE(ingested_at, ?)
            WHERE id = ?
            """,
            (len(records), total_size, now, now, repo_id),
        )

    row = get_repo(conn, repo_id)
    assert row is not None  # just created
    return row


@app.get("/repos/{repo_id}", response_model=RepoOut)
def get_repo_by_id(
    repo_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """Return a single repo's details."""
    return _require_repo(conn, repo_id)


@app.post("/repos/{repo_id}/scan", response_model=ScanResult)
def post_scan(
    repo_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
) -> ScanResult:
    """Re-scan a registered repo and refresh file metadata + aggregate stats."""
    repo_row = _require_repo(conn, repo_id)
    repo_path = repo_row["path"]

    if not Path(repo_path).exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"repo path no longer exists on disk: {repo_path}",
        )

    records = scan_repo(repo_path, [])

    total_files = sum(len(files) for _, _, files in os.walk(repo_path))
    skipped = total_files - len(records)

    for rec in records:
        upsert_file(
            conn,
            repo_id,
            rec.relative_path,
            extension=rec.extension,
            size_bytes=rec.size_bytes,
            mtime=rec.mtime,
            content_hash=rec.content_hash,
        )

    now = int(time.time())
    total_size = sum(r.size_bytes for r in records)
    with conn:
        conn.execute(
            """
            UPDATE repos
            SET file_count = ?,
                total_size_bytes = ?,
                last_scanned_at = ?
            WHERE id = ?
            """,
            (len(records), total_size, now, repo_id),
        )

    return ScanResult(repo_id=repo_id, scanned=len(records), skipped=skipped)


@app.post("/repos/{repo_id}/classify", response_model=ClassifyResult)
def post_classify(
    repo_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
) -> ClassifyResult:
    """Classify and score every file in a repo. Returns category breakdown."""
    _require_repo(conn, repo_id)

    files = list_files(conn, repo_id)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no files found; POST /repos to ingest first",
        )

    counts: dict[str, int] = {}
    for f in files:
        rel_path = f["path"]
        extension = f.get("extension") or ""
        size_bytes = f.get("size_bytes") or 0
        mtime = f.get("mtime") or 0

        category = classify_file(rel_path, extension)
        score = score_file(rel_path, category, size_bytes, mtime)

        upsert_file(
            conn,
            repo_id,
            rel_path,
            classification=category,
            importance_score=score,
        )

        counts[category] = counts.get(category, 0) + 1

    return ClassifyResult(
        repo_id=repo_id,
        classified=len(files),
        categories=counts,
    )


# ---------------------------------------------------------------------------
# Context & run endpoints
# ---------------------------------------------------------------------------


@app.get("/repos/{repo_id}/context", response_model=ContextOut)
def get_context(
    repo_id: int,
    task: str = "analyze",
    budget: int = 32000,
    conn: sqlite3.Connection = Depends(get_conn),
) -> ContextOut:
    """Build and persist a context bundle for a repo + task."""
    _require_repo(conn, repo_id)

    try:
        bundle = build_context(conn, repo_id, task, token_budget=budget)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    bundle_id = save_bundle(
        conn,
        repo_id=repo_id,
        task_type=task,
        token_budget=budget,
        token_count=bundle.token_count,
        content=bundle.content,
        file_paths=bundle.file_paths,
    )

    return ContextOut(
        repo_id=repo_id,
        task=task,
        token_budget=budget,
        token_count=bundle.token_count,
        file_paths=bundle.file_paths,
        content=bundle.content,
        bundle_id=bundle_id,
    )


@app.post("/repos/{repo_id}/run", response_model=RunOut)
def post_run(
    repo_id: int,
    body: RunIn,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """Execute a task against a repo synchronously and return the run row."""
    _require_repo(conn, repo_id)

    description = body.description or body.task_type

    try:
        result = execute_task(
            conn,
            repo_id,
            body.task_type,
            description,
            token_budget=body.budget,
            model=body.model,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # AI/SDK failures — surface as 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    row = get_run(conn, result["run_id"])
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"run {result['run_id']} was created but could not be read back",
        )
    return row


@app.get("/runs/{run_id}", response_model=RunOut)
def get_run_by_id(
    run_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """Return a single run row."""
    row = get_run(conn, run_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run {run_id} not found",
        )
    return row


@app.get("/runs", response_model=list[RunOut])
def get_runs(
    repo_id: Optional[int] = None,
    limit: int = 10,
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[dict]:
    """List recent runs, optionally filtered by repo_id."""
    if limit < 1 or limit > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 1000",
        )
    return list_runs(conn, repo_id=repo_id, limit=limit)
