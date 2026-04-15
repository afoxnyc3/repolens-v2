"""Context bundle formatters for repolens.

Pure functions -- no DB or API calls.

Public API
----------
export_markdown(bundle, *, task_type=None, repo_id=None) -> str
export_json(bundle, *, task_type=None, repo_id=None) -> str
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from repolens.context.packager import ContextBundle


def export_markdown(
    bundle: ContextBundle,
    *,
    task_type: str | None = None,
    repo_id: int | None = None,
) -> str:
    """Format a ContextBundle as a Markdown document.

    Returns a non-empty string with a YAML front-matter metadata header
    followed by the full bundle content.

    Args:
        bundle:    The assembled context bundle.
        task_type: Optional task type label for the metadata header.
        repo_id:   Optional repo integer ID for the metadata header.

    Returns:
        Markdown string with metadata header and bundle content.
    """
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    file_count = len(bundle.file_paths)

    header_lines = ["---"]
    if repo_id is not None:
        header_lines.append(f"repo_id: {repo_id}")
    if task_type is not None:
        header_lines.append(f"task_type: {task_type}")
    header_lines.append(f"token_count: {bundle.token_count}")
    header_lines.append(f"file_count: {file_count}")
    header_lines.append(f"generated: {generated}")
    header_lines.append("---")

    header = "\n".join(header_lines)
    return f"{header}\n\n{bundle.content}"


def export_json(
    bundle: ContextBundle,
    *,
    task_type: str | None = None,
    repo_id: int | None = None,
) -> str:
    """Serialize a ContextBundle to a JSON string.

    Args:
        bundle:    The assembled context bundle.
        task_type: Optional task type label included in the output when given.
        repo_id:   Optional repo ID included in the output when given.

    Returns:
        JSON string. Always includes 'content', 'file_paths', 'token_count'.
        Includes 'task_type' and 'repo_id' when provided.
    """
    data: dict = {
        "content": bundle.content,
        "file_paths": bundle.file_paths,
        "token_count": bundle.token_count,
    }
    if task_type is not None:
        data["task_type"] = task_type
    if repo_id is not None:
        data["repo_id"] = repo_id

    return json.dumps(data, ensure_ascii=False, indent=2)
