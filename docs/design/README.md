# Design Notes

This directory stores feature-level design notes, implementation decisions,
fallback strategies, and comparisons between alternative approaches.

Use `docs/design/` for documents that answer questions like:

- Which implementation options were considered?
- Which approach was chosen for production?
- Why was that approach selected over other options?
- What fallback or diagnostic strategies should be kept in mind if the feature
  needs to be revisited later?

Use other documentation areas for different purposes:

- `docs/recovery/reports/`: reverse-engineering findings, offsets, pointer
  chains, and raw memory validation notes.
- `docs/wiki/`: current system behavior, architecture, and developer-facing
  feature documentation.
- `docs/mechanics/`: game mechanics and formula references.

Typical candidates for `docs/design/` include:

- command implementation notes such as `!chests`
- transition-detection strategy decisions
- alternative tracking-model comparisons
- UI behavior decisions when multiple approaches were evaluated
