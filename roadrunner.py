#!/usr/bin/env python3
"""
Roadmap Loop Controller
-----------------------
Python owns: task selection, dependency resolution, validation, logging, state.
Claude Code owns: implementation inside one task boundary.
Hooks own: stop enforcement, completion gating, context snapshots.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent
TASKS_FILE = ROOT / "tasks" / "tasks.yaml"
LOGS_DIR = ROOT / "logs"
CHANGELOG = LOGS_DIR / "CHANGELOG.md"
STATE_FILE = ROOT / ".roadmap_state.json"
LOGS_DIR.mkdir(exist_ok=True)

# ── YAML helpers ─────────────────────────────────────────────────────────────


def load_tasks() -> list[dict]:
    with open(TASKS_FILE) as f:
        data = yaml.safe_load(f)
    return data.get("tasks", [])


def save_tasks(tasks: list[dict]) -> None:
    with open(TASKS_FILE) as f:
        data = yaml.safe_load(f)
    data["tasks"] = tasks
    with open(TASKS_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_task(tasks: list[dict], task_id: str) -> dict | None:
    return next((t for t in tasks if t["id"] == task_id), None)


# ── Eligibility ───────────────────────────────────────────────────────────────


def is_eligible(task: dict, tasks: list[dict]) -> bool:
    if task.get("status") != "todo":
        return False
    for dep_id in task.get("depends_on", []):
        dep = get_task(tasks, dep_id)
        if not dep or dep.get("status") != "done":
            return False
    return True


def next_eligible_task(tasks: list[dict]) -> dict | None:
    return next((t for t in tasks if is_eligible(t, tasks)), None)


# ── Validation ────────────────────────────────────────────────────────────────


def run_validation(task: dict) -> tuple[bool, list[dict]]:
    """Run all validation_commands for a task. Returns (passed, results)."""
    commands = task.get("validation_commands", [])
    if not commands:
        return True, []

    results = []
    all_passed = True

    for cmd in commands:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        passed = result.returncode == 0
        if not passed:
            all_passed = False
        results.append(
            {
                "command": cmd,
                "passed": passed,
                "returncode": result.returncode,
                "stdout": result.stdout.strip()[:500],
                "stderr": result.stderr.strip()[:500],
            }
        )

    return all_passed, results


# ── State management ──────────────────────────────────────────────────────────


def write_state(current_task_id: str | None, iteration: int) -> None:
    state = {
        "current_task_id": current_task_id,
        "iteration": iteration,
        "updated_at": _now(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"current_task_id": None, "iteration": 0}
    return json.loads(STATE_FILE.read_text())


# ── Logging ───────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_changelog(task_id: str, status: str, notes: str = "") -> None:
    entry = f"## {_now()} | {task_id} → {status}\n{notes}\n\n"
    with open(CHANGELOG, "a") as f:
        f.write(entry)


def write_work_log(task: dict, validation_results: list[dict], notes: str = "") -> None:
    log_path = LOGS_DIR / f"{task['id']}.md"
    passed_count = sum(1 for r in validation_results if r["passed"])
    total = len(validation_results)

    lines = [
        f"# Work Log: {task['id']} — {task.get('title', '')}",
        f"**Completed:** {_now()}",
        f"**Status:** {task.get('status')}",
        "",
        f"## Goal\n{task.get('goal', 'N/A')}",
        "",
        "## Acceptance Criteria",
    ]
    for ac in task.get("acceptance_criteria", []):
        lines.append(f"- {ac}")

    lines += [
        "",
        f"## Validation ({passed_count}/{total} passed)",
    ]
    for r in validation_results:
        icon = "✅" if r["passed"] else "❌"
        lines.append(f"\n### {icon} `{r['command']}`")
        if r["stdout"]:
            lines.append(f"```\n{r['stdout']}\n```")
        if r["stderr"] and not r["passed"]:
            lines.append(f"**stderr:**\n```\n{r['stderr']}\n```")

    if notes:
        lines += ["", f"## Notes\n{notes}"]

    log_path.write_text("\n".join(lines))


def write_reset_marker(task_id: str, summary: str) -> None:
    marker = ROOT / f".reset_{task_id}"
    marker.write_text(
        json.dumps({"task_id": task_id, "summary": summary, "at": _now()}, indent=2)
    )


def write_context_snapshot() -> None:
    """Called by PreCompact hook — persist enough state for cold resume."""
    tasks = load_tasks()
    state = read_state()
    next_task = next_eligible_task(tasks)

    snapshot = {
        "snapshot_at": _now(),
        "current_task": state.get("current_task_id"),
        "iteration": state.get("iteration", 0),
        "next_eligible": next_task["id"] if next_task else None,
        "status_summary": {t["id"]: t["status"] for t in tasks},
    }
    (ROOT / ".context_snapshot.json").write_text(json.dumps(snapshot, indent=2))
    print(
        json.dumps(
            {
                "additionalContext": f"Roadmap state snapshot written. Next task: {snapshot['next_eligible']}. Iteration: {snapshot['iteration']}"
            }
        )
    )


# ── CLI commands ──────────────────────────────────────────────────────────────


def cmd_status(args) -> None:
    tasks = load_tasks()
    print(f"\n{'ID':<14} {'STATUS':<12} {'TITLE'}")
    print("─" * 60)
    for t in tasks:
        marker = "→" if t.get("status") == "in_progress" else " "
        print(
            f"{marker} {t['id']:<13} {t.get('status', 'todo'):<12} {t.get('title', '')}"
        )
    next_t = next_eligible_task(tasks)
    print(f"\nNext eligible: {next_t['id'] if next_t else 'None'}")


def cmd_next(args) -> None:
    tasks = load_tasks()
    task = next_eligible_task(tasks)
    if not task:
        print("No eligible tasks.")
        return
    print(f"\nNext: {task['id']} — {task.get('title')}")
    print(f"Goal: {task.get('goal', 'N/A')}")
    print("Acceptance criteria:")
    for ac in task.get("acceptance_criteria", []):
        print(f"  - {ac}")


def cmd_start(args) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)
    if not is_eligible(task, tasks):
        print(
            f"Task {args.task_id} is not eligible (status={task.get('status')}, check deps)."
        )
        sys.exit(1)

    state = read_state()
    task["status"] = "in_progress"
    save_tasks(tasks)
    write_state(args.task_id, state.get("iteration", 0) + 1)
    append_changelog(args.task_id, "in_progress")
    print(f"Started {args.task_id}. Iteration {state.get('iteration', 0) + 1}.")


def cmd_validate(args) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)

    passed, results = run_validation(task)
    for r in results:
        icon = "✅" if r["passed"] else "❌"
        print(f"{icon} {r['command']}")
        if not r["passed"] and r["stderr"]:
            print(f"   {r['stderr'][:200]}")

    sys.exit(0 if passed else 1)


def cmd_complete(args) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)

    passed, results = run_validation(task)
    if not passed:
        print(f"Validation failed. Task {args.task_id} NOT marked done.")
        write_work_log(task, results, notes=args.notes or "")
        sys.exit(1)

    task["status"] = "done"
    save_tasks(tasks)
    write_work_log(task, results, notes=args.notes or "")
    append_changelog(args.task_id, "done", notes=args.notes or "")
    write_reset_marker(args.task_id, summary=args.notes or "Completed.")
    print(f"✅ {args.task_id} marked done.")


def cmd_block(args) -> None:
    tasks = load_tasks()
    task = get_task(tasks, args.task_id)
    if not task:
        sys.exit(1)

    task["status"] = "blocked"
    save_tasks(tasks)
    append_changelog(args.task_id, "blocked", notes=args.notes or "")
    write_work_log(task, [], notes=args.notes or "")
    print(f"🚫 {args.task_id} marked blocked.")


def cmd_reset(args) -> None:
    write_reset_marker(args.task_id, summary=args.summary or "")
    write_context_snapshot()
    print(f"Reset marker written for {args.task_id}.")


def cmd_health(args) -> None:
    tasks = load_tasks()
    eligible = [t for t in tasks if is_eligible(t, tasks)]
    done = [t for t in tasks if t.get("status") == "done"]
    blocked = [t for t in tasks if t.get("status") == "blocked"]
    print(
        f"healthy — {len(done)}/{len(tasks)} done, {len(eligible)} eligible, {len(blocked)} blocked"
    )


def cmd_check_stop(args) -> None:
    """
    Called by Stop hook. Outputs JSON to control whether Claude Code halts.
    Reads stop_hook_active from stdin to prevent infinite loops.
    """
    try:
        stdin_data = json.loads(sys.stdin.read())
    except Exception:
        stdin_data = {}

    # Guard: if already looping from hook, allow stop
    if stdin_data.get("stop_hook_active"):
        sys.exit(0)

    state = read_state()
    iteration = state.get("iteration", 0)
    max_iter = int(args.max_iterations) if args.max_iterations else 50

    if iteration >= max_iter:
        print(
            json.dumps(
                {
                    "continue": False,
                    "stopReason": f"Max iterations ({max_iter}) reached. Roadmap loop halted.",
                }
            )
        )
        sys.exit(0)

    tasks = load_tasks()
    last_msg = stdin_data.get("last_assistant_message", "")

    # Completion signal: Claude outputs ROADMAP_COMPLETE
    if "ROADMAP_COMPLETE" in last_msg:
        append_changelog(
            "ALL",
            "complete",
            notes="Roadmap finished — ROADMAP_COMPLETE signal received.",
        )
        sys.exit(0)

    next_task = next_eligible_task(tasks)
    if not next_task:
        blocked = [t["id"] for t in tasks if t.get("status") == "blocked"]
        if blocked:
            msg = f"No eligible tasks. Blocked: {blocked}. Investigate and unblock or output ROADMAP_COMPLETE to halt."
        else:
            msg = "All tasks complete. Output ROADMAP_COMPLETE to signal completion."
        print(json.dumps({"decision": "block", "reason": msg}))
        sys.exit(0)

    brief = _build_task_brief(next_task, iteration, max_iter)
    print(json.dumps({"decision": "block", "reason": brief}))
    sys.exit(0)


def cmd_snapshot(args) -> None:
    write_context_snapshot()


def _build_task_brief(task: dict, iteration: int, max_iter: int) -> str:
    criteria = "\n".join(f"  - {ac}" for ac in task.get("acceptance_criteria", []))
    validation = "\n".join(f"  - {v}" for v in task.get("validation_commands", []))
    files = "\n".join(f"  - {f}" for f in task.get("files_expected", []))
    return (
        f"Continue working. Iteration {iteration + 1}/{max_iter}.\n\n"
        f"CURRENT TASK: {task['id']} — {task.get('title')}\n"
        f"Goal: {task.get('goal', 'N/A')}\n\n"
        f"Acceptance criteria:\n{criteria or '  (none specified)'}\n\n"
        f"Validation commands (must pass before complete):\n{validation or '  (none)'}\n\n"
        f"Expected files:\n{files or '  (none)'}\n\n"
        f"When done: run `python roadrunner.py complete {task['id']} --notes '...'`\n"
        f"To signal full roadmap done: output ROADMAP_COMPLETE on its own line."
    )


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Roadmap Loop Controller")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status")
    sub.add_parser("next")
    sub.add_parser("health")
    sub.add_parser("snapshot")

    p_start = sub.add_parser("start")
    p_start.add_argument("task_id")

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("task_id")

    p_complete = sub.add_parser("complete")
    p_complete.add_argument("task_id")
    p_complete.add_argument("--notes", default="")

    p_block = sub.add_parser("block")
    p_block.add_argument("task_id")
    p_block.add_argument("--notes", default="")

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("task_id")
    p_reset.add_argument("--summary", default="")

    p_stop = sub.add_parser("check-stop")
    p_stop.add_argument("--max-iterations", default="50")

    args = parser.parse_args()

    dispatch = {
        "status": cmd_status,
        "next": cmd_next,
        "start": cmd_start,
        "validate": cmd_validate,
        "complete": cmd_complete,
        "block": cmd_block,
        "reset": cmd_reset,
        "health": cmd_health,
        "check-stop": cmd_check_stop,
        "snapshot": cmd_snapshot,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
