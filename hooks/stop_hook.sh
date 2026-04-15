#!/usr/bin/env bash
# hooks/stop_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# Stop Hook — fires when Claude Code agent finishes responding.
# Determines whether Claude is allowed to stop or must continue working.
#
# Exit behavior:
#   exit 0          → allow Claude to stop
#   exit 2          → force Claude to continue (legacy method)
#   stdout JSON     → structured control (preferred)
#     {"decision": "block", "reason": "..."}  → continue with reason
#     {"continue": false, "stopReason": "..."} → hard stop with message
#
# CRITICAL: Always check stop_hook_active to prevent infinite loops.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MAX_ITERATIONS="${ROADMAP_MAX_ITERATIONS:-50}"

# Read stdin from Claude Code
INPUT=$(cat)

# ── Infinite loop guard ───────────────────────────────────────────────────────
# If stop_hook_active is true, a previous hook invocation already ran.
# Allow Claude to stop to break the loop.
HOOK_ACTIVE=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('true' if d.get('stop_hook_active') else 'false')
except:
    print('false')
" 2>/dev/null || echo "false")

if [ "$HOOK_ACTIVE" = "true" ]; then
    exit 0
fi

# ── Delegate to Python controller ─────────────────────────────────────────────
# Pass stdin through to check-stop command which owns all logic.
echo "$INPUT" | python3 "$PROJECT_ROOT/roadrunner.py" check-stop \
    --max-iterations "$MAX_ITERATIONS"
