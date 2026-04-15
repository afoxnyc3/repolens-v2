"""Prompt templates for repolens AI operations.

Pure functions — no I/O, no API calls. Each returns a formatted prompt string
ready to pass to RepolensClient.complete().
"""


def file_summary_prompt(path: str, content: str, language: str = "") -> str:
    """Return a prompt requesting a 2-4 sentence summary of a source file.

    Args:
        path: Relative path to the file within the repository.
        content: Full text content of the file.
        language: Programming language (e.g. 'Python', 'TypeScript'). Optional.
    """
    return (
        "You are analyzing source code. Summarize this file in 2-4 sentences covering:\n"
        "- What the file does\n"
        "- Key functions, classes, or exports it defines\n"
        "- Any notable dependencies or side effects\n"
        "\n"
        f"File: {path}\n"
        f"Language: {language}\n"
        "\n"
        f"{content}"
    )


def dir_summary_prompt(dir_path: str, file_summaries_block: str) -> str:
    """Return a prompt requesting a 2-3 sentence directory summary.

    Args:
        dir_path: Path to the directory (trailing slash added automatically).
        file_summaries_block: Pre-formatted block of file summaries for files
            within this directory.
    """
    return (
        "Summarize the purpose of this directory given the following file summaries.\n"
        "2-3 sentences maximum. Be specific about what the directory owns.\n"
        "\n"
        f"Directory: {dir_path}/\n"
        "\n"
        f"{file_summaries_block}"
    )


def repo_summary_prompt(dir_summaries_block: str) -> str:
    """Return a prompt requesting a 4-6 sentence repository overview.

    Args:
        dir_summaries_block: Pre-formatted block of directory summaries
            covering the whole repository.
    """
    return (
        "Write a concise 4-6 sentence overview of this codebase.\n"
        "Cover: what it does, key architectural components, primary language/stack,"
        " and intended users.\n"
        "\n"
        f"{dir_summaries_block}"
    )


def task_execution_prompt(context_bundle: str, task_description: str) -> str:
    """Return a prompt for running a user task against a repository context bundle.

    Args:
        context_bundle: Pre-built context string (file/dir/repo summaries, etc.)
            describing the repository.
        task_description: The user's question or task to execute against the context.
    """
    return (
        "You are analyzing a software repository. Use the provided context to answer"
        " the task.\n"
        "Be specific, cite file paths when referencing code, and stay within the"
        " context given.\n"
        "If the context is insufficient, say so explicitly rather than guessing.\n"
        "\n"
        "=== REPOSITORY CONTEXT ===\n"
        "\n"
        f"{context_bundle}\n"
        "\n"
        "=== TASK ===\n"
        "\n"
        f"{task_description}"
    )
