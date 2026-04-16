"""Directory summarizer with caching.

Public API
----------
summarize_directory(conn, repo_id, dir_path, file_summaries, client) -> str
    Return a summary for the given directory, using the DB cache when one
    exists, otherwise calling the AI client and storing the result.
"""

from __future__ import annotations

import sqlite3

from repolens.ai.prompts import dir_summary_prompt
from repolens.db.repository import get_summary, upsert_summary


def summarize_directory(
    conn: sqlite3.Connection,
    repo_id: int,
    dir_path: str,
    file_summaries: dict[str, str],
    client,
) -> str:
    """Return an AI-generated summary for *dir_path*, using the DB cache.

    Cache hit: if a summary exists for (repo_id, 'directory', dir_path),
    the cached text is returned without calling the AI.

    Cache miss: builds a block of file summaries, calls client.complete(),
    stores the result, and returns the summary text.

    Args:
        conn:           Open SQLite connection.
        repo_id:        Foreign key to the repos table.
        dir_path:       Directory path relative to the repo root (e.g.
                        'repolens/summarization').
        file_summaries: Mapping of relative file path -> summary text for
                        files in this directory. Used to build the prompt.
        client:         A RepolensClient (or compatible mock). Must expose
                        .complete(prompt) -> CompletionResult and .model.

    Returns:
        The summary text (2-3 sentences from the AI, or the cached copy).
    """
    # ------------------------------------------------------------------
    # 1. Cache check
    # ------------------------------------------------------------------
    cached = get_summary(conn, repo_id, "directory", dir_path)
    if cached is not None:
        return cached["summary"]

    # ------------------------------------------------------------------
    # 2. Build prompt
    # ------------------------------------------------------------------
    file_summaries_block = "\n\n".join(
        f"{path}:\n{summary}" for path, summary in sorted(file_summaries.items())
    )
    prompt = dir_summary_prompt(dir_path, file_summaries_block)

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
        "directory",
        dir_path,
        result.text,
        model=client.model,
        prompt_tokens=result.input_tokens,
        completion_tokens=result.output_tokens,
    )

    # ------------------------------------------------------------------
    # 5. Return
    # ------------------------------------------------------------------
    return result.text
