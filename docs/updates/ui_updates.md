# UI Updates

Date: 2026-05-24

This file tracks open and partially completed UI-focused work.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## 1. Preserve Template Colors In Runtime Active-Templates Log

Status: `[Open]`

Current issue:

- When templates are added or updated during scanner runtime, the `Active templates updated live` log output shows template names as plain text.
- In the main templates list, those same templates already have distinct colors.
- This makes the runtime log harder to scan quickly, especially when several
  templates are active at once.

Goal:

- When runtime log lines list active templates, render each template name using
  the same color that template already has in the templates UI.

Example target:

- Current:
  - `Active templates updated live: LIGHT, MERCHANT, GOOD, PERFECT`
- Desired:
  - `LIGHT`, `MERCHANT`, `GOOD`, and `PERFECT` should each reuse their existing
    template color in the runtime scanner log/output.

Why this helps:

- Makes runtime updates easier to parse at a glance.
- Keeps visual language consistent between the template list and the live log.
- Reduces the chance of misreading a long active-template set during reroll
  setup changes.

Suggested behavior:

- Reuse the existing template-to-color mapping instead of introducing a second
  color definition source.
- Apply color only to the template names, not necessarily to commas or the full
  line prefix.
- Keep plain-text fallback safe in any output path that does not support rich
  text coloring.

Implementation note:

- Prefer using the same helper/constants already used by the templates list so
  log coloring stays in sync automatically if template colors ever change.

## 2. Make Recordings List Narrower And Keep Stats Cards Static In Size

Status: `[Open]`

Current issue:

- In the `Recordings` tab, the recordings list takes more horizontal space than
  needed.
- That leaves less room for run stats and detail cards.
- Stat/info cards can also visually change size as item count or text amount
  changes, which makes the layout feel jumpy.

Goal:

- Reduce the width of the recordings list panel.
- Give more horizontal room to the stats/details area.
- Keep stats/info cards at a stable size so the layout does not shift when
  recording content changes.

Desired UX:

- The recordings list should be compact but still comfortably readable.
- The stats/details section should have more room for long item lists and run
  information.
- Cards should already be expanded to a size that fits their maximum expected
  content footprint, or at least a stable upper-bound layout, so switching
  snapshots does not keep resizing the UI.

Why this helps:

- Makes the recordings tab easier to read during run review.
- Reduces distracting layout movement when item counts or snapshot content
  change.
- Gives more of the screen to the information the user is actually analyzing.

Suggested behavior:

- Narrow the left recordings list pane relative to the details pane.
- Review minimum/maximum/fixed widths for the list so it does not overgrow.
- Set stable sizing rules for key stat/info cards in the recordings view.
- Prefer a fixed or strongly bounded card layout for sections whose content
  changes often, especially items, stats, and summary panels.

Implementation note:

- The goal is visual stability, not clipping useful information. If some areas
  need scrolling or wrapping inside a fixed-size card, that is preferable to the
  whole layout constantly resizing.
