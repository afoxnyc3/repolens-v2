"""Importance scorer for classified files.

A file's score is deterministic given the same inputs.  The score drives
greedy inclusion when the context packager is filling its token budget —
higher scores are packed first.

See DESIGN.md §2.3 for the rationale behind each adjustment.
"""

from __future__ import annotations

import time
from pathlib import PurePosixPath

# ---------------------------------------------------------------------------
# Scoring parameters
# ---------------------------------------------------------------------------

_BASE_WEIGHTS: dict[str, float] = {
    "core":      1.0,
    "config":    0.8,
    "test":      0.6,
    "docs":      0.5,
    "build":     0.3,
    "generated": 0.0,
    "other":     0.2,
}

_SIZE_PENALTY_BYTES = 20_000
_SIZE_PENALTY_FACTOR = 0.8

_RECENCY_WINDOW_SECONDS = 7 * 86_400
_RECENCY_BONUS = 0.1

_DEPTH_PENALTY_STEP = 0.05
_DEPTH_PENALTY_FLOOR = 0.5

_ENTRY_POINTS: frozenset[str] = frozenset(
    {"main.py", "app.py", "index.py", "__init__.py"}
)
_ENTRY_POINT_BONUS = 0.2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_file(
    relative_path: str,
    category: str,
    size_bytes: int,
    mtime: int,
) -> float:
    """Compute an importance score in ``[0.0, 1.0]`` for a file.

    Args:
        relative_path: POSIX-style path relative to the repo root.
        category:      Result of :func:`repolens.classification.classifier.classify_file`
                       for this file.  Unknown categories fall back to 0.2.
        size_bytes:    File size in bytes.
        mtime:         Last-modified timestamp as a Unix epoch integer.

    Returns:
        A float in ``[0.0, 1.0]`` rounded to 6 decimal places.
    """
    score = _BASE_WEIGHTS.get(category, 0.2)

    path = PurePosixPath(relative_path)
    depth = len(path.parts) - 1  # directory depth

    # Depth penalty: attenuates deeply nested files; floor at 0.5× base.
    score *= max(_DEPTH_PENALTY_FLOOR, 1.0 - _DEPTH_PENALTY_STEP * depth)

    # Size penalty: large files carry less signal per token.
    if size_bytes > _SIZE_PENALTY_BYTES:
        score *= _SIZE_PENALTY_FACTOR

    # Recency bonus: files touched within the last week get +0.1.
    now = int(time.time())
    if mtime > (now - _RECENCY_WINDOW_SECONDS):
        score = min(1.0, score + _RECENCY_BONUS)

    # Entry-point boost: top-level well-known filenames jump +0.2.
    filename = path.name
    if filename in _ENTRY_POINTS and depth == 0:
        score = min(1.0, score + _ENTRY_POINT_BONUS)

    return round(score, 6)
