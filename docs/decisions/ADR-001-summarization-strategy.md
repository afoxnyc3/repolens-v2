# ADR-001: Summarization Strategy — Per-File vs Batch

**Date:** 2026-04-15
**Status:** Accepted
**Decider:** Clarke (reviewed from architect recommendation)

---

## Context

The summarization module needs to generate AI-powered summaries at file, directory, and repo scope. The question is whether to batch multiple files into a single API call or issue one call per file.

Options:
- **Option A — Batch:** Send multiple files in one API call. Lower per-token cost, fewer round trips.
- **Option B — Per-file:** One API call per file. Simpler retry logic, natural cache granularity.

## Decision

**Per-file (Option B) for MVP.**

## Reasoning

- Cache keys are content hashes per file. Per-file calls map cleanly to cache entries — a batch call that mixes files would require splitting and re-associating results, adding complexity.
- If one file fails or the API errors, retrying a single file is cheaper and simpler than retrying a mixed batch.
- Debugging a bad summary is easier when each call is isolated.
- For a typical repo (100-300 summarizable files), the cost difference between batch and per-file on `claude-haiku` is negligible at MVP scale (< $0.10 difference on a first run).
- Batching can be introduced later as a `--batch` flag once the per-file path is proven.

## Consequences

- Slightly more API round trips on first summarize run.
- `--force` re-summarization triggers N calls where N = files without a valid cached summary.
- Cost confirmation prompt fires if estimated total exceeds $0.50 (guards against accidentally re-running on a large repo).
- Future optimization path: batch files with the same extension/classification into grouped calls.
