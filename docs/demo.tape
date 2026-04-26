# Repolens v2 — README demo
#
# Renders an end-to-end pipeline run on a real repo using only free-tier
# commands (ingest, classify, status, dry-run cost preview).
#
# Regenerate:
#   source .venv/bin/activate
#   vhs docs/demo.tape

Output docs/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1200
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set PlaybackSpeed 1.0

# --- silent setup (side DB so we don't touch ~/.repolens) -----------------
Hide
Type "export REPOLENS_DB=/tmp/repolens-demo.db"
Enter
Type "rm -f /tmp/repolens-demo.db /tmp/repolens-demo.db-shm /tmp/repolens-demo.db-wal"
Enter
Type "source .venv/bin/activate"
Enter
Type "export PS1='$ '"
Enter
Type "clear"
Enter
Sleep 500ms
Show

# --- 1. Quick CLI overview ------------------------------------------------
Type "repolens --help"
Enter
Sleep 2500ms

Hide
Type "clear"
Enter
Sleep 200ms
Show

# --- 2. Ingest a real repo ------------------------------------------------
Type "# Scan a local repo into a single SQLite file"
Enter
Type "repolens ingest ."
Enter
Sleep 2000ms

# --- 3. Classify + score every file --------------------------------------
Type "# Rules-based classification + importance scoring (no AI call)"
Enter
Type "repolens classify 1"
Enter
Sleep 3000ms

# --- 4. Inspect repo state -----------------------------------------------
Type "repolens status 1"
Enter
Sleep 3000ms

Hide
Type "clear"
Enter
Sleep 200ms
Show

# --- 5. Cost-visible AI: dry-run preview ---------------------------------
Type "# Preview tokens + USD before any API call"
Enter
Type "repolens run 1 --task analyze --description 'what does this repo do?' --budget 8000 --dry-run"
Enter
Sleep 2500ms

Type "# Same command without --dry-run would log every token + cost to runs"
Enter
Sleep 2500ms

# --- end ------------------------------------------------------------------
Sleep 1500ms
