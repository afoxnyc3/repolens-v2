# ADR-006: Model ID Pinning and Deprecation Policy

**Date:** 2026-04-16
**Status:** Accepted
**Decider:** Alex

---

## Context

The original config defaulted to `claude-opus-4-5`. As of 2026-04-16 that alias is superseded: Opus 4.7 is the current Opus release, Sonnet 4.6 is current Sonnet, Haiku 4.5 is current Haiku. Stale model IDs cause two problems: (a) eventual server-side retirement errors when the old alias is removed, and (b) misleading cost estimates because the pricing table may not track retired-model prices once they're dropped.

## Decision

**One source of truth for the default model ID: `repolens.ai.client.RepolensClient.DEFAULT_MODEL`, mirrored in `repolens.config.REPOLENS_MODEL`. Current default: `claude-opus-4-7`. Every release cycle reviews this default; any Anthropic deprecation announcement triggers a P0 commit that:**

1. **Bumps the default model ID.**
2. **Adds the new model ID to the `_PRICING` table in `repolens/context/token_counter.py`.**
3. **Keeps the retired ID in the pricing table so historical `runs` rows can still be costed.**
4. **Adds a CHANGELOG entry noting the change and a migration note for users pinning the old ID via `REPOLENS_MODEL`.**

## Reasoning

- A single constant prevents the drift the audit found (model id hardcoded in config.py, client.py, *and* cli/main.py).
- Keeping retired IDs in the pricing table avoids silent fallback-to-Sonnet costing on old run rows.
- Tying the bump to an ADR (not just a silent constant change) forces us to notice when pricing changes alongside deprecation.

## Consequences

- Tests that hardcoded `"claude-opus-4-5"` as the default were updated to `"claude-opus-4-7"` in the same commit as the flip.
- Tests using the old ID for pricing assertions are still valid (old ID retained in `_PRICING`).
- `REPOLENS_MODEL` env var always wins, so users on pinned-model workflows are unaffected by a default bump.

## Policy checklist for future model bumps

- [ ] Update `DEFAULT_MODEL` in `repolens/ai/client.py`.
- [ ] Update the default in `repolens/config.py` and any CLI fallback strings.
- [ ] Add new model ID to `_PRICING` in `repolens/context/token_counter.py`.
- [ ] Keep retired IDs in `_PRICING`.
- [ ] Update tests that assert on the default ID.
- [ ] CHANGELOG: "Default model bumped; users on `REPOLENS_MODEL=<retired-id>` should review."

## References

- https://platform.claude.com/docs/en/about-claude/models/overview
- https://platform.claude.com/docs/en/about-claude/model-deprecations
