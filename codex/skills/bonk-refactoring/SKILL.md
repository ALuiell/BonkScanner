---
name: bonk-refactoring
description: Refactor existing BonkScanner code for cleanup, restructuring, simplification, deduplication, maintainability, and clearer failure paths. Use when Codex needs to improve existing code structure without adding features, changing behavior, or modifying reverse-engineering facts.
---

# Bonk Refactoring

Use this skill to refactor existing BonkScanner code only. Refactoring may improve structure, naming, duplication, and maintainability, but it must preserve behavior unless the user explicitly asks for a behavior change.

## Refactor Boundaries

- Do not add new features.
- Do not intentionally change runtime behavior, UI behavior, config shape, public interfaces, memory chains, hook behavior, native exports, offsets, or error behavior.
- Do not invent, update, or reinterpret reverse-engineering facts.

## Refactoring Rules

- Start by identifying the exact existing code area the user wants refactored.
- Inspect nearby code, tests, call sites, and existing style before editing.
- Prefer small mechanical improvements: clearer naming, extraction, deduplication, simplified conditionals, lower coupling, removal of dead local complexity, and clearer failure paths.
- Avoid broad rewrites, architecture changes, speculative abstractions, formatting-only churn, and unrelated cleanup.
- If native hook code is touched, preserve byte checks, calling conventions, exported names, and loader expectations.
- If Python memory reading code is touched, preserve safe process/module failure handling.

## Workflow

1. Restate the refactor goal and expected preserved behavior.
2. Inspect relevant code paths, call sites, and tests before editing.
3. Make the smallest coherent refactor.
4. Update tests only when existing tests need adjustment for renamed or extracted internals, or when coverage is needed to prove behavior stayed stable.
5. Run targeted verification first, then broader checks only if shared behavior was touched.
