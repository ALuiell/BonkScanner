# Reverse Handoff Template

Use this template for new reverse reports in `docs/recovery/reports/`.

Recommended filename:

`YYYY-MM-DD-short-topic.md`

Example:

`2026-05-12-player-stats-refresh.md`

---

# Title

Date: YYYY-MM-DD

## Goal

Describe exactly what this reverse pass is trying to prove or recover.

Examples:

- recover the stable root path for player stats after game update
- confirm the passive item dictionary path across fresh sessions
- refresh hook target addresses for restart flow

## Scope

State what is in scope and what is out of scope.

Examples:

- in scope: passive items only
- out of scope: active pickups, temporary buffs, UI-only labels

## Final Conclusion

Write the best current implementation target in a short, direct form.

Example shape:

1. `GameAssembly.dll + 0x????????`
2. dereference -> `class_ptr`
3. `class_ptr + 0xB8` -> `static_fields`
4. ...

If the path is not fully confirmed, say so clearly.

## Stable Root Path

Document the highest-confidence stable root chain.

Include:

- module-relative start
- every dereference
- every field offset
- object meaning at each step

## Data Layout

If arrays, dictionaries, or lists are involved, document:

- count field
- entries/items pointer
- first entry offset
- entry stride
- key/value offsets
- name/value/count fields inside the item object

## Name / Label Source

Explain exactly where the readable identity comes from.

Examples:

- Mono string at `object + 0x??`
- ASCII class name via `class_meta + 0x10`
- enum id mapped through static table

## Confirmation Across Sessions

Show whether the path survives fresh game sessions.

Minimum useful proof:

- Session A result
- Session B result
- note that live addresses changed but the chain still worked

## Rejected Paths

List tempting but unsafe paths that should not be implemented.

Examples:

- one-session Cheat Engine address
- stale object that remained readable after restart
- path that gave plausible counts but empty entries

## Implementation Shape

Describe how code should read the path.

Keep it implementation-oriented.

Example:

1. resolve root
2. read container pointer
3. read dictionary pointer
4. iterate entries
5. decode count and display name

## Best Current Source Of Truth

State the exact path or logic that code should use right now.

This section should be easy to scan and copy into implementation work.

## Confidence

Rate each important claim separately.

Recommended format:

- root path: high / medium / low
- field layout: high / medium / low
- display-name source: high / medium / low
- count/value source: high / medium / low

## Open Questions

List what is still unknown.

Examples:

- whether this path is passive-only or also includes active pickups
- whether stack count is always at the same offset for all item classes
- whether names should be read from class metadata or a richer display-name source exists

## Recommended Next Action

Choose one:

- safe to implement now
- safe to implement with guardrails
- needs one more live confirmation
- not safe to implement yet

## Implementation Handoff Prompt

Write the exact prompt that can be given to Codex later.

Example:

`Use this report as source of truth and update src/player_stats.py, src/gui.py, and tests to read passive item inventory.`

