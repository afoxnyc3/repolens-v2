# ADR-005: Native Anthropic Tokenizer with tiktoken Fallback

**Date:** 2026-04-16
**Status:** Accepted
**Decider:** Alex

---

## Context

Repolens v2 counts tokens in two places: (1) the context packager's greedy budget loop, and (2) cost estimation. Both used `tiktoken` (`cl100k_base`), which is OpenAI's tokenizer, not Claude's. For code-heavy content the drift is routinely 10–20%, inflating budgets and distorting cost previews.

Anthropic's Python SDK exposes `client.messages.count_tokens(...)` which returns the authoritative server-side count. It is a network call — a typical ingest runs `count_tokens` against every file, which would mean N HTTP round-trips per repo-summarize pass.

Options:
- **Always tiktoken** (status quo) — fast, local, wrong-tokenizer drift.
- **Always Anthropic** — authoritative but latency/cost-sensitive for interactive CLI use.
- **Local default, opt-in accurate** (chosen) — tiktoken for greedy packing decisions (where approximate is fine), Anthropic for cost-preview paths and when the user explicitly wants correctness.

## Decision

**Keep tiktoken as the default local estimator. Add `count_tokens(text, *, accurate=False, model=None)` with an accurate path that delegates to `anthropic.Anthropic().messages.count_tokens`. Accurate results are cached in-process by SHA-256 hash of the input. Opt-in via the `accurate=True` kwarg or the `REPOLENS_ACCURATE_TOKENS` env var. Gracefully falls back to the local estimator on any SDK error (no API key, network, model not recognized).**

## Reasoning

- The packager's greedy file-inclusion loop runs `count_tokens` once per file per repo. At even 50ms per round-trip, 200 files would add 10s per ingest — unacceptable.
- Cost previews are the one place where accuracy matters more than speed. A 20% miscount on a `summarize --estimate` run can cause a user to misjudge whether a summarize pass is affordable.
- In-process cache keyed by content hash means the accurate path is effectively free after the first call on a given string. Disk-backed cache is a future extension, not MVP.
- Graceful fallback means the feature degrades to the old behavior when the API key isn't configured — no new hard dependency.

## Consequences

- New env var: `REPOLENS_ACCURATE_TOKENS` (accepts `1`, `true`, `yes`).
- `count_tokens()` gains keyword-only `accurate` and `model` parameters. Existing callers unchanged.
- Cost preview commands (`summarize --estimate`, `run --dry-run`) will migrate to the accurate path in a follow-up; not in this ADR's scope.
- tiktoken remains a required dep so the fallback path works without a network connection.

## References

- https://docs.anthropic.com/en/api/messages-count-tokens
- https://platform.claude.com/docs/en/build-with-claude/token-counting
