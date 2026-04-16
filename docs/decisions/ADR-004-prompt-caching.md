# ADR-004: Prompt Caching with Ephemeral System Blocks

**Date:** 2026-04-16
**Status:** Accepted
**Decider:** Alex

---

## Context

An audit of Repolens v2 found that every summarizer and the task executor were re-sending identical instruction text on each API call. A single `summarize --scope all` pass against a 100-file repo re-transmits the same ~800 characters of system-role prompt 100+ times. The Anthropic prompt-cache feature (released 2024, generally available in 2026) lets us mark stable prefixes with `cache_control={"type": "ephemeral"}` and reuse them at 10% of the input rate on subsequent calls within a 5-minute TTL window.

Options considered:
- **Do nothing** — accept the full cost of redundant input tokens.
- **Cache the system block only** (chosen) — stable instructions become cacheable; per-call payload stays in the user block.
- **Cache the system block + context bundle for task execution** — larger cache hit for multi-task sessions against the same repo.

## Decision

**Split every prompt builder into `(system, user)` tuples. The system block carries invariant instructions. `RepolensClient.complete()` attaches `cache_control={"type":"ephemeral"}` to the system block when it meets the minimum cacheable size for the model family (1024 tokens for Opus/Sonnet, 2048 for Haiku). Task-execution prompts put the full repository context inside the system block so a session of multiple runs against one repo reuses the cached context.**

## Reasoning

- Summarizer system blocks are identical across every file/dir/repo in a run — prime cache candidate.
- Task executor's system block now includes the context bundle, which typically doesn't change between successive questions about the same repo. One cache write, many cache reads at 0.1× input cost.
- Minimum-token gate prevents silent no-op cache markers on small prompts (the server ignores them but counting them as "enabled" in logs is misleading).
- 5-minute TTL is the default breakeven after one read; 1-hour TTL (2× creation cost, breakeven after two reads) is not used in MVP — can be added later under a flag if cost data supports it.
- Token accounting: `response.usage.cache_read_input_tokens` and `cache_creation_input_tokens` are captured in the new schema v2 columns (see ADR-006 for schema policy). `estimate_cost_detailed()` applies the 0.1× / 1.25× / 1× / 1× lane multipliers.

## Consequences

- `RepolensClient.complete()` accepts either a bare string (legacy, still works) or a `(system, user)` tuple.
- All prompt builders in `repolens/ai/prompts.py` now return tuples.
- Tests migrated to attribute access on the new `CompletionResult` NamedTuple.
- `runs` table gains `cache_read_tokens` and `cache_creation_tokens` (schema v2 migration — see `repolens/db/migrations.py`).
- Expected cost reduction on repeat-run summarization: 85-95% on input cost after the first pass warms the cache.
- Out of scope: 1-hour TTL, multi-breakpoint cache structures, cache invalidation strategy (5-minute TTL handles itself).

## References

- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://platform.claude.com/docs/en/about-claude/pricing
