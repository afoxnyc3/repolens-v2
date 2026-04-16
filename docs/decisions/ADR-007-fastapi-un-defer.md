# ADR-007: Un-defer FastAPI Layer (supersedes ADR-003)

**Date:** 2026-04-16
**Status:** Accepted
**Supersedes:** [ADR-003](ADR-003-fastapi-mvp-scope.md)
**Decider:** Alex

---

## Context

ADR-003 (2026-04-15) deferred the FastAPI layer from the roadrunner MVP queue on the grounds that the CLI was the only near-term consumer and the API surface would drift from the CLI if built too early. Those risks are now resolved:

- The CLI surface stabilized through T18/T19 (run, status, list, runs commands).
- T20 and T21 were added to the queue to wire the API layer against the stable CLI contract.
- The API is implemented as a thin wrapper that reuses the same module functions (`scan_repo`, `classify_file`, `build_context`, `execute_task`), so it cannot drift without breaking the CLI tests too.

## Decision

**Implement the FastAPI layer as part of the MVP. `repolens/api/main.py` ships GET/POST `/repos`, GET `/repos/{id}`, POST `/repos/{id}/scan`, POST `/repos/{id}/classify`, GET `/repos/{id}/context`, POST `/repos/{id}/run`, GET `/runs/{id}`, and GET `/runs`. All endpoints are synchronous (MVP), use Pydantic response models, and share a per-request SQLite connection via a dependency. Startup/shutdown uses a `lifespan` context manager.**

## Reasoning

- Each endpoint is ≤30 lines and reuses existing module functions — no business logic lives in the API layer.
- ADR-003's main concern (drift between CLI and API) is addressed by the shared-module pattern; a break in either surface is caught by the corresponding test suite.
- The API is useful for local integrations (e.g. editor plugins hitting `uvicorn repolens.api.main:app --port 8765`) and doesn't add meaningful maintenance burden.
- Deferring now would mean writing these 29 tests in `tests/test_api.py` against an unknown future codebase — worse review ergonomics.

## Consequences

- `repolens/api/__init__.py` re-exports `app` from `repolens.api.main`.
- 29 new tests in `tests/test_api.py` (all mocked for the AI path).
- ADR-003 marked Superseded (see that file's header update).
- No streaming, no background tasks, no auth — all explicit MVP non-goals carry over from DESIGN.md §8.

## References

- [ADR-003: FastAPI Layer — Defer](ADR-003-fastapi-mvp-scope.md) (superseded)
- `repolens/api/main.py`
- `tests/test_api.py`
