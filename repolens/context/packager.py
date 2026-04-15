"""Context bundle assembler for repolens.

Builds a token-budgeted context string from repository summaries and file
content, ready to pass to an LLM as a prompt prefix.

Public API
----------
build_context(conn, repo_id, task_type, token_budget=32000) -> ContextBundle
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from repolens.context.token_counter import count_tokens
from repolens.db.repository import (
    get_repo,
    get_summary,
    list_files,
    list_summaries_by_scope,
)

# ---------------------------------------------------------------------------
# Task instructions
# ---------------------------------------------------------------------------

_TASK_INSTRUCTIONS: dict[str, str] = {
    "analyze": (
        "## Task Instructions\n\n"
        "Analyze the repository above. Identify the main purpose, key components, "
        "architectural patterns, and any notable design decisions. "
        "Highlight areas of interest, technical debt, or improvement opportunities."
    ),
    "summarize": (
        "## Task Instructions\n\n"
        "Produce a concise summary of this repository. Cover: what it does, "
        "the primary technologies used, the top-level structure, and "
        "who the intended audience or users are."
    ),
    "refactor-prep": (
        "## Task Instructions\n\n"
        "Prepare a refactoring plan for this repository. Identify coupling, "
        "duplication, unclear naming, missing abstractions, and any code "
        "that is harder to change than it should be. "
        "Propose concrete next steps in priority order."
    ),
}

_DEFAULT_INSTRUCTIONS = (
    "## Task Instructions\n\n"
    "Review the repository context above and respond to the task."
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ContextBundle:
    """Assembled context ready for LLM consumption.

    Attributes:
        content:     The full assembled context string.
        file_paths:  Repo-relative paths of files included at full content
                     (not summary). Ordered by importance_score DESC, matching
                     the greedy inclusion order.
        token_count: Token count of *content* as returned by count_tokens().
    """

    content: str
    file_paths: list[str] = field(default_factory=list)
    token_count: int = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_context(
    conn: sqlite3.Connection,
    repo_id: int,
    task_type: str,
    token_budget: int = 32000,
) -> ContextBundle:
    """Assemble a token-budgeted context bundle for a repo and task.

    Assembly order:
    1. Repo-level summary (scope='repo').
    2. All directory summaries (scope='directory').
    3. Files in importance_score DESC order, included at full content while
       the budget allows; falling back to the stored file summary otherwise.
    4. Task-specific instructions appended at the end.

    The final token_count is guaranteed to be <= token_budget * 1.05 as long
    as any single preamble or instruction section is smaller than the budget.
    Files whose content or summary would push usage over the file budget are
    silently skipped.

    Args:
        conn:         Open SQLite connection (schema must be initialised).
        repo_id:      Primary key of the repo to build context for.
        task_type:    One of 'analyze', 'summarize', 'refactor-prep'.
                      Unknown values use a generic instruction block.
        token_budget: Soft token ceiling. Default 32 000.

    Returns:
        ContextBundle with assembled content, full-content file_paths list,
        and the final token_count.

    Raises:
        ValueError: if repo_id is not found in the repos table.
    """
    repo = get_repo(conn, repo_id)
    if repo is None:
        raise ValueError(f"Repo {repo_id} not found")

    repo_root = Path(repo["path"])
    parts: list[str] = []

    # ------------------------------------------------------------------
    # 1. Repo summary
    # ------------------------------------------------------------------
    repo_summary_row = get_summary(conn, repo_id, "repo", "")
    if repo_summary_row:
        parts.append(f"# Repository Summary\n\n{repo_summary_row['summary']}")

    # ------------------------------------------------------------------
    # 2. Directory summaries
    # ------------------------------------------------------------------
    dir_rows = list_summaries_by_scope(conn, repo_id, scope="directory")
    if dir_rows:
        dir_blocks = [
            f"### {row['target_path']}\n{row['summary']}" for row in dir_rows
        ]
        parts.append("# Directory Summaries\n\n" + "\n\n".join(dir_blocks))

    # ------------------------------------------------------------------
    # 3. Reserve tokens for task instructions
    # ------------------------------------------------------------------
    task_instructions = _TASK_INSTRUCTIONS.get(task_type, _DEFAULT_INSTRUCTIONS)
    instructions_tokens = count_tokens(task_instructions)

    # ------------------------------------------------------------------
    # Measure preamble
    # ------------------------------------------------------------------
    preamble = "\n\n".join(parts)
    preamble_tokens = count_tokens(preamble) if preamble else 0

    # Token budget available for file sections (full content + summaries)
    file_budget = max(0, token_budget - preamble_tokens - instructions_tokens)

    # ------------------------------------------------------------------
    # 4. Greedy file inclusion
    # ------------------------------------------------------------------
    files = list_files(conn, repo_id, order_by="importance_score DESC")
    file_parts: list[str] = []
    full_content_paths: list[str] = []
    used_tokens = 0

    for f in files:
        file_disk_path = repo_root / f["path"]
        disk_content: str | None = None
        try:
            disk_content = file_disk_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            disk_content = None

        if disk_content is not None:
            content_tokens = count_tokens(disk_content)
            if used_tokens + content_tokens <= file_budget:
                # Full content fits — include it
                ext = (f.get("extension") or Path(f["path"]).suffix.lstrip(".")) or ""
                file_parts.append(
                    f"### {f['path']}\n\n```{ext}\n{disk_content}\n```"
                )
                full_content_paths.append(f["path"])
                used_tokens += content_tokens
                continue
            # Falls through to summary attempt below

        # ------------------------------------------------------------------
        # 5. Summary fallback
        # ------------------------------------------------------------------
        summary_row = get_summary(conn, repo_id, "file", f["path"])
        if summary_row:
            summary_tokens = count_tokens(summary_row["summary"])
            if used_tokens + summary_tokens <= file_budget:
                file_parts.append(
                    f"### {f['path']} (summary)\n\n{summary_row['summary']}"
                )
                used_tokens += summary_tokens

    # ------------------------------------------------------------------
    # 6. Assemble and measure
    # ------------------------------------------------------------------
    all_parts: list[str] = []
    if preamble:
        all_parts.append(preamble)
    if file_parts:
        all_parts.append("# Files\n\n" + "\n\n".join(file_parts))
    all_parts.append(task_instructions)

    content = "\n\n".join(all_parts)
    token_count = count_tokens(content)

    return ContextBundle(
        content=content,
        file_paths=full_content_paths,
        token_count=token_count,
    )
