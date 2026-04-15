"""Task executor: wires context packager, AI client, and DB run logging together."""

import sqlite3

from repolens import config
from repolens.ai.client import RepolensClient
from repolens.ai.prompts import task_execution_prompt
from repolens.context.packager import build_context
from repolens.context.token_counter import estimate_cost
from repolens.db.repository import create_run, update_run


def execute_task(
    conn: sqlite3.Connection,
    repo_id: int,
    task_type: str,
    task_description: str,
    token_budget: int = 32000,
    model: str = None,
) -> dict:
    """Execute a task against a repo, logging the full run lifecycle to the DB.

    Steps:
    1. Create a 'running' run row in the DB.
    2. Build a token-budgeted context bundle for the repo.
    3. Construct the prompt and call the AI client.
    4. Update the run to 'done' with result, token counts, and cost.
    5. On any exception, update the run to 'failed' with the error message, then re-raise.

    Args:
        conn:             Open SQLite connection with initialised schema.
        repo_id:          Primary key of the repo to run the task against.
        task_type:        Task category e.g. 'ask', 'review', 'analyze'.
        task_description: Free-text description of the task.
        token_budget:     Soft token ceiling for context assembly. Default 32000.
        model:            Model override. Falls back to config.REPOLENS_MODEL.

    Returns:
        dict with keys: run_id (int), result (str), prompt_tokens (int),
        completion_tokens (int).

    Raises:
        Re-raises any exception from context building or the AI client after
        recording the failure in the DB.
    """
    resolved_model = model if model is not None else config.REPOLENS_MODEL

    run_id = create_run(conn, repo_id, task_type, task_description, resolved_model)

    try:
        bundle = build_context(conn, repo_id, task_type, token_budget)
        prompt = task_execution_prompt(bundle.content, task_description)

        client = RepolensClient()
        text, prompt_tokens, completion_tokens = client.complete(
            prompt, model=resolved_model
        )

        cost = estimate_cost(prompt_tokens, completion_tokens, resolved_model)
        update_run(
            conn,
            run_id,
            status="done",
            result=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )

    except Exception as exc:
        update_run(conn, run_id, status="failed", error_message=str(exc))
        raise

    return {
        "run_id": run_id,
        "result": text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
