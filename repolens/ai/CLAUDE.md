# repolens/ai — agent brief

The Anthropic SDK wrapper and prompt-template layer. Every API call
goes through `client.py:RepolensClient.complete()`.

## Stable invariants

- **`CompletionResult` is a 5-field NamedTuple** — `text`,
  `input_tokens`, `output_tokens`, `cache_read_tokens`,
  `cache_creation_tokens`. Callers use attribute access
  (`result.input_tokens`), not positional unpacking. Tests construct
  one via the `_cr(text, input, output, cache_read=0, cache_creation=0)`
  helper in `tests/test_ai.py`.

- **Prompt builders in `prompts.py` return `(system, user)` tuples.**
  Every template follows the same split: stable instructions in the
  system block (prime cache candidate), per-call payload in the user
  block. Bare-string prompts still work for backwards compatibility
  but skip prompt-caching.

- **Empirical prompt-cache floor is 2048 tokens across all model
  families.** Anthropic's documented 1024-token minimum for Opus/Sonnet
  does *not* actually trigger a cache write on `claude-opus-4-7` — see
  [ADR-004](../../docs/decisions/ADR-004-prompt-caching.md) "Threshold
  note" for the empirical observation. Source of truth:
  `_MIN_CACHE_TOKENS_BY_FAMILY` in `client.py`. If Anthropic clarifies
  the docs or the server floor changes, update this dict.

- **Cache-control tagging is automatic.** `complete()` attaches
  `cache_control={"type":"ephemeral"}` to the system block when the
  block meets the family minimum (rough `len // 4` estimate) AND the
  caller didn't pass `cache=False`. Call sites don't make this
  decision; the client owns it.

- **Model default** lives in one place: `client.py:RepolensClient.DEFAULT_MODEL`,
  mirrored in `repolens/config.py`. Follow the checklist in
  [ADR-006](../../docs/decisions/ADR-006-model-ids.md) when bumping:
  update both files, add the new ID to the pricing table in
  `repolens/context/token_counter.py`, keep retired IDs in the pricing
  table, update test assertions, add a CHANGELOG entry.

- **Retries + timeout** are set at construction (`max_retries=2`,
  `timeout=60`). Configurable via `REPOLENS_MAX_RETRIES` and
  `REPOLENS_TIMEOUT`. The SDK handles retry backoff internally; do
  not add another retry loop around `complete()`.

- **SDK floor: `anthropic>=0.65.0`** (see `pyproject.toml`). Older
  versions omit `cache_read_input_tokens` / `cache_creation_input_tokens`
  on the usage object. `getattr(usage, ..., 0)` makes the client
  tolerate that, but cache accounting is silently zero on older SDKs.

- **`response.content` can be empty.** Some prompts (malformed or
  filtered) return no text blocks. `complete()` concatenates every
  text block defensively and returns `""` rather than crashing on an
  empty list.

## Editing guidance

- **New prompt type?** Add it to `prompts.py` as a `(system, user)`
  tuple. Put invariant instructions in system so cache breakpoints
  land on the stable block.
- **New task?** Wire it through `executor.py` via `execute_task()` so
  the run row captures all four token lanes automatically.
- **Touching `complete()`?** Keep both call shapes (bare string and
  tuple) working — existing callers rely on both.
