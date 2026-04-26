# Repolens v2

Repolens v2 transforms a local git checkout into token-budgeted context for
Anthropic's Claude — via CLI or a thin FastAPI layer, backed by a single
SQLite file. It ingests a repo, classifies and scores every file, caches
AI-generated summaries at file/dir/repo scope, and greedily packages the
highest-signal files inside a configurable token budget. Built for
developers who need reproducible, cache-aware, cost-visible Claude runs
instead of ad-hoc copy-paste.

---

## Status

- Default model: `claude-opus-4-7`, prompt caching on, SQLite schema v3.
- 412 unit + 1 e2e tests green on `main`.

---

## Where to read next

- [README.md](README.md) — install, env vars, quickstart, CLI + API reference.
- [DESIGN.md](DESIGN.md) — architecture, module responsibilities, data model.
- [docs/spec.md](docs/spec.md) — product-level capabilities and explicit non-goals.
- [docs/decisions/DECISION-LOG.md](docs/decisions/DECISION-LOG.md) — ADR index.
  - [ADR-004](docs/decisions/ADR-004-prompt-caching.md) — prompt caching; empirical 2048-token cache-write floor.
  - [ADR-005](docs/decisions/ADR-005-tokenizer.md) — tiktoken default, opt-in native via `REPOLENS_ACCURATE_TOKENS`.
  - [ADR-006](docs/decisions/ADR-006-model-ids.md) — model pinning + deprecation checklist.
  - [ADR-007](docs/decisions/ADR-007-fastapi-un-defer.md) — FastAPI surface scope.

---

## Scoped agent briefs (progressive disclosure)

Read only the one relevant to your task:

- [repolens/ai/CLAUDE.md](repolens/ai/CLAUDE.md) — SDK wrapper, prompt caching, model pinning, CompletionResult shape.
- [repolens/db/CLAUDE.md](repolens/db/CLAUDE.md) — schema, migration ladder, no-raw-SQL rule, WAL/FK pragmas.
- [repolens/summarization/CLAUDE.md](repolens/summarization/CLAUDE.md) — bottom-up assembly, content-hash cache, explicit-only generation.
- [tests/CLAUDE.md](tests/CLAUDE.md) — pytest conventions, e2e marker, `CompletionResult` mock pattern.

---

## Environment Setup

**Always activate the venv before running any Python, pytest, or ruff commands:**

```bash
source .venv/bin/activate
```

If `.venv` doesn't exist yet, create it first:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

---

## Working in this repo

- **Tests:** `.venv/bin/pytest -q` for the unit suite;
  `ANTHROPIC_API_KEY=… .venv/bin/pytest -q -m e2e tests/test_smoke_e2e.py`
  for the real-API end-to-end smoke.
- **Lint:** `.venv/bin/ruff check .`
- **Run the CLI:** `repolens --help` (after `pip install -e .`).
- **Run the API:** `uvicorn repolens.api.main:app --port 8765`.

When touching a module, read its scoped `CLAUDE.md` first (above) — it
documents the non-obvious invariants that a fresh reader would miss.
