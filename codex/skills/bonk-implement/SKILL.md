---
name: bonk-implement
description: Implement BonkScanner features from a technical plan produced by the bonk-reverse skill. Use when Codex needs to turn a BonkScanner reverse-engineering plan into scoped code changes, tests, and verification while preserving existing memory and hook behavior.
---

# Bonk Implement

Use this skill to implement BonkScanner features from a technical plan produced by `bonk-reverse`. Treat that plan as the primary source for reverse-engineering facts, target behavior, memory or hook direction, and unresolved risks.

## Inputs

Start from the user's provided `bonk-reverse` technical note or plan. If the plan is missing, has unresolved alternatives, or asks for a user choice, stop and ask for that decision before implementing.

When the plan depends on memory or hook semantics, read `docs/memory-and-hooks-reference.md` only to confirm current project guidance. Do not duplicate its content in the implementation notes.

## Implementation Rules

- Keep changes tightly scoped to the provided plan.
- Prefer existing project patterns, helpers, naming, and error-handling style.
- Inspect the smallest relevant code surface before editing.
- Preserve existing memory chains, hook behavior, and UI behavior unless the plan explicitly changes them.
- Do not invent new reverse-engineering facts. If implementation reveals the plan is wrong or incomplete, pause and report the conflict.
- Avoid broad refactors, unrelated cleanup, and speculative abstractions.
- If native hook code is touched, keep byte checks, calling conventions, exported names, and loader expectations aligned.
- If Python memory reading code is touched, keep process/module failure paths explicit and safe for unavailable game processes.
- At the end of implementation, update `docs/memory-and-hooks-reference.md` only if the change modifies durable memory chains, hook entry points, offset semantics, or reverse-engineering guidance that future `bonk-reverse` runs must know.

## Workflow

1. Restate the implementation goal and the `bonk-reverse` plan assumptions.
2. Inspect the relevant code paths and any tests before editing.
3. Make the smallest coherent code change that implements the plan.
4. Update or add focused tests when practical.
5. If relevant memory or hook guidance changed, update `docs/memory-and-hooks-reference.md` after the code change.
6. Run targeted verification first, then broader checks only when the change touches shared behavior.
7. Summarize changed files, verification results, and any remaining runtime checks the user should perform.
