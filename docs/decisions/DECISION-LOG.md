# Decision Log — Repolens v2

Running log of architectural and product decisions. Detailed rationale in individual ADRs.

| # | Decision | Outcome | Date | ADR |
|---|---|---|---|---|
| 1 | Summarization strategy: per-file vs batch API calls | Per-file for MVP | 2026-04-15 | [ADR-001](ADR-001-summarization-strategy.md) |
| 2 | Default token budget for context bundles | 32K (override via `--budget` or env) | 2026-04-15 | [ADR-002](ADR-002-default-token-budget.md) |
| 3 | FastAPI layer scope in MVP | Deferred — CLI first, API after CLI is stable | 2026-04-15 | [ADR-003](ADR-003-fastapi-mvp-scope.md) |
