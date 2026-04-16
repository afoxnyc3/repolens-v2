# Repolens v2 — Product Specification

## Overview

Repolens v2 is an AI-native repository intelligence tool that transforms a local
git checkout into structured, token-efficient context for Claude — accessible
from a Python CLI or a thin FastAPI layer. Local-first, single SQLite file, no
cloud, no auth.

## Core Capabilities

- **Ingest & filter** — walk the repo, apply `.gitignore` + custom ignores,
  skip binaries and oversized files, capture metadata + sha256 content hash.
- **Classify & score** — rule-based file category (`core|test|config|docs|build|generated|other`)
  plus a deterministic importance score in `[0, 1]`.
- **Summarize** — AI-powered file → dir → repo summaries, cached by content
  hash so re-runs on unchanged content cost zero tokens.
- **Package** — token-budgeted context bundles assembled greedily by importance
  score, with per-task shaping (`analyze`, `summarize`, `refactor-prep`).
- **Execute** — synchronous AI runs with full usage accounting (base input,
  cache read, cache creation, output, USD cost) persisted to SQLite.

## Architecture

```
repo → ingestion → classification → scoring → summarization
                                               ↓
                                     context packaging → AI task → run log
```

## Model & Caching

- Default model: `claude-opus-4-7` (ADR-006). Overrideable via `REPOLENS_MODEL`
  or `--model`.
- Prompt caching enabled by default (ADR-004). Summarizers cache the stable
  instruction block; task-executor caches the full context bundle for the
  5-minute TTL window — typical workloads see 85-95% input-cost reduction
  on repeat runs against the same repo.
- Native Anthropic tokenizer available via `REPOLENS_ACCURATE_TOKENS=1`
  (ADR-005); otherwise fast local tiktoken estimate.

## Surfaces

- **CLI** (Typer): `ingest`, `scan`, `classify`, `summarize`, `context`, `run`,
  `status`, `list`, `runs`. `--dry-run`, `--output`, `--format json`.
- **HTTP** (FastAPI, ADR-007): REST mirror of the CLI — `/repos`,
  `/repos/{id}/scan|classify|context|run`, `/runs`, `/runs/{id}`.

## MVP Scope (shipped)

- Read-only repo intelligence.
- Context generation (markdown or JSON).
- Task templates: `analyze`, `summarize`, `refactor-prep`.
- Synchronous AI runs; full cache-aware cost accounting in `runs` table.
- SQLite schema v2 with migration runner.

## Explicit Non-Goals

- No web UI.
- No multi-user auth or cloud sync.
- No streaming responses (batch only).
- No AST parsing (extension + path rules only for classification).
- No RAG or vector search.
- No patch generation or code editing.
- No git history analysis beyond filesystem mtime.

## Future

- RAG / vector search for targeted retrieval.
- Patch generation (proposed edits with human review).
- Batched summarization for cost efficiency on large repos.
- 1-hour prompt-cache TTL opt-in for long analysis sessions.
