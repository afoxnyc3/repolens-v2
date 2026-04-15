"""Directory scanner for the ingestion pipeline.

Classes
-------
FileRecord
    Dataclass capturing per-file metadata produced by a scan.

Functions
---------
scan_repo(path, custom_ignores) -> list[FileRecord]
    Walk *path* recursively, apply ingestion filters, compute sha256 hashes,
    and return a sorted list of FileRecord objects.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from repolens.ingestion.filters import (
    is_binary,
    is_ignored,
    is_oversized,
    load_gitignore,
)


@dataclass
class FileRecord:
    """Metadata and content hash for a single ingested file."""

    repo_root: str
    relative_path: str
    extension: str
    size_bytes: int
    mtime: int  # unix timestamp (integer seconds)
    content_hash: str  # sha256 hex digest


def _sha256(path: str) -> str:
    """Return the sha256 hex digest of *path*'s contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_repo(
    path: str,
    custom_ignores: Sequence[str] = (),
) -> list[FileRecord]:
    """Walk *path* and return a sorted list of FileRecord objects.

    Files are excluded if they:
    - live inside ``.git/``
    - are matched by the repo's ``.gitignore`` (if one exists)
    - match any pattern in *custom_ignores*
    - appear to be binary (null byte in first 8 KB)
    - exceed 1 MB

    The returned list is sorted by ``relative_path`` (ascending).

    Parameters
    ----------
    path:
        Absolute or relative path to the repository root.
    custom_ignores:
        Additional fnmatch glob patterns to exclude (e.g. ``["*.lock"]``).
    """
    root = Path(path).resolve()
    root_str = str(root)

    gitignore_rules = load_gitignore(root_str)
    records: list[FileRecord] = []

    # Iterative scandir walk (more efficient than os.walk)
    dirs_to_visit: list[str] = [root_str]

    while dirs_to_visit:
        current_dir = dirs_to_visit.pop()
        try:
            entries = list(os.scandir(current_dir))
        except PermissionError:
            continue

        for entry in entries:
            # Resolve the full path once
            full_path = entry.path

            # Build a Path for filter functions
            entry_path = Path(full_path)

            if entry.is_dir(follow_symlinks=False):
                # Check before descending so we skip .git/ entirely
                if is_ignored(entry_path, gitignore_rules, custom_ignores):
                    continue
                dirs_to_visit.append(full_path)
                continue

            if not entry.is_file(follow_symlinks=False):
                # Skip symlinks and other non-regular entries
                continue

            # Apply all filters
            if is_ignored(entry_path, gitignore_rules, custom_ignores):
                continue
            if is_binary(full_path):
                continue
            if is_oversized(full_path):
                continue

            # Stat for size and mtime (reuse from scandir where possible)
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            size_bytes = stat.st_size
            mtime = int(stat.st_mtime)

            # Content hash
            try:
                content_hash = _sha256(full_path)
            except OSError:
                continue

            relative_path = str(entry_path.relative_to(root))
            extension = entry_path.suffix  # includes leading dot, e.g. ".py"

            records.append(
                FileRecord(
                    repo_root=root_str,
                    relative_path=relative_path,
                    extension=extension,
                    size_bytes=size_bytes,
                    mtime=mtime,
                    content_hash=content_hash,
                )
            )

    records.sort(key=lambda r: r.relative_path)
    return records
