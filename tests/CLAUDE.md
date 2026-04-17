# tests — agent brief

Flat pytest layout. 401 unit tests + 1 e2e smoke as of 2026-04-17.

## Test layout

- **Unit tests** — `test_<module>.py`. Mock-heavy, no network. Run by
  default with `pytest -q`.
- **E2E smoke** — `tests/test_smoke_e2e.py` with
  `@pytest.mark.e2e`. Skipped unless `ANTHROPIC_API_KEY` is set.
  Cost ≈ \$0.50 per run; writes `smoke_test_output.md` at the repo
  root (gitignored — it's a per-run artifact).
- **Naming** — mirror the module path flat: tests for
  `repolens/foo/bar.py` live in `tests/test_foo_bar.py`. No nested
  `tests/` directories.

## Running subsets

```bash
.venv/bin/pytest -q                                         # unit suite (fast)
.venv/bin/pytest -q tests/test_db_migrations.py             # single file
.venv/bin/pytest -q -m e2e tests/test_smoke_e2e.py          # real API run
.venv/bin/pytest -q -k "cache" tests/test_ai.py             # by keyword
```

## Fixtures (from `conftest.py`)

- `tmp_db` — throwaway SQLite `Connection` backed by a tempfile. Use
  for unit tests that don't need a full schema (the connection is bare
  — call `init_db()` manually if the schema is needed).
- `sample_repo_path` — minimal fake repo (main.py, README.md,
  pyproject.toml, tests/test_main.py, .gitignore). Use for
  classifier, scorer, and ingestion tests.

## Mocking the Anthropic SDK

Two layers:

- **Raw response** — `_make_response(text, input_tokens, output_tokens,
  cache_read_input_tokens=0, cache_creation_input_tokens=0)` in
  `test_ai.py` builds a `SimpleNamespace` shaped like the real SDK
  response. Use when testing `RepolensClient.complete()` directly and
  you want to control the `response.usage` shape.
- **CompletionResult** — `_cr(text, input, output, cache_read=0,
  cache_creation=0)` in `test_ai.py` builds the NamedTuple that
  `complete()` returns. Use when mocking a whole `RepolensClient`:
  ```python
  MockClient.return_value.complete.return_value = _cr("answer", 50, 20)
  ```
  The same helper is duplicated in `test_api.py` and
  `test_summarization.py` (deliberately — keeps each test module
  self-contained).

## Patterns to follow

- Patch `repolens.ai.executor.RepolensClient` and
  `repolens.ai.executor.build_context` when exercising `execute_task`,
  not the inner SDK objects.
- For migration tests, build both a fresh DB (via `init_db()`) and a
  hand-rolled v(N-1) DB to exercise the upgrade path — see
  `tests/test_db_migrations.py`.
- When adding a test that touches env vars, use `monkeypatch.setenv` /
  `monkeypatch.delenv` and reload the module if it captures env at
  import time (e.g. `repolens.config`).

## Gating and CI

- `pyproject.toml` registers the `e2e` marker and drops
  `asyncio_mode = "auto"` (no async tests).
- E2E tests must never run in the default suite; the `@pytest.mark.e2e`
  decorator plus the `ANTHROPIC_API_KEY` skip guard is the contract.
