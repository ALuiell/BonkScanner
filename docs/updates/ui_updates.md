# UI Updates

Last reviewed: 2026-08-30

This file tracks open and partially completed UI-focused work. Implemented
entries retain their original problem/goal text as decision history.

Status legend:

- `[Implemented]` present in the current UI and covered by automated checks
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## 1. Preserve Template Colors In Runtime Active-Templates Log

Status: `[Implemented]`

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

Status: `[Implemented]`

Current implementation:

- the recordings library is a collapsible, resizable `QSplitter` drawer with
  bounded and persisted width;
- the detail side receives the remaining width;
- pooled/stable detail views avoid resizing the whole workspace as snapshot
  content changes.

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

## 3. Reconsider The Live Stats Segment Compare Card

Status: `[Implemented]`

Current thought:

- The `Live Stats` tab currently uses a compact `Segment Compare` card that
  mirrors the recordings viewer's snapshot-delta summary.
- This is useful for consistency, but it may not be the most valuable card for
  live gameplay because live review needs are different from post-run review.

Goal:

- Revisit whether the `Live Stats` summary row should keep `Segment Compare` or
  replace it with a more live-focused analytics card.

Theoretical replacement ideas:

- Track active improvement / powerup value over time.
- Estimate improvement duration impact by combining observed duration with
  relevant stats such as `Powerup Multiplier`.
- Show a compact live benefit summary instead of snapshot-to-snapshot item
  gains.
- Keep the card small and glanceable, similar to the current `Segment Compare`
  footprint.

Why this might help:

- `Segment Compare` is more naturally useful in recordings, where the user is
  deliberately inspecting chosen snapshots.
- During live gameplay, a card focused on current powerup/improvement value may
  be more actionable than showing the latest recorded snapshot delta.

Implementation note:

- `Live Stats` now uses a dedicated `Powerups` summary card in place of the
  live `Segment Compare` card.
- `Recordings` keeps the existing `Segment Compare` behavior for manual
  snapshot analysis.

## 4. Make The Live Stats Summary Row Responsive

Status: `[Open]`

Current issue:

- The top `Live Stats` row always gives equal width to `Run Summary`,
  `Stage Summary`, and `Powerups`, even though `Stage Summary` has a much wider
  content footprint.
- At the default window layout, the main Live Stats column is about 674 px wide
  and each summary card receives about 220 px. The populated Stage Summary needs
  roughly 321 px to show its four columns without clipping.
- Stage times, kill counts, and some of the colored item-rarity counters are
  therefore cut off without an ellipsis, wrap, tooltip, or horizontal scroll.
- The problem becomes severe in a narrower window, where even the column
  headers and stage numbers can be truncated.

Goal:

- Keep all Stage Summary values readable at the normal desktop window size.
- Let the summary row adapt cleanly when less width is available instead of
  squeezing every card equally.

Suggested behavior:

- When the three cards fit on one row, use content-aware proportions close to
  `1 : 2 : 1` for `Run Summary`, `Stage Summary`, and `Powerups`.
- Below the width where the cards' readable minimums fit, reflow Stage Summary
  onto a full-width second row rather than clipping its columns.
- Prefer a reusable responsive layout rule over a hard-coded one-off width for
  Stage Summary.

Acceptance checks:

- With all four stages populated and all four rarity counters visible, no
  header or value is clipped at the default window size.
- The same content remains usable in a narrower window through reflow or
  wrapping, without introducing horizontal page scrolling.
- The Items column and the existing outer-page vertical scrolling continue to
  behave consistently.

## 5. Prevent Long Roll-Stat Names From Being Clipped

Status: `[Open]`

Current issue:

- The responsive roll-stat grids used by `Chaos`, `Shrines`, and `Passives`
  currently allow cards as narrow as 160 px.
- At the normal Live Stats width, this selects a dense four-column layout, but
  a row such as `Projectile Speed  +31%` does not fully fit in that card.
- The last part of the stat name is visibly clipped. The same defect repeats in
  all three tabs because they share the same card layout and breakpoint rule.

Goal:

- Preserve the compact card grid while guaranteeing that normal game stat names
  and their values remain readable.

Suggested behavior:

- Raise the effective minimum card width to approximately 175-180 px, or derive
  it from the longest supported label plus the widest expected value.
- Prefer three readable columns at the default Live Stats width over four cards
  with clipped text.
- Keep the shared sizing rule centralized so `Chaos`, `Shrines`, and `Passives`
  cannot drift apart.

Acceptance checks:

- `Projectile Speed` and its value fit in all three tabs at the default window
  size.
- Resizing across column-count breakpoints does not create overlap, horizontal
  scrolling, or unstable card heights.

## 6. Release The Expanded-Control Space Outside The Stats Tab

Status: `[Open]`

Current issue:

- The `Expanded` switch is only relevant to the inner `Stats` tab and is hidden
  when another Live Stats detail tab is active.
- Its corner wrapper remains about 114 px wide even while the switch itself is
  hidden.
- That empty reserved area shortens the tab bar and pushes `Damage Sources` and
  `Build Progression` behind the tab-scroll arrows earlier than necessary.

Goal:

- Return the full header width to the detail-tab bar whenever the `Expanded`
  control is not visible.

Suggested behavior:

- Collapse or hide the entire corner wrapper together with the switch, or make
  the wrapper report a zero-width size hint while its control is hidden.
- Restore the wrapper at its normal size when the user returns to `Stats`.

Acceptance checks:

- Non-Stats tabs have no empty reserved block at the right side of the header.
- More tab labels remain directly visible before scroll arrows are required.
- The `Expanded` switch remains vertically centered and fully interactive on
  `Stats`.

## 7. Reduce Nested Scrolling Ambiguity In Live Stats

Status: `[Implemented]`

Current implementation:

- Live Stats uses a stable two-column page: the main analytics column and a
  bounded Items/Banishes column;
- large inventories scroll inside `LiveStatsItemsScroll` without increasing
  the outer page height or outer scrollbar range;
- detail tabs own their content scrolling so tab switches do not resize the
  surrounding page.

Current issue:

- A populated Live Stats page can show the outer page scrollbar and the Items
  panel's own vertical scrollbar at the same time.
- The two scrollbars are close together, and mouse-wheel behavior changes based
  on whether the pointer is over the page or the Items viewport.
- This is functional, but it adds visual noise and can make navigation feel
  inconsistent in a dense run.

Goal:

- Make it obvious whether the user is scrolling the whole Live Stats page or
  only the item list, without allowing a large inventory to resize the page.

Suggested direction:

- First evaluate whether the Items column can remain visually anchored while
  the main column scrolls.
- If nested scrolling remains necessary, strengthen the visual distinction and
  ensure wheel handoff at the start/end of the inner list feels predictable.
- Preserve the existing bounded Items viewport; the item list must not expand
  the full page as more items are collected.

Acceptance checks:

- Large item collections remain independently usable without changing the page
  height.
- Reaching the beginning or end of the Items list does not leave the user unsure
  how to continue scrolling the surrounding page.
- The layout remains stable with an empty inventory, a full inventory, and a
  populated banishes section.
