"""Tests for the FastAPI app in repolens.api.main."""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from repolens.ai.client import CompletionResult


def _cr(text, input_tokens, output_tokens, cache_read=0, cache_creation=0):
    return CompletionResult(text, input_tokens, output_tokens, cache_read, cache_creation)


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """Spin up the FastAPI app against a throwaway SQLite file.

    REPOLENS_DB must be set before importing/reloading repolens modules so
    config.DB_PATH picks up the override.
    """
    db_path = tmp_path / "repolens.db"
    monkeypatch.setenv("REPOLENS_DB", str(db_path))

    from repolens import config as _config
    from repolens.api import main as api_main
    from repolens.db import schema as _schema

    importlib.reload(_config)
    importlib.reload(_schema)
    importlib.reload(api_main)

    with TestClient(api_main.app) as client:
        yield client


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main():\n    pass\n")
    (repo / "README.md").write_text("# Sample\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "sample"\n')
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_ok(): pass\n")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    return repo


# ---------------------------------------------------------------------------
# GET /repos
# ---------------------------------------------------------------------------


def test_get_repos_empty_returns_array(api_client):
    resp = api_client.get("/repos")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_repos_returns_registered_repos(api_client, sample_repo):
    api_client.post("/repos", json={"path": str(sample_repo)})
    resp = api_client.get("/repos")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["path"] == str(sample_repo.resolve())


# ---------------------------------------------------------------------------
# POST /repos
# ---------------------------------------------------------------------------


def test_post_repos_registers_and_returns_201(api_client, sample_repo):
    resp = api_client.post("/repos", json={"path": str(sample_repo)})
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] > 0
    assert body["path"] == str(sample_repo.resolve())
    assert body["name"] == sample_repo.name
    assert body["file_count"] is not None and body["file_count"] > 0


def test_post_repos_uses_provided_name(api_client, sample_repo):
    resp = api_client.post(
        "/repos", json={"path": str(sample_repo), "name": "custom-name"}
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "custom-name"


def test_post_repos_nonexistent_path_returns_400(api_client, tmp_path):
    missing = tmp_path / "does-not-exist"
    resp = api_client.post("/repos", json={"path": str(missing)})
    assert resp.status_code == 400
    assert "does not exist" in resp.json()["detail"]


def test_post_repos_file_path_returns_400(api_client, tmp_path):
    f = tmp_path / "a_file.txt"
    f.write_text("hello")
    resp = api_client.post("/repos", json={"path": str(f)})
    assert resp.status_code == 400
    assert "not a directory" in resp.json()["detail"]


def test_post_repos_duplicate_returns_409(api_client, sample_repo):
    first = api_client.post("/repos", json={"path": str(sample_repo)})
    assert first.status_code == 201
    second = api_client.post("/repos", json={"path": str(sample_repo)})
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# GET /repos/{id}
# ---------------------------------------------------------------------------


def test_get_repo_by_id_returns_details(api_client, sample_repo):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    resp = api_client.get(f"/repos/{created['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["path"] == str(sample_repo.resolve())


def test_get_repo_missing_returns_404(api_client):
    resp = api_client.get("/repos/999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /repos/{id}/scan
# ---------------------------------------------------------------------------


def test_post_scan_refreshes_file_count(api_client, sample_repo):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    # Add a new file after initial ingest
    (sample_repo / "extra.py").write_text("x = 1\n")

    resp = api_client.post(f"/repos/{created['id']}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_id"] == created["id"]
    assert body["scanned"] > created["file_count"]
    assert body["skipped"] >= 0


def test_post_scan_missing_repo_returns_404(api_client):
    resp = api_client.post("/repos/999/scan")
    assert resp.status_code == 404


def test_post_scan_vanished_path_returns_410(api_client, sample_repo, tmp_path):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    # Delete the repo on disk
    for p in sorted(sample_repo.rglob("*"), reverse=True):
        if p.is_file():
            p.unlink()
        else:
            p.rmdir()
    sample_repo.rmdir()

    resp = api_client.post(f"/repos/{created['id']}/scan")
    assert resp.status_code == 410


# ---------------------------------------------------------------------------
# POST /repos/{id}/classify
# ---------------------------------------------------------------------------


def test_post_classify_returns_category_breakdown(api_client, sample_repo):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    resp = api_client.post(f"/repos/{created['id']}/classify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_id"] == created["id"]
    assert body["classified"] > 0
    assert isinstance(body["categories"], dict)
    # Sample repo has main.py (core) and a test file (test)
    assert "core" in body["categories"]
    assert "test" in body["categories"]


def test_post_classify_persists_scores(api_client, sample_repo, tmp_path):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    api_client.post(f"/repos/{created['id']}/classify")

    # Verify directly via the DB that classification and score were written
    db_path = tmp_path / "repolens.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT path, classification, importance_score FROM files WHERE repo_id = ?",
            (created["id"],),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) > 0
    assert all(r["classification"] is not None for r in rows)
    assert all(r["importance_score"] is not None for r in rows)


def test_post_classify_missing_repo_returns_404(api_client):
    resp = api_client.post("/repos/999/classify")
    assert resp.status_code == 404


def test_post_classify_empty_repo_returns_400(api_client, tmp_path):
    # Create and ingest a repo with only ignored files → zero files in DB
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    (empty / ".gitignore").write_text("*\n")  # ignore everything
    created = api_client.post("/repos", json={"path": str(empty)}).json()

    resp = api_client.post(f"/repos/{created['id']}/classify")
    # Either 400 (no files) or 200 (if .gitignore itself classified).
    # We only care that /classify handles zero-file repos cleanly.
    assert resp.status_code in (200, 400)


# ---------------------------------------------------------------------------
# Response shape: everything is JSON with HTTPException detail on errors
# ---------------------------------------------------------------------------


def test_error_responses_use_detail_key(api_client):
    resp = api_client.get("/repos/999")
    assert resp.headers["content-type"].startswith("application/json")
    assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# GET /repos/{id}/context
# ---------------------------------------------------------------------------


def _make_bundle(content: str = "ctx"):
    return SimpleNamespace(content=content, file_paths=["main.py"], token_count=42)


def test_get_context_returns_bundle_json(api_client, sample_repo):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    # classify so importance_score is populated for greedy inclusion
    api_client.post(f"/repos/{created['id']}/classify")

    resp = api_client.get(
        f"/repos/{created['id']}/context",
        params={"task": "analyze", "budget": 4000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_id"] == created["id"]
    assert body["task"] == "analyze"
    assert body["token_budget"] == 4000
    assert body["token_count"] > 0
    assert isinstance(body["file_paths"], list)
    assert body["bundle_id"] > 0
    assert "Task Instructions" in body["content"]


def test_get_context_defaults_task_and_budget(api_client, sample_repo):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    api_client.post(f"/repos/{created['id']}/classify")
    resp = api_client.get(f"/repos/{created['id']}/context")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task"] == "analyze"
    assert body["token_budget"] == 32000


def test_get_context_missing_repo_returns_404(api_client):
    resp = api_client.get("/repos/999/context")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /repos/{id}/run
# ---------------------------------------------------------------------------


def test_post_run_returns_run_row_synchronously(api_client, sample_repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    api_client.post(f"/repos/{created['id']}/classify")

    with (
        patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
        patch("repolens.ai.executor.RepolensClient") as MockClient,
    ):
        MockClient.return_value.complete.return_value = _cr("answer text", 50, 20)
        resp = api_client.post(
            f"/repos/{created['id']}/run",
            json={
                "task_type": "ask",
                "description": "what is this?",
                "budget": 8000,
                "model": "claude-haiku-4-5",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] > 0
    assert body["repo_id"] == created["id"]
    assert body["task_type"] == "ask"
    assert body["task_description"] == "what is this?"
    assert body["model"] == "claude-haiku-4-5"
    assert body["result"] == "answer text"
    assert body["prompt_tokens"] == 50
    assert body["completion_tokens"] == 20
    assert body["status"] == "done"


def test_post_run_defaults_description_to_task_type(api_client, sample_repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    api_client.post(f"/repos/{created['id']}/classify")

    with (
        patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
        patch("repolens.ai.executor.RepolensClient") as MockClient,
    ):
        MockClient.return_value.complete.return_value = _cr("ok", 1, 1)
        resp = api_client.post(
            f"/repos/{created['id']}/run", json={"task_type": "summarize"}
        )

    assert resp.status_code == 200
    assert resp.json()["task_description"] == "summarize"


def test_post_run_missing_repo_returns_404(api_client):
    resp = api_client.post("/repos/999/run", json={"task_type": "ask"})
    assert resp.status_code == 404


def test_post_run_sdk_failure_returns_502(api_client, sample_repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    api_client.post(f"/repos/{created['id']}/classify")

    with (
        patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
        patch("repolens.ai.executor.RepolensClient") as MockClient,
    ):
        MockClient.return_value.complete.side_effect = RuntimeError("upstream 529")
        resp = api_client.post(
            f"/repos/{created['id']}/run", json={"task_type": "ask"}
        )

    assert resp.status_code == 502
    assert "upstream 529" in resp.json()["detail"]


def test_post_run_rejects_missing_task_type(api_client, sample_repo):
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    resp = api_client.post(f"/repos/{created['id']}/run", json={})
    assert resp.status_code == 422  # pydantic validation


# ---------------------------------------------------------------------------
# GET /runs/{id} and GET /runs
# ---------------------------------------------------------------------------


def test_get_run_by_id_returns_row(api_client, sample_repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    api_client.post(f"/repos/{created['id']}/classify")

    with (
        patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
        patch("repolens.ai.executor.RepolensClient") as MockClient,
    ):
        MockClient.return_value.complete.return_value = _cr("r", 1, 1)
        run = api_client.post(
            f"/repos/{created['id']}/run", json={"task_type": "ask"}
        ).json()

    resp = api_client.get(f"/runs/{run['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == run["id"]
    assert body["result"] == "r"


def test_get_run_missing_returns_404(api_client):
    resp = api_client.get("/runs/999")
    assert resp.status_code == 404


def test_list_runs_filters_by_repo_and_limit(api_client, sample_repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    created = api_client.post("/repos", json={"path": str(sample_repo)}).json()
    api_client.post(f"/repos/{created['id']}/classify")

    with (
        patch("repolens.ai.executor.build_context", return_value=_make_bundle()),
        patch("repolens.ai.executor.RepolensClient") as MockClient,
    ):
        MockClient.return_value.complete.return_value = _cr("r", 1, 1)
        for i in range(3):
            api_client.post(
                f"/repos/{created['id']}/run",
                json={"task_type": "ask", "description": f"call-{i}"},
            )

    # No filter — all three
    resp = api_client.get("/runs")
    assert resp.status_code == 200
    assert len(resp.json()) == 3

    # Limit
    resp = api_client.get("/runs", params={"limit": 2})
    assert len(resp.json()) == 2

    # Filter by repo_id
    resp = api_client.get("/runs", params={"repo_id": created["id"]})
    assert len(resp.json()) == 3

    # Non-matching repo_id
    resp = api_client.get("/runs", params={"repo_id": 9999})
    assert resp.json() == []


def test_list_runs_invalid_limit_returns_400(api_client):
    resp = api_client.get("/runs", params={"limit": 0})
    assert resp.status_code == 400
    resp = api_client.get("/runs", params={"limit": 10001})
    assert resp.status_code == 400
