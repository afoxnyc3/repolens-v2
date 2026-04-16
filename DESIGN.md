# Repolens v2 — Design Document

> Last updated: 2026-04-16
> Stack: Python 3.12+, SQLite, FastAPI (thin), Anthropic SDK, Typer CLI

---

## 1. What This Is

Repolens ingests a local git repository, classifies and scores every file, builds token-efficient context bundles, and runs AI tasks against that context. It replaces the pattern of pasting entire codebases into chat windows.

MVP is local-only. No cloud storage. No Redis. No authentication. Everything persists in a single SQLite file. Output is markdown or JSON to stdout or disk.

---

## 2. Module Architecture

```
repolens/
├── cli/           Entry point. Wires together all modules.
├── ingestion/     Scans repo, applies ignore rules, collects file metadata.
├── classification/ Rules-based file type and role classification.
├── scoring/       Importance scoring. Ranks files for context budget allocation.
├── summarization/ AI-powered summaries at file, directory, and repo level.
├── context/       Builds token-budgeted context packages for AI tasks.
├── ai/            Anthropic API wrapper, prompt templates, task executor.
└── db/            SQLite schema + data access layer.
```

### 2.1 Ingestion (`repolens/ingestion/`)

Responsibilities:
- Walk the directory tree starting at the repo root
- Apply `.gitignore` rules (via `gitignore_parser` or equivalent)
- Apply custom ignore patterns (passed in at ingest time or stored per-repo)
- Skip binary files (detect via null bytes in first 8KB)
- Skip files above size threshold (default: 1MB)
- Collect per-file metadata: path, extension, size, mtime, content hash

Key files: `scanner.py`, `filters.py`

The scanner returns a stream of `FileRecord` objects. Metadata is written to the `files` table. Content is not stored in the DB — it is read from disk on demand. This keeps the DB small.

### 2.2 Classification (`repolens/classification/`)

Responsibilities:
- Assign a category to each file (rules-based, no AI)
- Categories: `core`, `test`, `config`, `docs`, `build`, `generated`, `other`

Rules (in priority order):
1. Path pattern: `**/test_*.py`, `**/*_test.py`, `**/tests/**` → `test`
2. Path pattern: `**/__pycache__/**`, `**/dist/**`, `**/build/**`, `**/.git/**` → `generated`
3. Extension: `.md`, `.rst`, `.txt` + path contains `docs/` or `README` → `docs`
4. Filename: `pyproject.toml`, `setup.py`, `Makefile`, `Dockerfile`, `*.yaml`, `*.toml`, `*.json` at root → `config`
5. Extension: `.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, `.rb`, `.swift` → `core` (default for source)
6. Everything else → `other`

Key files: `classifier.py`

### 2.3 Scoring (`repolens/scoring/`)

Responsibilities:
- Compute a numeric importance score (0.0–1.0) for each file
- Score drives context budget allocation (higher-scored files included first)

Scoring inputs:
- Classification weight: `core`=1.0, `config`=0.8, `test`=0.6, `docs`=0.5, `build`=0.3, `generated`=0.0
- Depth penalty: files deeper in the tree score slightly lower (`score *= (1 - 0.05 * depth)`, floor at 0.5 of base)
- Size penalty: files above 20KB are penalized (large files carry less signal per token)
- Recency bonus: files modified in the last 7 days get +0.1 (optional, only if git mtime available)
- Entry point boost: files named `main.py`, `app.py`, `index.py`, `__init__.py` at root depth get +0.2

Score is deterministic given the same repo state. No AI involved in scoring.

Key files: `repolens/scoring/scorer.py`

(Originally drafted inside `classification/classifier.py` and extracted
2026-04-16 to match this section; back-compat re-export retained.)

### 2.4 Summarization (`repolens/summarization/`)

Responsibilities:
- Generate concise natural-language summaries at three scopes: file, directory, repo
- Cache summaries in SQLite (keyed by content hash; only regenerate when source changes)
- Respect a per-run token budget for the summary generation pass itself

Levels:
- **File summary**: given file content, return 2-4 sentence summary of purpose and key exports
- **Directory summary**: given all file summaries in a directory, return 2-3 sentence summary
- **Repo summary**: given all directory summaries, return a 4-6 sentence overview

Summaries are generated bottom-up: files first, then directories, then repo. Each level uses summaries from the level below (not raw content), keeping prompt sizes small.

Key files: `file_summarizer.py`, `dir_summarizer.py`, `repo_summarizer.py`

### 2.5 Context Engine (`repolens/context/`)

Responsibilities:
- Build a context bundle: a curated selection of file content + summaries within a token budget
- Support task-specific context shapes (different tasks need different file selections)
- Export to markdown (for reading/pasting) or JSON (for programmatic use)

Context building algorithm:
1. Sort files by importance score descending
2. Include files greedily until token budget exhausted
3. For files that didn't fit: include their file summary instead of full content
4. Always include repo summary and directory summaries at the top
5. Append a task description section at the end

Token counting: use `tiktoken` (cl100k_base) for accurate counts. Fall back to `len(text) // 4` if tiktoken unavailable.

Task types (predefined context shapes):
- `analyze`: include high-scoring core files, summaries for everything else
- `summarize`: only summaries, no full file content (smallest bundle)
- `refactor-prep`: include the specific target file at full content, plus all files that import it, plus test files

Key files: `packager.py`, `token_counter.py`, `exporter.py`

### 2.6 AI Layer (`repolens/ai/`)

Responsibilities:
- Wrap the Anthropic API (single client, configured from env)
- Own all prompt templates
- Execute AI tasks against context bundles
- Log every run (tokens, cost, result) to SQLite

Model selection: default `claude-opus-4-7`. Configurable via `--model` flag or `REPOLENS_MODEL` env var. Model ID pinning policy: see [ADR-006](docs/decisions/ADR-006-model-ids.md).

Prompt caching: every call uses a structured `(system, user)` prompt. The system block is tagged with `cache_control={"type": "ephemeral"}` when it meets the model-family minimum (1024 tokens for Opus/Sonnet, 2048 for Haiku). Summarizer system blocks are identical across a run so cache hits are the norm after the first call. Task-execution system blocks include the full context bundle, so repeated questions against the same repo within a 5-minute TTL window read from cache at 10% of the input rate. See [ADR-004](docs/decisions/ADR-004-prompt-caching.md).

Key files: `client.py`, `prompts.py`, `executor.py`

### 2.7 Database (`repolens/db/`)

Responsibilities:
- Create and migrate the SQLite schema on first use
- Provide a clean data access interface (no raw SQL outside this module)

Key files: `schema.py`, `repository.py`

---

## 3. Data Model (SQLite Schema)

Single DB file at `~/.repolens/repolens.db` (configurable via `REPOLENS_DB` env var).

```sql
-- Tracked repositories
CREATE TABLE repos (
    id          INTEGER PRIMARY KEY,
    path        TEXT    UNIQUE NOT NULL,  -- absolute path on disk
    name        TEXT    NOT NULL,
    file_count  INTEGER,
    total_size_bytes INTEGER,
    ingested_at INTEGER,
    last_scanned_at INTEGER,
    created_at  INTEGER DEFAULT (unixepoch())
);

-- Per-file metadata and classification (content NOT stored here)
CREATE TABLE files (
    id               INTEGER PRIMARY KEY,
    repo_id          INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    path             TEXT    NOT NULL,   -- relative to repo root
    extension        TEXT,
    size_bytes       INTEGER,
    mtime            INTEGER,            -- unix timestamp
    content_hash     TEXT,               -- sha256 of file content
    classification   TEXT,               -- core|test|config|docs|build|generated|other
    importance_score REAL,
    token_estimate   INTEGER,
    UNIQUE(repo_id, path)
);

-- Cached summaries (file, directory, repo scope)
CREATE TABLE summaries (
    id           INTEGER PRIMARY KEY,
    repo_id      INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    scope        TEXT    NOT NULL,  -- file|directory|repo
    target_path  TEXT    NOT NULL,  -- relative path; empty string for repo scope
    summary      TEXT    NOT NULL,
    model        TEXT,
    content_hash TEXT,              -- source hash at time of generation
    prompt_tokens    INTEGER,
    completion_tokens INTEGER,
    created_at   INTEGER DEFAULT (unixepoch()),
    UNIQUE(repo_id, scope, target_path)
);

-- Saved context bundles
CREATE TABLE context_bundles (
    id           INTEGER PRIMARY KEY,
    repo_id      INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    task_type    TEXT,               -- analyze|summarize|refactor-prep|custom
    token_budget INTEGER,
    token_count  INTEGER,            -- actual count after packing
    content      TEXT    NOT NULL,   -- the full context bundle as text
    file_paths   TEXT,               -- JSON array of included file paths
    created_at   INTEGER DEFAULT (unixepoch())
);

-- AI task run log (schema v2 — see repolens/db/migrations.py)
CREATE TABLE runs (
    id                    INTEGER PRIMARY KEY,
    repo_id               INTEGER REFERENCES repos(id) ON DELETE SET NULL,
    bundle_id             INTEGER REFERENCES context_bundles(id) ON DELETE SET NULL,
    task_type             TEXT,
    task_description      TEXT,
    model                 TEXT,
    prompt_tokens         INTEGER,
    completion_tokens     INTEGER,
    cache_read_tokens     INTEGER DEFAULT 0,  -- v2: cache reads at 0.1× input
    cache_creation_tokens INTEGER DEFAULT 0,  -- v2: cache writes at 1.25× input (5m TTL)
    cost_usd              REAL,
    result                TEXT,
    status                TEXT DEFAULT 'pending',  -- pending|running|done|failed
    error_message         TEXT,
    created_at            INTEGER DEFAULT (unixepoch()),
    completed_at          INTEGER
);

-- Schema version tracking
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER DEFAULT (unixepoch())
);
```

Indexes:
```sql
CREATE INDEX idx_files_repo ON files(repo_id);
CREATE INDEX idx_files_score ON files(repo_id, importance_score DESC);
CREATE INDEX idx_summaries_lookup ON summaries(repo_id, scope, target_path);
CREATE INDEX idx_runs_repo ON runs(repo_id, created_at DESC);
```

---

## 4. CLI Interface

Built with [Typer](https://typer.tiangolo.com/) (type-annotated Click). Single entrypoint: `repolens`.

### Commands

```
repolens ingest <path> [--name NAME] [--ignore PATTERN...]
repolens scan <repo>
repolens classify <repo>
repolens summarize <repo> [--scope file|dir|repo|all] [--force]
repolens context <repo> --task TASK --budget TOKENS [--output PATH] [--format markdown|json]
repolens run <repo> --task TASK [--description TEXT] [--budget TOKENS] [--model MODEL]
repolens status [<repo>]
repolens list
repolens runs [<repo>] [--limit N]
```

### Command details

**`ingest`**: Registers a repo in the DB and runs initial scan + classification. Does not summarize (that costs API tokens — user calls `summarize` explicitly).

**`scan`**: Re-scans an already-registered repo. Updates file metadata, detects new/deleted/modified files.

**`classify`**: Re-runs classification and scoring on all files. Non-destructive.

**`summarize`**: Generates AI summaries. `--scope` controls which level(s) to run. `--force` regenerates even if cached summaries exist and hashes match.

**`context`**: Builds a context bundle and writes it to stdout or `--output PATH`. Does not call AI. Use to preview what would be sent to the model.

**`run`**: Builds context bundle, sends to AI with the task description, logs the run. Prints result to stdout.

**`status`**: Shows repo stats: file count, classification breakdown, summary coverage, last scan time.

**`list`**: Lists all tracked repos with path and last scan time.

**`runs`**: Shows recent AI task runs for a repo (or all repos).

### Output formats

Default: human-readable text to stdout.
`--format json`: machine-readable JSON (for piping or programmatic use).
`--output PATH`: write to file instead of stdout.

### `<repo>` argument

Accepts: integer repo ID, repo name, or absolute/relative path. Resolved in that order.

---

## 5. FastAPI Endpoints (MVP Minimal)

Start with `uvicorn repolens.api.main:app`. Intended for local tooling integration, not production exposure.

```
GET  /repos                     List all repos
POST /repos                     Ingest a new repo {path, name?, ignore?[]}
GET  /repos/{id}                Repo details + stats
POST /repos/{id}/scan           Trigger re-scan
POST /repos/{id}/summarize      Trigger summarization {scope?, force?}
GET  /repos/{id}/context        Build context bundle {task, budget, format?}
POST /repos/{id}/run            Run AI task {task_type, description?, budget?, model?}
GET  /runs/{id}                 Get run result
GET  /runs                      List recent runs {repo_id?, limit?}
```

All endpoints return JSON. Errors return `{"error": "message"}` with appropriate HTTP status.

No auth. No middleware beyond request logging. This is a local tool.

---

## 6. File and Directory Structure

```
repolens_v2_repo/
├── repolens/
│   ├── __init__.py
│   ├── config.py               App config (DB path, model, token limits from env)
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py             Typer app, all CLI commands
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── scanner.py          Directory walker
│   │   └── filters.py          Ignore rules, binary detection
│   ├── classification/
│   │   ├── __init__.py
│   │   └── classifier.py       Rules engine + scorer
│   ├── summarization/
│   │   ├── __init__.py
│   │   ├── file_summarizer.py
│   │   ├── dir_summarizer.py
│   │   └── repo_summarizer.py
│   ├── context/
│   │   ├── __init__.py
│   │   ├── packager.py         Context bundle builder
│   │   ├── token_counter.py    tiktoken wrapper
│   │   └── exporter.py         Markdown/JSON export
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── client.py           Anthropic SDK wrapper
│   │   ├── prompts.py          Prompt templates
│   │   └── executor.py         Run tasks, log to DB
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.py           CREATE TABLE statements + migration runner
│   │   └── repository.py       Data access layer (no raw SQL outside here)
│   └── api/
│       ├── __init__.py
│       └── main.py             FastAPI app
├── tests/
│   ├── conftest.py             Shared fixtures (temp DB, test repo)
│   ├── test_ingestion.py
│   ├── test_classification.py
│   ├── test_context.py
│   ├── test_db.py
│   └── fixtures/
│       └── sample_repo/        Minimal fake repo for tests (no API calls needed)
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── DESIGN.md
└── tasks.yaml                  Roadrunner task queue
```

---

## 7. AI Integration Points

### 7.1 Where AI is called

| Location | Purpose | Prompt size |
|---|---|---|
| `file_summarizer.py` | Summarize one file | File content, capped at 50K tokens |
| `dir_summarizer.py` | Summarize one directory | All file summaries in dir |
| `repo_summarizer.py` | Summarize entire repo | All directory summaries |
| `executor.py` | Run a user task | Full context bundle + task description |

All AI calls go through `ai/client.py`. Calls are logged to the `runs` table on completion.

### 7.2 Prompt structure

**File summary:**
```
You are analyzing source code. Summarize this file in 2-4 sentences covering:
- What the file does
- Key functions, classes, or exports it defines
- Any notable dependencies or side effects

File: {relative_path}
Language: {language}

{file_content}
```

**Directory summary:**
```
Summarize the purpose of this directory given the following file summaries.
2-3 sentences maximum. Be specific about what the directory owns.

Directory: {dir_path}/

{file_summaries_block}
```

**Repo summary:**
```
Write a concise 4-6 sentence overview of this codebase.
Cover: what it does, key architectural components, primary language/stack, and intended users.

{directory_summaries_block}
```

**Task execution:**
```
You are analyzing a software repository. Use the provided context to answer the task.
Be specific, cite file paths when referencing code, and stay within the context given.
If the context is insufficient, say so explicitly rather than guessing.

=== REPOSITORY CONTEXT ===

{context_bundle}

=== TASK ===

{task_description}
```

### 7.3 Cost controls

- File summarization is batched; user confirms before running if estimated cost > $0.50
- Summaries are cached aggressively (keyed by content_hash); re-running summarize on unchanged files is free
- Context bundles include token count before the run command sends to AI
- `--dry-run` flag on `run` command prints estimated tokens/cost without calling the API

### 7.4 Model configuration

```python
# repolens/config.py
REPOLENS_MODEL = os.getenv("REPOLENS_MODEL", "claude-opus-4-7")
REPOLENS_MAX_TOKENS = int(os.getenv("REPOLENS_MAX_TOKENS", "4096"))
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]  # hard fail at call time

# repolens/ai/client.py — timeouts and retries are set at construction time.
REPOLENS_TIMEOUT = int(os.getenv("REPOLENS_TIMEOUT", "60"))
REPOLENS_MAX_RETRIES = int(os.getenv("REPOLENS_MAX_RETRIES", "2"))
# REPOLENS_ACCURATE_TOKENS=1 switches count_tokens() to the native
# Anthropic endpoint (ADR-005).
```

---

## 8. Non-Goals (MVP)

- No web UI (CLI + JSON export only)
- No multi-user access or authentication
- No cloud sync or remote storage
- No real-time file watching
- No AST parsing (extension + path rules only for classification)
- No RAG / vector search
- No patch generation or code editing
- No git history analysis (mtime from filesystem only)
- No support for private GitHub/GitLab repos (local path only)
- No streaming responses (batch only for MVP)

---

## 9. Key Dependencies

```toml
[project]
dependencies = [
    "anthropic>=0.65.0",
    "typer>=0.24.0",
    "fastapi>=0.130.0",
    "uvicorn[standard]>=0.30.0",
    "gitignore-parser>=0.1.11",
    "tiktoken>=0.8.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.15.0",
    "httpx>=0.27.0",   # for FastAPI test client
]
```

---

## 10. Open Questions

1. Should `summarize` batch all files in one API call (cheaper, less latency) or one call per file (simpler retry logic, better cache granularity)? Recommendation: one call per file for MVP, batch later if cost is a pain point.
2. Token budget default for context command: 32K or 64K? Recommend 32K as safe default; override with `--budget`.
3. Should the FastAPI layer be part of MVP or deferred? It's thin enough to include but can be dropped if the weekend build is running long. CLI is fully functional without it.
