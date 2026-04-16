# Decision Log — Repolens v2

Running log of architectural and product decisions. Detailed rationale in individual ADRs.

| # | Decision | Outcome | Date | ADR |
|---|---|---|---|---|
| 1 | Summarization strategy: per-file vs batch API calls | Per-file for MVP | 2026-04-15 | [ADR-001](ADR-001-summarization-strategy.md) |
| 2 | Default token budget for context bundles | 32K (override via `--budget` or env) | 2026-04-15 | [ADR-002](ADR-002-default-token-budget.md) |
| 3 | FastAPI layer scope in MVP | Deferred (superseded by ADR-007) | 2026-04-15 | [ADR-003](ADR-003-fastapi-mvp-scope.md) |
| 4 | Prompt caching with ephemeral system blocks | 85-95% input-cost reduction on repeat summarize | 2026-04-16 | [ADR-004](ADR-004-prompt-caching.md) |
| 5 | Native Anthropic tokenizer with tiktoken fallback | Local default, opt-in accurate via env var | 2026-04-16 | [ADR-005](ADR-005-tokenizer.md) |
| 6 | Model ID pinning and deprecation policy | Default `claude-opus-4-7`; single source of truth | 2026-04-16 | [ADR-006](ADR-006-model-ids.md) |
| 7 | Un-defer FastAPI layer | Ship with MVP now that CLI surface is stable | 2026-04-16 | [ADR-007](ADR-007-fastapi-un-defer.md) |
