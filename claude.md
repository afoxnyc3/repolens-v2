# CLAUDE.md — Roadmap Loop Agent Brief

## Operating Model

You are executing a deterministic roadmap. Python owns control. You own implementation.
**One task per cycle. No side quests. No skipping ahead.**

---

## Your Job Each Cycle

1. Run `python3 roadrunner.py next` to see the current task
2. Run `python3 roadrunner.py start TASK-XXX` before touching any files
3. Implement the task — stay within its scope
4. Run `python3 roadrunner.py validate TASK-XXX` to check your work
5. Fix any failures — validation commands are the source of truth, not your assessment
6. Run `python3 roadrunner.py complete TASK-XXX --notes "what you did"` to close the task
7. Run `python3 roadrunner.py reset TASK-XXX --summary "one line"` to write the boundary marker

**The Stop hook will determine what comes next. Do not attempt to decide task order yourself.**

---

## Completion Signal

When ALL tasks are `done` and there is no remaining eligible work:

Output this exact string on its own line:

```
ROADMAP_COMPLETE
```

This halts the loop. Do not output it unless the roadmap is genuinely finished.

---

## Blocked Tasks

If a task cannot be completed due to an unresolvable dependency, external blocker, or repeated validation failure (3+ attempts):

```bash
python3 roadrunner.py block TASK-XXX --notes "reason for block"
```

Document what is blocking. Do not keep retrying indefinitely.

---

## Validation Is the Gate

A task is done when `python3 roadrunner.py validate TASK-XXX` exits 0.
Not when you think it looks right. Not when the code exists. When validation passes.

---

## Context Hygiene

- Work on exactly one task per cycle
- Do not reference prior task details unless directly relevant to current task
- After each `complete`, treat the prior task as closed
- The `.context_snapshot.json` and `.roadmap_state.json` are your memory

---

## File Scope

Only touch files listed in the current task's `files_expected` and `documentation_targets`.
If you need to modify something outside scope, note it in the task's `--notes` and continue.

---

## Commands Reference

```bash
python3 roadrunner.py status                        # show all task statuses
python3 roadrunner.py next                          # show next eligible task
python3 roadrunner.py start TASK-XXX               # begin a task
python3 roadrunner.py validate TASK-XXX            # run validation only
python3 roadrunner.py complete TASK-XXX --notes "" # complete with validation
python3 roadrunner.py block TASK-XXX --notes ""    # mark blocked
python3 roadrunner.py reset TASK-XXX --summary ""  # write boundary marker
python3 roadrunner.py health                        # system health check
```

---

## What the Stop Hook Does

After every response, the Stop hook checks:
- Is `stop_hook_active` true? → allow stop (prevents infinite loop)
- Did you output `ROADMAP_COMPLETE`? → allow stop
- Are there eligible tasks? → inject the next task brief and block stop
- Are all tasks done? → prompt you to output `ROADMAP_COMPLETE`
- Iteration limit reached? → hard stop with message

You do not need to manage this. The hook manages it. Just do the work.
