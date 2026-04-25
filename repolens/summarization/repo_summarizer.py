"""Repository summarizer with caching.

Public API
----------
summarize_repo(conn, repo_id, dir_summaries, client) -> str
    Return a top-level summary of the full repository, using the DB cache
    when one exists, otherwise calling the AI client and storing the result.
"""

from __future__ import annotations

import sqlite3

from repolens.ai.prompts import repo_summary_prompt
from repolens.db.repository import get_summary, upsert_summary

# Canonical target_path for the repo-level summary row.
_REPO_TARGET_PATH = ""


def summarize_repo(
    conn: sqlite3.Connection,
    repo_id: int,
    dir_summaries: dict[str, str],
    client,
) -> str:
    """Return an AI-generated repository overview, using the DB cache.

    Cache hit: if a summary exists for (repo_id, 'repo', ''), the cached
    text is returned without calling the AI.

    Cache miss: builds a block of directory summaries, calls
    client.complete(), stores the result, and returns the summary text.

    Args:
        conn:          Open SQLite connection.
        repo_id:       Foreign key to the repos table.
        dir_summaries: Mapping of directory path -> summary text covering
                       the whole repository. Used to build the prompt.
        client:        A RepolensClient (or compatible mock). Must expose
                       .complete(prompt) -> CompletionResult and .model.

    Returns:
        The summary text (4-6 sentences from the AI, or the cached copy).
    """
    # ------------------------------------------------------------------
    # 1. Cache check
    # ------------------------------------------------------------------
    cached = get_summary(conn, repo_id, "repo", _REPO_TARGET_PATH)
    if cached is not None:
        return cached["summary"]

    # ------------------------------------------------------------------
    # 2. Build prompt
    # ------------------------------------------------------------------
    dir_summaries_block = "\n\n".join(
        f"{path}/:\n{summary}" for path, summary in sorted(dir_summaries.items())
    )
    prompt = repo_summary_prompt(dir_summaries_block)

    # ------------------------------------------------------------------
    # 3. Call AI
    # ------------------------------------------------------------------
    result = client.complete(prompt)

    # ------------------------------------------------------------------
    # 4. Store result
    # ------------------------------------------------------------------
    upsert_summary(
        conn,
        repo_id,
        "repo",
        _REPO_TARGET_PATH,
        result.text,
        model=client.model,
        prompt_tokens=result.input_tokens,
        completion_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_creation_tokens=result.cache_creation_tokens,
    )

    # ------------------------------------------------------------------
    # 5. Return
    # ------------------------------------------------------------------
    return result.text
