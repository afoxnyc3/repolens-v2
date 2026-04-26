# repolens/summarization — agent brief

AI-generated summaries at three scopes: file, directory, and repo.
Every summarizer caches its output in SQLite, keyed by content hash.

## Invariants

- **Bottom-up assembly only.** Files are summarized first, then
  directories, then the whole repo. A directory summarizer receives
  the *file summaries* in its directory — never raw file content.
  This keeps prompt sizes bounded and makes the system block
  prompt-cacheable (see [ADR-004](../../docs/decisions/ADR-004-prompt-caching.md)).

- **Cache key:** `(repo_id, scope, target_path)` in the `summaries`
  table. The stored `content_hash` is the version tag. On the next
  run, a file summary is served from cache iff its cached
  `content_hash` matches the current source file's sha256.

- **Summarization is opt-in.** `ingest` and `classify` never trigger
  summarization — it costs API tokens. The user must run
  `repolens summarize` (or call the HTTP equivalent) explicitly. This
  is an intentional cost guardrail.

- **File content cap: `_CONTENT_CHAR_LIMIT = 200_000`** (≈50K
  tokens). Larger files are truncated at the character boundary
  before the prompt is built. The summary reflects only the
  truncated content.

- **Dir/repo summaries don't auto-invalidate on child changes.** If a
  file is re-summarized, its parent directory summary still hits the
  cache until `--force` or an explicit regenerate. Known limitation;
  workaround is `repolens summarize --force --scope dir` (or `repo`).

- **Prompt caching is active by default, but rarely fires for the
  user-facing summarize path in practice.** Per-call system blocks for
  file/dir/repo summarization fall under the 2048-token cache-write
  floor (ADR-004), so the typical full-repo `summarize --scope all`
  pays full input cost at every call. The CLI surfaces this honestly:
  when both `cache_read_tokens` and `cache_creation_tokens` are zero
  across a run, `summarize` prints `Prompt cache: inactive (...)`.
  Cache fields are persisted per-summary in schema v3 so this is
  auditable from `summaries.cache_*` as well as the run-level
  `runs.cache_*` columns.

## Editing guidance

- **New scope?** Follow the `file_summarizer.py` / `dir_summarizer.py`
  / `repo_summarizer.py` shape: check cache first, build the
  `(system, user)` prompt via `repolens/ai/prompts.py`, call
  `client.complete(prompt)`, upsert via `repository.upsert_summary`.
- **Changing instructions?** Invalidate existing caches if the wording
  change is substantial — otherwise users will see mixed-vintage
  summaries for the same scope. A schema-version bump is overkill for
  prompt-text changes; a CHANGELOG note + an explicit recommendation
  to `--force` next summarize is sufficient.
