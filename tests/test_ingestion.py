"""Tests for repolens.ingestion.filters."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repolens.ingestion.filters import (
    is_binary,
    is_ignored,
    is_oversized,
    load_gitignore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """Minimal repo with a .gitignore and a few files."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # .gitignore with a couple of patterns
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.env\n")

    # Source file (plain text, should not be ignored)
    (repo / "main.py").write_text("print('hello')\n")

    # Ignored by .gitignore
    pycache = repo / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-311.pyc").write_bytes(b"\x00\x01\x02")

    # .git directory
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\n\trepositoryformatversion = 0\n")

    # Binary file (PNG magic bytes + null byte)
    (repo / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00" + b"A" * 100)

    # Text file that happens to have .png extension but no null byte
    (repo / "fake_binary.png").write_bytes(b"not really binary at all")

    return repo


@pytest.fixture()
def oversized_file(tmp_path: Path) -> Path:
    """A file just over 1 MB."""
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * (1_000_001))
    return f


@pytest.fixture()
def normal_file(tmp_path: Path) -> Path:
    """A file just under 1 MB."""
    f = tmp_path / "small.txt"
    f.write_bytes(b"x" * (999_999))
    return f


# ---------------------------------------------------------------------------
# load_gitignore
# ---------------------------------------------------------------------------


def test_load_gitignore_returns_callable(sample_repo: Path) -> None:
    matcher = load_gitignore(sample_repo)
    assert callable(matcher)


def test_load_gitignore_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_gitignore(tmp_path) is None


# ---------------------------------------------------------------------------
# is_ignored — .git/ always filtered
# ---------------------------------------------------------------------------


def test_git_dir_filtered_with_no_rules(sample_repo: Path) -> None:
    git_config = sample_repo / ".git" / "config"
    assert is_ignored(git_config, None) is True


def test_git_dir_root_filtered(sample_repo: Path) -> None:
    assert is_ignored(sample_repo / ".git", None) is True


def test_git_dir_filtered_even_with_rules(sample_repo: Path) -> None:
    rules = load_gitignore(sample_repo)
    git_path = sample_repo / ".git" / "HEAD"
    assert is_ignored(git_path, rules) is True


# ---------------------------------------------------------------------------
# is_ignored — .gitignore patterns
# ---------------------------------------------------------------------------


def test_gitignore_pyc_ignored(sample_repo: Path) -> None:
    rules = load_gitignore(sample_repo)
    pyc = sample_repo / "module.pyc"
    assert is_ignored(pyc, rules) is True


def test_gitignore_pycache_dir_ignored(sample_repo: Path) -> None:
    rules = load_gitignore(sample_repo)
    pycache_file = sample_repo / "__pycache__" / "main.cpython-311.pyc"
    assert is_ignored(pycache_file, rules) is True


def test_gitignore_env_ignored(sample_repo: Path) -> None:
    rules = load_gitignore(sample_repo)
    env_file = sample_repo / ".env"
    assert is_ignored(env_file, rules) is True


def test_regular_py_not_ignored(sample_repo: Path) -> None:
    rules = load_gitignore(sample_repo)
    src = sample_repo / "main.py"
    assert is_ignored(src, rules) is False


# ---------------------------------------------------------------------------
# is_ignored — custom patterns
# ---------------------------------------------------------------------------


def test_custom_pattern_matches(tmp_path: Path) -> None:
    secret = tmp_path / "secrets.txt"
    secret.write_text("shhh")
    assert is_ignored(secret, None, custom_patterns=["*.txt"]) is True


def test_custom_pattern_no_false_positive(tmp_path: Path) -> None:
    py_file = tmp_path / "app.py"
    py_file.write_text("pass")
    assert is_ignored(py_file, None, custom_patterns=["*.txt"]) is False


# ---------------------------------------------------------------------------
# is_binary
# ---------------------------------------------------------------------------


def test_png_detected_as_binary(sample_repo: Path) -> None:
    assert is_binary(sample_repo / "image.png") is True


def test_text_file_not_binary(sample_repo: Path) -> None:
    assert is_binary(sample_repo / "main.py") is False


def test_file_without_null_not_binary(sample_repo: Path) -> None:
    # fake_binary.png has no null byte
    assert is_binary(sample_repo / "fake_binary.png") is False


def test_binary_with_inline_bytes(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 10)
    assert is_binary(f) is True


def test_empty_file_not_binary(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    assert is_binary(f) is False


# ---------------------------------------------------------------------------
# is_oversized
# ---------------------------------------------------------------------------


def test_oversized_file_flagged(oversized_file: Path) -> None:
    assert is_oversized(oversized_file) is True


def test_normal_file_not_flagged(normal_file: Path) -> None:
    assert is_oversized(normal_file) is False


def test_custom_threshold(tmp_path: Path) -> None:
    f = tmp_path / "medium.bin"
    f.write_bytes(b"x" * 500)
    assert is_oversized(f, max_bytes=499) is True
    assert is_oversized(f, max_bytes=500) is False
    assert is_oversized(f, max_bytes=501) is False


def test_missing_file_treated_as_oversized(tmp_path: Path) -> None:
    assert is_oversized(tmp_path / "does_not_exist.bin") is True
