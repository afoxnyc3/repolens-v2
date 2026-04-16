# ADR-003: FastAPI Layer — Include in MVP or Defer

**Date:** 2026-04-15
**Status:** Superseded by [ADR-007](ADR-007-fastapi-un-defer.md) (2026-04-16)
**Decider:** Clarke (reviewed from architect recommendation)

---

## Context

The design includes a thin FastAPI layer for local tooling integration. The architect flagged this as optional for MVP — the CLI is fully functional without it, and adding it during the initial build adds surface area and test burden.

Options:
- **Include in MVP** — Build CLI + API together. More complete from day one.
- **Defer** — Build CLI only first. Add FastAPI once the core modules are proven.

## Decision

**Defer FastAPI until CLI is stable.**

## Reasoning

- The FastAPI layer is a thin wrapper over the CLI commands. It adds no new logic — it only exposes what the CLI already does over HTTP. This means it can be added at any point without architectural changes.
- Adding it during the initial roadrunner-driven build adds test surface (need `httpx` test client, async test setup, endpoint validation) that slows down the core build loop.
- The first real use of Repolens will be by Alex, locally, via CLI. There is no immediate consumer of the API.
- Introducing it too early risks the API shape drifting from the CLI commands as the CLI stabilises — better to lock the CLI interface first (see ADR-002 for CLI design), then wrap it.
- roadrunner's task queue is scoped to the CLI build. Adding FastAPI tasks would require re-sequencing the task graph or tacking them onto the end — both options increase the risk of the first run timing out or stalling.

## Consequences

- `repolens/api/` directory is created as a stub with a placeholder `main.py` (so the intended structure is clear) but no implementation.
- FastAPI tasks are captured in `tasks.yaml` as a separate phase, marked `status: deferred`, so they don't enter the roadrunner queue until explicitly unblocked.
- The decision to include or exclude the API layer in a future run is a one-line change in tasks.yaml (change `deferred` to `todo`).
