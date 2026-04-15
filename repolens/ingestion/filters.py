"""File-level filters for the ingestion pipeline.

Functions
---------
load_gitignore(repo_path)
    Parse the .gitignore at the repo root. Returns a callable matcher or None.

is_ignored(path, gitignore_rules, custom_patterns)
    Return True if path should be excluded (gitignore match, custom pattern match,
    or inside .git/).

is_binary(path)
    Return True if the file appears to be binary (null byte in first 8 KB).

is_oversized(path, max_bytes=1_000_000)
    Return True if the file is larger than max_bytes.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Callable, Optional, Sequence


def load_gitignore(repo_path: str | Path) -> Optional[Callable[[str], bool]]:
    """Parse the .gitignore at *repo_path* root.

    Returns a callable ``matcher(path: str) -> bool`` (True = ignored) if a
    .gitignore file exists, otherwise returns None.
    """
    import gitignore_parser  # local import so the rest of the module is usable without it

    gitignore_path = Path(repo_path) / ".gitignore"
    if not gitignore_path.is_file():
        return None
    return gitignore_parser.parse_gitignore(str(gitignore_path))


def is_ignored(
    path: str | Path,
    gitignore_rules: Optional[Callable[[str], bool]],
    custom_patterns: Sequence[str] = (),
) -> bool:
    """Return True if *path* should be excluded from ingestion.

    Exclusion criteria (any one is sufficient):
    - The path contains a ``.git`` component (always excluded).
    - *gitignore_rules* is set and matches the path.
    - The filename or any path component matches a pattern in *custom_patterns*
      (fnmatch glob syntax, matched against the full path string AND the basename).
    """
    path = Path(path)
    path_str = str(path)

    # Always filter .git/
    if ".git" in path.parts:
        return True

    # gitignore-parser match (accepts absolute or relative paths)
    if gitignore_rules is not None and gitignore_rules(path_str):
        return True

    # Custom glob patterns against full path and basename
    basename = path.name
    for pattern in custom_patterns:
        if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(basename, pattern):
            return True

    return False


def is_binary(path: str | Path) -> bool:
    """Return True if *path* appears to be a binary file.

    Reads up to the first 8 192 bytes and checks for a null byte.
    Unreadable files are treated as binary (safe default).
    """
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def is_oversized(path: str | Path, max_bytes: int = 1_000_000) -> bool:
    """Return True if *path* is larger than *max_bytes* (default 1 MB).

    Stat failures (missing file, permission error) return True as a safe default.
    """
    try:
        return Path(path).stat().st_size > max_bytes
    except OSError:
        return True
