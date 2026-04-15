"""Rules-based file classifier and importance scorer."""

from __future__ import annotations

import time
from pathlib import PurePosixPath

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_WEIGHTS: dict[str, float] = {
    "core": 1.0,
    "config": 0.8,
    "test": 0.6,
    "docs": 0.5,
    "build": 0.3,
    "generated": 0.0,
    "other": 0.2,
}

_CORE_EXTENSIONS = frozenset(
    {".py", ".ts", ".js", ".go", ".rs", ".java", ".rb", ".swift", ".c", ".cpp", ".h"}
)

_DOCS_EXTENSIONS = frozenset({".md", ".rst", ".txt"})

_CONFIG_EXTENSIONS = frozenset(
    {".yaml", ".toml", ".json", ".ini", ".cfg", ".env"}
)

_CONFIG_FILENAMES = frozenset(
    {"pyproject.toml", "setup.py", "setup.cfg", "Makefile", "Dockerfile", ".dockerignore"}
)

_GENERATED_SEGMENTS = frozenset({"__pycache__", "dist", "build", ".git"})

_ENTRY_POINTS = frozenset({"main.py", "app.py", "index.py", "__init__.py"})


# ---------------------------------------------------------------------------
# classify_file
# ---------------------------------------------------------------------------


def classify_file(relative_path: str, extension: str) -> str:
    """Classify a file into a category string.

    Categories (returned):
        core | test | config | docs | build | generated | other

    Rules applied in priority order (first match wins).

    Args:
        relative_path: POSIX-style path relative to the repo root,
            e.g. ``"src/utils/helper.py"`` or ``"__pycache__/mod.pyc"``.
        extension: File extension including the leading dot, e.g. ``".py"``.
            Pass ``""`` for extensionless files.

    Returns:
        One of the seven category strings.
    """
    path = PurePosixPath(relative_path)
    filename = path.name
    parts = path.parts  # tuple of path components

    # Rule 1: generated segments anywhere in the path
    for part in parts[:-1]:  # directories only
        if part in _GENERATED_SEGMENTS:
            return "generated"
    # Also catch if the file itself is inside one of these (redundant but explicit)
    if any(seg in _GENERATED_SEGMENTS for seg in parts):
        return "generated"

    # Rule 2: test files
    stem = path.stem  # filename without extension
    if (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or "/tests/" in f"/{relative_path}/"
        or (len(parts) > 1 and "tests" in parts[:-1])
    ):
        return "test"

    # Rule 3: docs — must be a docs extension AND (in docs/ OR README*)
    if extension in _DOCS_EXTENSIONS:
        in_docs = any(p == "docs" for p in parts[:-1])
        is_readme = filename.startswith("README")
        if in_docs or is_readme:
            return "docs"

    # Rule 4: config — explicit filenames, or config extension at root depth (<= 1)
    depth = len(parts) - 1  # number of directory components
    if filename in _CONFIG_FILENAMES:
        return "config"
    if extension in _CONFIG_EXTENSIONS and depth <= 1:
        return "config"

    # Rule 5: core source extensions
    if extension in _CORE_EXTENSIONS:
        return "core"

    # Rule 6: everything else
    return "other"


# ---------------------------------------------------------------------------
# score_file
# ---------------------------------------------------------------------------


def score_file(
    relative_path: str,
    category: str,
    size_bytes: int,
    mtime: int,
) -> float:
    """Compute an importance score in [0.0, 1.0] for a file.

    Args:
        relative_path: POSIX-style path relative to the repo root.
        category: Result of :func:`classify_file` for this file.
        size_bytes: File size in bytes.
        mtime: Last-modified timestamp as a Unix epoch integer.

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    score = _BASE_WEIGHTS.get(category, 0.2)

    path = PurePosixPath(relative_path)
    depth = len(path.parts) - 1  # directory depth

    # Depth penalty: floor at 0.5 of original score
    score *= max(0.5, 1.0 - 0.05 * depth)

    # Size penalty
    if size_bytes > 20_000:
        score *= 0.8

    # Recency bonus
    now = int(time.time())
    if mtime > (now - 7 * 86400):
        score = min(1.0, score + 0.1)

    # Entry-point boost
    filename = path.name
    if filename in _ENTRY_POINTS and depth == 0:
        score = min(1.0, score + 0.2)

    return round(score, 6)
