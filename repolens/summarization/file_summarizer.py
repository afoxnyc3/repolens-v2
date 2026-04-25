"""File summarizer with content-hash-aware caching.

Public API
----------
summarize_file(conn, repo_id, file_record, client) -> str
    Return a summary for the given file, using the DB cache when the
    content hash is unchanged, otherwise calling the AI client and
    storing the result.
"""

from __future__ import annotations

import os
import sqlite3

from repolens.ai.prompts import file_summary_prompt
from repolens.db.repository import get_summary, upsert_summary
from repolens.ingestion.scanner import FileRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Approximate character cap before sending content to the AI.
# 200_000 chars ≈ 50K tokens, good enough for MVP.
_CONTENT_CHAR_LIMIT = 200_000

# Map lowercase file extension (without dot) to display language name.
_EXT_TO_LANGUAGE: dict[str, str] = {
    "py": "Python",
    "pyi": "Python",
    "ts": "TypeScript",
    "tsx": "TypeScript",
    "js": "JavaScript",
    "jsx": "JavaScript",
    "mjs": "JavaScript",
    "cjs": "JavaScript",
    "rs": "Rust",
    "go": "Go",
    "java": "Java",
    "kt": "Kotlin",
    "swift": "Swift",
    "rb": "Ruby",
    "php": "PHP",
    "cs": "C#",
    "cpp": "C++",
    "cc": "C++",
    "cxx": "C++",
    "c": "C",
    "h": "C",
    "hpp": "C++",
    "sh": "Shell",
    "bash": "Shell",
    "zsh": "Shell",
    "fish": "Shell",
    "md": "Markdown",
    "mdx": "Markdown",
    "json": "JSON",
    "yaml": "YAML",
    "yml": "YAML",
    "toml": "TOML",
    "ini": "INI",
    "sql": "SQL",
    "html": "HTML",
    "htm": "HTML",
    "css": "CSS",
    "scss": "CSS",
    "sass": "CSS",
    "less": "CSS",
    "xml": "XML",
    "dockerfile": "Dockerfile",
    "tf": "Terraform",
    "hcl": "HCL",
    "r": "R",
    "lua": "Lua",
    "scala": "Scala",
    "clj": "Clojure",
    "ex": "Elixir",
    "exs": "Elixir",
    "erl": "Erlang",
    "hs": "Haskell",
}


def _language_for_extension(extension: str) -> str:
    """Return a display language name for *extension*, or '' if unknown.

    Args:
        extension: File extension including the leading dot (e.g. '.py'),
                   or without (e.g. 'py'). Case-insensitive.
    """
    ext = extension.lstrip(".").lower()
    # Special case: bare filename 'Dockerfile' has no extension in scanner
    # (extension would be ''). The caller may pass '' directly.
    return _EXT_TO_LANGUAGE.get(ext, "")


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def summarize_file(
    conn: sqlite3.Connection,
    repo_id: int,
    file_record: FileRecord,
    client,
) -> str:
    """Return an AI-generated summary for *file_record*, using the DB cache.

    Cache hit: if a summary exists for (repo_id, 'file', relative_path) and
    its stored content_hash matches file_record.content_hash, the cached
    summary is returned without calling the AI.

    Cache miss / stale hash: reads the file, caps content at
    _CONTENT_CHAR_LIMIT characters, calls client.complete(), stores the
    result in the DB with the updated hash, and returns the summary text.

    Args:
        conn:        Open SQLite connection (row_factory need not be set;
                     repository functions set it internally).
        repo_id:     Foreign key to the repos table.
        file_record: FileRecord from the scanner; must have repo_root,
                     relative_path, extension, and content_hash populated.
        client:      A RepolensClient (or compatible mock). Must expose
                     .complete(prompt) -> CompletionResult and .model -> str.

    Returns:
        The summary text (2-4 sentences from the AI, or the cached copy).
    """
    # ------------------------------------------------------------------
    # 1. Cache check
    # ------------------------------------------------------------------
    cached = get_summary(conn, repo_id, "file", file_record.relative_path)
    if cached is not None and cached.get("content_hash") == file_record.content_hash:
        return cached["summary"]

    # ------------------------------------------------------------------
    # 2. Read file content
    # ------------------------------------------------------------------
    file_path = os.path.join(file_record.repo_root, file_record.relative_path)
    with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()

    # ------------------------------------------------------------------
    # 3. Cap at ~50K tokens
    # ------------------------------------------------------------------
    if len(content) > _CONTENT_CHAR_LIMIT:
        content = content[:_CONTENT_CHAR_LIMIT]

    # ------------------------------------------------------------------
    # 4. Language detection
    # ------------------------------------------------------------------
    language = _language_for_extension(file_record.extension)

    # ------------------------------------------------------------------
    # 5. Build prompt
    # ------------------------------------------------------------------
    prompt = file_summary_prompt(file_record.relative_path, content, language)

    # ------------------------------------------------------------------
    # 6. Call AI
    # ------------------------------------------------------------------
    result = client.complete(prompt)

    # ------------------------------------------------------------------
    # 7. Store result
    # ------------------------------------------------------------------
    upsert_summary(
        conn,
        repo_id,
        "file",
        file_record.relative_path,
        result.text,
        content_hash=file_record.content_hash,
        model=client.model,
        prompt_tokens=result.input_tokens,
        completion_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_creation_tokens=result.cache_creation_tokens,
    )

    # ------------------------------------------------------------------
    # 8. Return
    # ------------------------------------------------------------------
    return result.text
