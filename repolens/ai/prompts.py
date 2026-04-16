"""Prompt templates for repolens AI operations.

Each builder returns a ``(system, user)`` tuple.  The ``system`` block
contains the task-shaped instructions (stable across calls within a scope,
a prime prompt-cache candidate); the ``user`` block carries the per-call
payload (file content, summary block, task description, …).

Pure functions — no I/O, no API calls.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# System instruction blocks — identical across calls of the same scope, so
# these are the candidates for ``cache_control`` in RepolensClient.complete().
# ---------------------------------------------------------------------------

_FILE_SUMMARY_SYSTEM = (
    "You are analyzing source code. Summarize each file in 2-4 sentences "
    "covering:\n"
    "- What the file does\n"
    "- Key functions, classes, or exports it defines\n"
    "- Any notable dependencies or side effects\n"
    "Respond with the summary only — no preamble, no repetition of the "
    "prompt, no code fences."
)

_DIR_SUMMARY_SYSTEM = (
    "Summarize the purpose of a directory given the file summaries within "
    "it. 2-3 sentences maximum. Be specific about what the directory owns. "
    "Respond with the summary only."
)

_REPO_SUMMARY_SYSTEM = (
    "Write a concise 4-6 sentence overview of a codebase given its "
    "directory summaries. Cover: what it does, key architectural "
    "components, primary language/stack, and intended users. Respond with "
    "the summary only."
)

_TASK_EXECUTION_SYSTEM = (
    "You are analyzing a software repository. Use the provided context to "
    "answer the task.\n"
    "Be specific, cite file paths when referencing code, and stay within "
    "the context given.\n"
    "If the context is insufficient, say so explicitly rather than "
    "guessing."
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def file_summary_prompt(
    path: str, content: str, language: str = ""
) -> tuple[str, str]:
    """Return ``(system, user)`` for a per-file summary call.

    Args:
        path: Relative path to the file within the repository.
        content: Full text content of the file.
        language: Programming language (e.g. 'Python', 'TypeScript'). Optional.
    """
    user = (
        f"File: {path}\n"
        f"Language: {language}\n"
        "\n"
        f"{content}"
    )
    return _FILE_SUMMARY_SYSTEM, user


def dir_summary_prompt(
    dir_path: str, file_summaries_block: str
) -> tuple[str, str]:
    """Return ``(system, user)`` for a directory-level summary call.

    Args:
        dir_path: Directory path relative to the repo root (trailing slash
            added automatically).
        file_summaries_block: Pre-formatted block of file summaries for
            files within this directory.
    """
    user = (
        f"Directory: {dir_path}/\n"
        "\n"
        f"{file_summaries_block}"
    )
    return _DIR_SUMMARY_SYSTEM, user


def repo_summary_prompt(dir_summaries_block: str) -> tuple[str, str]:
    """Return ``(system, user)`` for a repository-level summary call.

    Args:
        dir_summaries_block: Pre-formatted block of directory summaries
            covering the whole repository.
    """
    return _REPO_SUMMARY_SYSTEM, dir_summaries_block


def task_execution_prompt(
    context_bundle: str, task_description: str
) -> tuple[str, str]:
    """Return ``(system, user)`` for a user task against a context bundle.

    The stable context bundle goes in the ``system`` block so it can be
    prompt-cached across multiple tasks run against the same repo.  Only
    the task description varies between calls and lands in the ``user``
    block.

    Args:
        context_bundle: Pre-built context string (file/dir/repo summaries,
            etc.) describing the repository.
        task_description: The user's question or task to execute against
            the context.
    """
    system = (
        f"{_TASK_EXECUTION_SYSTEM}\n"
        "\n"
        "=== REPOSITORY CONTEXT ===\n"
        "\n"
        f"{context_bundle}"
    )
    user = f"=== TASK ===\n\n{task_description}"
    return system, user
