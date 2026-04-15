#!/usr/bin/env bash
# hooks/task_completed_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# TaskCompleted Hook — fires when any agent tries to mark a task as completed.
# Runs the task's validation_commands before allowing completion.
#
# Exit behavior:
#   exit 0   → allow task completion
#   exit 2   → block completion, stderr is fed back to the model as feedback
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

INPUT=$(cat)

# Debug: log raw payload so we can confirm field names on first run
# Remove once TaskCompleted payload schema is confirmed
echo "$INPUT" >> /tmp/rr_tc_debug.log

# Extract task_id from hook payload
# NOTE: verify field name against /tmp/rr_tc_debug.log after first run
# Claude Code may use 'task_id', 'taskId', 'title', or 'content'
TASK_ID=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    # Try common field names in priority order
    print(d.get('task_id', '') or d.get('taskId', '') or '')
except:
    print('')
" 2>/dev/null || echo "")

if [ -z "$TASK_ID" ]; then
    # No task_id — allow through (not a managed task)
    exit 0
fi

# Run validation via Python controller
python3 "$PROJECT_ROOT/roadrunner.py" validate "$TASK_ID"
RESULT=$?

if [ $RESULT -ne 0 ]; then
    echo "Validation failed for $TASK_ID. Fix the issues above before marking complete." >&2
    exit 2
fi

exit 0
