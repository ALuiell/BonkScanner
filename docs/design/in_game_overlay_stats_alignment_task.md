# In-Game Overlay Stats Alignment Task

## Goal

Bring the `stats` widget alignment used by the OBS overlay into the in-game overlay so stat values start from the same visual column instead of shifting per row.

## OBS Overlay: current alignment implementation

### Data preparation

- File: `src/overlay_state.py`
- Function: `_snapshot_stats()`

OBS `stats` rows are prepared as an ordered list of objects:

- `label`
- `value`

The row order follows the widget's `selected_stats` config and is capped by `max_rows`.

### Rendering and alignment

- File: `src/media/overlay/overlay.js`
- Function: `renderStats()`

Current alignment logic:

1. Take the visible `rows`.
2. Compute `maxLen` from the longest `row.label`.
3. Convert it to pixels with `labelWidth = Math.max(60, maxLen * 8.8)`.
4. Pass that width into CSS via `--stat-label-width`.
5. Render each row as separate `label` and `value` elements.

Important detail: the width is calculated from the label text length, not from the value length.

### CSS that makes the alignment work

- File: `src/media/overlay/overlay.css`

Alignment is created by layout rules, not by padded strings:

- `.stats-list` uses a grid container.
- `.stat-row` is a flex row.
- `.stat-row span` gets a fixed flex-basis from `--stat-label-width`.
- `.stat-row strong` holds the value and starts after the same reserved label width on every row.

Result: values visually line up in one column even when stat names have different lengths.

## In-Game Overlay: current implementation

### Update path

- File: `src/gui_in_game_overlay.py`
- Method: `_overlay_fast_tick()`

The in-game overlay reads the selected stats config and sends it to `build_stats_overlay_html()`.

### Current rendering

- File: `src/gui_in_game_overlay_render.py`
- Function: `build_stats_overlay_html()`

Current output is a simple list of HTML lines:

- abbreviated label + `: `
- colored value
- rows joined with `<br>`

This widget already has useful stat-specific behavior:

- shared abbreviations through `abbreviate_stat_label()`
- difficulty cap suffix and red warning color
- XP gain cap suffix and red warning color

But it does **not** have OBS-style alignment logic:

- no per-render max label width calculation
- no separate fixed-width label column
- no shared value start column

### Widget container behavior

- File: `src/gui_in_game_overlay_window.py`
- Class: `DraggableOverlayWidget`

The widget content is displayed through a generic `QLabel` with rich text. That means the OBS browser CSS cannot be reused directly, but the same alignment idea can be reproduced in the generated HTML.

## Gap between OBS and in-game

OBS `stats` alignment is structural:

- measure longest displayed label
- reserve one fixed label column width
- render values in a second column

In-game `stats` formatting is linear:

- render `Label: Value`
- let each row width depend on the label text

So the in-game widget currently preserves stat formatting and coloring, but not the alignment mechanic.

## What should be transferred

Transfer the alignment approach, not the browser-specific implementation:

- keep the in-game widget's current stat abbreviations
- keep the current cap suffix and cap-color logic
- add a fixed label column width calculated from the longest displayed in-game stat label

The width should be based on the final displayed label text in the in-game overlay, meaning the abbreviated label, not the raw stat key. Otherwise the widget will reserve space for labels that are never shown.

## Concrete change list

1. Add a shared helper for stats row preparation in Python.
   Suggested responsibility:
   - accept `snapshot` + `selected_stats`
   - build ordered rows
   - expose both raw label and displayed label
   - expose rendered value text

2. Add a shared helper for alignment width calculation.
   Suggested output:
   - `max_display_label_len`
   - or directly `label_width_px`

3. Update `build_stats_overlay_html()` in `src/gui_in_game_overlay_render.py`.
   It should stop emitting plain `Label: Value` lines and instead render two-column rows, for example:
   - label element with fixed width / inline-block width
   - value element after it

4. Base in-game alignment on displayed abbreviated labels.
   This keeps the widget compact and matches what the user actually sees.

5. Keep current in-game stat-specific rules untouched.
   Preserve:
   - difficulty cap suffix
   - XP gain cap suffix
   - red cap warning color
   - cyan default value color

6. Decide whether OBS should also reuse the same Python width metadata.
   Two valid options:
   - minimal change: only port the logic to in-game
   - cleaner reuse: prepare label-width metadata once in Python and let both overlays consume it

7. Add tests for the new in-game alignment output.
   At minimum verify:
   - rows are rendered as two-column HTML, not plain `Label: Value`
   - width is derived from the longest displayed abbreviated label
   - existing cap suffix/color rules still appear

## Recommended implementation scope

Recommended scope for the first pass:

- do **not** rewrite OBS rendering
- do **not** remove current in-game abbreviations
- do **not** change widget config format
- only extract the width/row-building logic into reusable Python helpers and apply it to the in-game renderer

This gives parity of behavior where it matters and keeps the risk small.

## Acceptance criteria

- In-game `stats` values start from one visually aligned column.
- Alignment width changes automatically when the selected stat set changes.
- Longest visible abbreviated stat label determines the reserved label width.
- Existing difficulty/XP cap formatting in the in-game overlay still works.
- Existing OBS `stats` behavior does not regress.
