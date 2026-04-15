# ADR-002: Default Token Budget for Context Bundles

**Date:** 2026-04-15
**Status:** Accepted
**Decider:** Clarke (reviewed from architect recommendation)

---

## Context

The `context` and `run` commands need a default token budget for building context bundles. The architect flagged 32K vs 64K as the decision point.

Options:
- **32K** — Safe default. Fits comfortably within Claude Haiku and Sonnet context windows. Low cost on accidental runs.
- **64K** — More generous. Useful for larger repos. Higher cost if used without thinking.

## Decision

**32K default.**

## Reasoning

- 32K covers the majority of real-world use cases: a typical Python module with its imports, a component with its tests, an API layer with its dependencies.
- A user who needs more will reach for `--budget 64000` deliberately. A user who doesn't know they're sending 60K tokens to the API will not notice until they see their bill.
- Cost discipline matters at MVP. 32K at claude-opus-4-5 rates is ~$0.48 per run input; 64K is ~$0.96. On a day of iterating, that difference compounds.
- If 32K is consistently too small for real workflows, the default can be raised — but starting high is harder to walk back without breaking user expectations.
- Power users and scripts can always override with `--budget` or `REPOLENS_TOKEN_BUDGET` env var.

## Consequences

- `--budget` flag is required documentation in CLI help text with a clear note that 32K is the default.
- Context packager must handle gracefully when a single file exceeds the budget (include a truncated version + note, never silently drop).
- Add a `REPOLENS_TOKEN_BUDGET` env var for users who want a persistent non-default.
