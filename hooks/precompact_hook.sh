#!/usr/bin/env bash
# hooks/precompact_hook.sh
# ─────────────────────────────────────────────────────────────────────────────
# PreCompact Hook — fires before conversation compaction.
# Writes current roadmap state to disk so Claude can resume after context reset.
# stdout is injected into the new context window as additionalContext.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Write snapshot and emit additionalContext JSON for Claude
python3 "$PROJECT_ROOT/roadrunner.py" snapshot
