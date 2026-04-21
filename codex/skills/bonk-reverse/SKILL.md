---
name: bonk-reverse
description: Plan and research BonkScanner reverse-engineering features involving memory reads, hooks, IL2CPP dump analysis, offsets, pointer chains, signatures, GameAssembly-relative addresses, and Cheat Engine MCP live-process investigation. Use when Codex needs to analyze or plan BonkScanner reverse work without modifying project files.
---

# Bonk Reverse

Use this skill to investigate and plan reverse-engineering features for the BonkScanner project. This skill is read-only: it may gather facts and produce a technical direction, but it must not edit files, apply patches, change repo state, inject new behavior, or implement code.

## Source Order

Always start by reading `docs/memory-and-hooks-reference.md`. Treat it as the first source of truth for current memory chains, hook entry points, offset semantics, and project-specific reverse-engineering notes.

After reading the reference doc, follow its entry-point guidance and inspect only the project sources needed for the requested feature.

Use the IL2CPP dump only after the reference doc and relevant project sources. Prefer targeted searches in:

- `Dump/dump.cs`
- `Dump/il2cpp.h`
- `Dump/script.json`
- `Dump/stringliteral.json`
- `Dump/DummyDll/`

## Allowed Investigation

- Read and search project files.
- Inspect IL2CPP dump files for classes, methods, fields, offsets, signatures, string literals, and likely hook targets.
- Use Cheat Engine MCP tools when live-process confirmation is needed, including symbol lookup, address info, disassembly, pointer-chain reads, memory-region enumeration, and thread inspection.
- Use the offset semantics from `docs/memory-and-hooks-reference.md`; do not restate or override them here.

## Forbidden Actions

- Do not edit, create, delete, move, or rewrite project files.
- Do not apply patches or run formatters/codegen that change tracked files.
- Do not change repository state, git state, config files, generated sources, or docs.
- Do not inject new behavior or make implementation changes.
- Do not treat live Cheat Engine observations as a replacement for documenting the static source/dump evidence that led to them.

## Workflow

1. Restate the feature goal briefly.
2. Read `docs/memory-and-hooks-reference.md`.
3. Follow the reference doc to choose the smallest relevant project entry points.
4. Search `Dump/` for matching IL2CPP classes, methods, fields, string literals, offsets, signatures, or hook candidates.
5. Use Cheat Engine MCP only when static evidence is insufficient or a live address/pointer path needs confirmation.
6. Distinguish confirmed facts from inferences.
7. If exactly one viable path exists, produce a concise technical description.
8. If multiple viable paths exist, stop and ask the user to choose between concrete options before giving a final technical direction.

## Final Output

End with a brief technical note, not an implementation patch. Include:

- Feature goal as understood.
- Relevant existing code and dump sources.
- Discovered memory or hook facts.
- Recommended implementation direction.
- Unresolved risks or confirmations needed.

If there are alternatives, present the concrete options and ask the user which route to take.
