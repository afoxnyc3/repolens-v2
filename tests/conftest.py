"""Shared pytest fixtures for repolens tests."""

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db():
    """Provide a temporary SQLite connection for tests.

    Yields a sqlite3.Connection backed by a temp file.
    The file is removed after the test completes.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_repo_path(tmp_path: Path) -> Path:
    """Create a minimal fake repository structure for tests that don't need real files."""
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main():\n    pass\n")
    (repo / "README.md").write_text("# Sample repo\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "sample"\n')
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_placeholder(): pass\n")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    return repo
