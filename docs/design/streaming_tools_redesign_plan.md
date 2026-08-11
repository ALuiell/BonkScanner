# Streaming Tools redesign — implementation plan

Three tabs — **OBS Overlay**, **Twitch Bot**, **In-Game Overlay** — rebuilt on one
shared skeleton. Source mock: `ui_mockups/streaming_tools/streaming_tools_proposal.html`.
Palette and control geometry: `ui_mockups/bonkscanner_redesign.qss`.

> **Status: implemented.** All three tabs are rebuilt. What changed *during*
> implementation, beyond this plan:
>
> - `SettingsCard` became a fourth shared control — `QGroupBox` cannot carry a
>   header with a step number, a sub-line and an action button.
> - The in-game hero badge grew a fifth reading, `LAYOUT MODE`, once layout mode
>   stopped having a button of its own to show it.
> - Three real bugs were caught by existing tests rather than by review:
>   `bind` connecting `clicked` on a `RunToggle`; `SettingsCard` showing a
>   parentless label, which Qt turns into a top-level window (eight flashes);
>   and `_is_in_game_overlay_tab_active` put on the layout router, which the
>   component cannot reach.
> - One test was written vacuous and had to be fixed: the tile's repaint case
>   compared whole grabs, and the switch inside repaints on its own, so it
>   passed with the repolish deleted.

This document records what was **decided**, and — more importantly — where the
mock and the code disagree. The mock was drawn as one screen with an internal
context switcher; we keep three separate tabs. Every place the mock invented a
control, a state, or a signal that does not exist is listed under *Deviations*,
because those are the places an implementation would otherwise silently invent
behaviour.

---

## 0. Shared decisions

- **Three top-level tabs.** The mock's `contextbar` (`OBS / Twitch / In-game`
  segmented switcher) is **not** implemented; the tab bar already does that job.
- **Per-tab layout:** hero → card 1 (setup) → card 2 (module tiles) → optional
  card 3 (behaviour), with a side column holding preview and tip.
- **No setup checklist** on any tab (mock card removed entirely — see §5).
- **Preview cards have no buttons** on any tab.

### Shared components to build

| component | where | notes |
|---|---|---|
| `TabHero` | new, `src/ui/` | icon, title, 4-state badge, subtitle, auto-switch, run toggle |
| `RunToggle(SegmentedToggle)` | new, `src/ui/` | ▶ Start / ■ Stop, drop-in for the three toggle buttons |
| `ModuleTile` | new, `src/ui/` | name + mini-switch, tinted when enabled |

`LabeledSwitch` (`ui/shared.py:37`) and `SegmentedToggle`
(`ui/segmented_toggle.py:41`) already exist and are reused as-is.

---

## 1. Hero (block 0)

Replaces the first group box on each tab:

| tab | current group | file |
|---|---|---|
| OBS | `Overlay Server` | `gui_overlay.py:183-220` |
| Twitch | `Bot Control` | `ui/tabs/twitch/panel.py:214-250` |
| In-game | `General Settings` | `gui_in_game_overlay_settings.py:268-302` |

### Icons

The mock's three SVGs (`streaming_tools_proposal.html:722-724`) are saved into
`src/media/` and loaded with `resource_path` / `_apply_button_icon`
(`ui/shared.py:236`, `ui/shared.py:333`).

> **Trap.** The mock's paths use `stroke="currentColor"`. Qt does not resolve
> `currentColor` — the stroke must be written as `#38BDF8` in each file, or the
> glyph renders black on black.

### Status badge — four states

| state | badge | colour role |
|---|---|---|
| running / connected | `LIVE` / `CONNECTED` / `RUNNING` | ok |
| in transition | `CONNECTING` / `VALIDATING` / `AUTHORIZING` | warn |
| error | `PORT ERROR` / `AUTH FAILED` / `ERROR` | danger |
| stopped | `STOPPED` / `NOT CONNECTED` | off |

The badge stays visible in every state. **Error detail text replaces the hero
subtitle** while an error is showing; the badge itself stays a short label.

Current sources:

- OBS — `refresh_overlay_ui` (`gui_overlay.py:808-815`): `Live` / `Port Error
  (message)` / `Stopped`.
- In-game — `update_in_game_overlay_status_ui`
  (`gui_in_game_overlay_settings.py:416-432`).
- Twitch — `show_bot_status` (`panel.py:437-449`), five branches.

### Twitch: account status and bot status merge into one badge

The two are **sequential, not concurrent**: `start_bot` refuses without a token
(`app/twitch_session.py:206`) and the Connect button is hidden once connected
(`panel.py:413`). One badge carries the whole lifecycle:

```
NOT CONNECTED → AUTHORIZING → VALIDATING → STOPPED → CONNECTING → CONNECTED
                                    ↘ AUTH FAILED       ↘ ERROR
```

The account field in card 1 keeps a plain `Authorized` suffix.

> **Trap 1 — periodic validation overwrites the bot status.**
> `_on_validation_finished` calls `show_connected(username)` on every successful
> validation (`app/twitch_session.py:351`) and the validation timer keeps
> running while the bot is up (`:353`, `:364`). Rule: **while the bot is active,
> auth states do not paint the badge** — they only update the account field.
>
> **Trap 2 — `bot_status_text()` is parsed, not just displayed.**
> `on_bot_finished` decides whether to write `Stopped` by reading the label back
> and searching for `"error"` (`app/twitch_session.py:248`). The panel must keep
> the bot status in **its own field** and keep returning that from
> `bot_status_text()`, independent of what the merged badge currently renders.

### Run toggle

`RunToggle` subclasses `SegmentedToggle` with fixed captions `▶ Start` /
`■ Stop` on all three tabs — the hero title says *what* is being started.

State arrives through `setText`, exactly as `ScannerToggle` already does
(`ui/scanner_toggle.py:73-77`), so **no caller changes**: `refresh_overlay_ui`,
`update_in_game_overlay_status_ui` and `show_bot_running` / `show_bot_stopped`
keep writing their captions. `_set_widget_style_role` renaming `objectName` is
already survivable — the frame is selected by the `[segmentedToggle="true"]`
property (`ui/scanner_toggle.py:31-36`), and the QSS rules exist
(`bonkscanner_redesign.qss:403-448`).

> **Trap.** A caption-driven control fails silently: a typo in the per-tab
> caption constants leaves the toggle stuck on Start with nothing raising.
> Each tab's caption pair needs a test, in the shape of `test_scanner_toggle`.

### In-game: `Running` must read the window, not the config

`update_in_game_overlay_status_ui` currently reads
`config.IN_GAME_OVERLAY["enabled"]` (`gui_in_game_overlay_settings.py:420`). If
the transparent window failed to appear the badge still says Running. Read real
window state instead.

### In-game: one handler writes hero and tiles together

`_on_igo_settings_changed` (`gui_in_game_overlay.py:521-532`) rewrites
`auto_start` *and* all seven widget toggles on any change. Blocks 0 and 2 for
this tab must be done in one pass, or the handler split first.

---

## 2. Card 1 — Setup

### OBS — "Browser source"

- Segmented **two** ways: `Full overlay` / `Single widget`.
- In `Single widget` mode a combo box picks the widget — the existing
  `overlay_widget_url_combo` (`gui_overlay.py:304-309`) minus its
  `Layout Editor Mode` entry.
- `Layout editor` becomes a **button in the card header** (it is just the URL
  with `?edit=true`, `gui_overlay.py:1178-1179`, not a mode).
- **Port** moves here from the hero (`gui_overlay.py:206`). Pure reparent —
  `save_overlay_settings_from_ui` reads the widget by name (`:709`).
- Accepted loss: the full URL and the widget URL are no longer both visible at
  once.

### Twitch — "Account & channel"

Merges two group boxes into one card: `Twitch Account` (`panel.py:174-212`) and
`Bot Settings` (`panel.py:252-279`). All four fields move 1:1; `read_settings`
(`panel.py:382-396`) is unchanged.

- `Connect` / `Disconnect` stay a **pair of buttons** with swapped visibility
  (`panel.py:413-421`). If Connect turns out to be hard to find in the card
  header, the fallback is: while unauthorized, show a single large Connect in
  the card body and reveal the fields after authorization — every other field
  is meaningless without a token anyway.
- Cooldowns are two `QSpinBox` side by side (the app's spin boxes carry custom
  arrows); the mock's single shared frame is not reproduced.

### In-game — "Layout & activation"

- **No segmented control.** Layout mode is entered by hotkey only (variant B).
- **Edit hotkey — editable field**, duplicated with the Settings dialog (§7).
- **Target window** with a detection indicator, from `_find_game_window`
  (`gui_in_game_overlay.py:179`).

> **Trap.** `_find_game_window` currently only runs inside the overlay's fast
> tick. The tab field needs its own slow poll (1–2 s, only while the tab is
> visible) or it freezes on whatever was true when the tab was opened.

Removed by variant B: `igo_edit_btn` (`gui_in_game_overlay_settings.py:299-302`)
and the caption/inline-style swap in `_toggle_igo_edit_mode`
(`gui_in_game_overlay.py:541-548`). `_toggle_igo_edit_mode` itself stays — it is
the hotkey's target (`gui_in_game_overlay.py:215`).

Edit mode remains visible and exitable **from the overlay itself**: the window
shows a green `Save Layout & Exit` button in edit mode
(`gui_in_game_overlay_window.py:479`), and `Esc`
(`gui_in_game_overlay_window.py:553-557`) and the hotkey both exit.

> **Cleanup while here.** `_on_save_clicked` reaches the mixin through `hasattr`
> (`gui_in_game_overlay_window.py:561`) — the pattern this codebase has already
> been bitten by (see the comment at `ui/dialogs/__init__.py:1175-1179`).
> Replace with a direct call.

---

## 3. Card 2 — Module tiles

Replaces three checkbox grids:

| tab | current | count | grid |
|---|---|---|---|
| OBS | `Visible Widgets` (`gui_overlay.py:252-282`) | 6 | 3 cols |
| Twitch | `Command Configuration` (`panel.py:281-309`) | **16** | **3 cols** |
| In-game | `Active Widgets` (`gui_in_game_overlay_settings.py:304-373`) | **7** | 3 cols |

**Tile = name + mini-switch only.** No icon badge, no description — both are
dropped from the mock. The tile is tinted when enabled (`.module.enabled`:
border `--acc2`, background `rgba(47,111,176,.12)`), which is the whole point
over a checkbox: enabled state reads as a block of colour across 16 items.

The `Widget settings` / `Command settings` button stays in the card header and
keeps opening the existing modal dialog (§6).

### Deviations from the mock

- The mock shows 6 tiles per tab. Real counts are 6 / 16 / 7.
- The mock merged In-game `Stats` and `Event timer` into one tile. They are two
  independent config keys (`gui_in_game_overlay.py:529-530`) — **keep 7 tiles**.

> **Trap — double toggle.** The whole tile toggles
> (`streaming_tools_proposal.html:988`). A clickable switch inside a clickable
> tile fires twice and snaps back, which reads as "the control does not work".
> The switch must be `WA_TransparentForMouseEvents`; the tile is the only
> event source.

> **Twitch exceptions.** `bonkhelp` raises the alias dialog before saving and
> must not be wired to the shared handler (`panel.py:373-375`); `disabled` has
> its own section in the command settings dialog
> (`ui/dialogs/__init__.py:1431`). Both stay in the same grid.

### Future: `?` hover with descriptions

Not built now. When it is: descriptions already exist as **prose in three
language files** (`docs/help/help_eng.txt`, `_ru`, `_ukr`) read by `HelpDialog`
(`ui/dialogs/__init__.py:794`). They would need extraction into an `id → text`
map, and there are gaps: `!luck` is undocumented (15 of 16 commands), In-game
`Stats` and `Event Timer` are undocumented (5 of 7, `help_eng.txt:134-139`), and
OBS widgets have no per-widget text at all.

---

## 4. Card 3 — Behaviour

Only where there is something real to put in it.

| tab | card 3 | contents |
|---|---|---|
| Twitch | **yes** | `stage_announcements` (`panel.py:331`), `commands_announcements` (`panel.py:337`) — 1:1 |
| OBS | **yes** | one option: the scanner reminder, full width |
| In-game | **no** | both mock options rejected |

### Rejected mock options

- **OBS "Remember last canvas"** — no such flag, and canvas size is already
  persisted unconditionally by the browser editor
  (`infra/overlay_server.py:287-300`). Off would mean "reset the canvas on every
  restart", which nobody wants.
- **In-game "Game-only visibility"** — behaviour exists but is unconditional
  (`gui_in_game_overlay.py:236-242`). Making it optional is new functionality;
  deferred.
- **In-game "Clamp to game bounds"** — unconditional
  (`gui_in_game_overlay_window.py:102-111`). Turning it off lets a widget be
  dragged out of reach.

### OBS scanner reminder — duplicated on purpose

`SHOW_OBS_REMINDER_ON_START_SCANNER` (`app/config.py:888`) is today edited only
in the Settings dialog (`ui/dialogs/__init__.py:993-997`). It gains a second
editor in the OBS tab. Both use the **same label text**.

Three of the four sync directions are already safe: `SettingsDialog` is modal
(`ui/dialogs/__init__.py:952`) and constructed fresh per open
(`gui_app.py:609`), and its checkbox reads config in the constructor. The one
gap to build: **after the dialog saves, the tab checkbox must re-read.**

---

## 5. Preview (block 4) — live, not editable

Decision: the preview reads **real** coordinates and is **not** draggable.
Positions are already editable in two places, and a third editor over the same
geometry with different clamping rules would drift silently:

- OBS — in the browser via `?edit=true`, POSTing to `/api/save-widget-positions`
  (`media/overlay/overlay.js:528`, `infra/overlay_server.py:233-270`).
- In-game — in the transparent window (`gui_in_game_overlay_window.py:89-100`).

At roughly 1:6 scale a preview drag would carry ±6 real pixels per screen pixel,
and true widget sizes are content-dependent anyway
(`gui_in_game_overlay_window.py:113-117`).

**No buttons under the preview** on any tab. (This also removes the mock's
`Reset positions`, which does not exist in code — only `_reset_stats_to_default`
and `_reset_overlay_stats_to_default`, both about *stat selection*.)

### OBS preview

- Aspect ratio follows the **real** canvas (`canvas_width` / `canvas_height`),
  not the mock's hardcoded 16:9 (`streaming_tools_proposal.html:475`).
- **`LIVE` badge means "a browser source is polling the server"** — the one
  genuine signal salvaged from the deleted checklist. Needs a last-request
  timestamp in `_serve_state` (`infra/overlay_server.py:324`) plus a getter;
  the server currently records nothing (`log_message` is silenced, `:321`).
  `overlay.js` polls every `poll_ms` (default 500), so "a request within the
  last couple of seconds" is a clean signal. It cannot distinguish OBS from an
  ordinary browser tab — the label must say *browser source*, not *OBS*.
- Layout branch: if **no** widget has `x`/`y`, the browser lays them out by
  flow, not absolutely (`media/overlay/overlay.js:317-325`), and the preview
  cannot reproduce that. In that case show a line — "widgets are auto-arranged,
  open the layout editor to place them" — instead of a fake grid.

### In-game preview

Frame of reference is the game client rect, known only while the game runs
(`gui_in_game_overlay.py:176-204`). Without it, fall back to the screen, as the
overlay itself already does, and say so in the caption. Refresh on the `moved`
signal (`gui_in_game_overlay_window.py:99`) and on tab show; no revision
counter needed, it is all in-process.

### Twitch preview

Stays a chat-message mock, but rendered from the **real** templates in
`TWITCH_BOT.templates` (`ui/dialogs/__init__.py:1222`) rather than a hardcoded
string.

---

## 6. Setup checklist (block 5) — removed

All nine mock entries were checked. Five duplicate what is already on screen
(server status, twitch account, bot connection, target channel, game window);
two can never fail and would be permanently green — In-game "Overlay permission"
(the window is created unconditionally,
`gui_in_game_overlay_window.py:399-405`) and "Layout saved" (coordinates always
exist, `app/config.py:112-115`); one is an echo of a text field.

The single real signal — "is a browser source actually pulling?" — moves to the
OBS preview badge (§5).

The card is **not built** on any tab.

## 7. Tip (block 6)

| tab | tip |
|---|---|
| OBS | yes — the existing info card (`gui_overlay.py:224-250`) restyled |
| In-game | yes — the existing info card (`gui_in_game_overlay_settings.py:378-410`) restyled |
| Twitch | **none** |

Twitch gets no tip: the mock's text points at a `Send test message` button, and
no such feature exists anywhere in the project.

Both existing cards are drawn with inline styles in colours outside the redesign
palette (`#111A2E`, `#1D4ED8`, `#3B82F6`, `#ffd23f`, and `pt` font sizes inside
label HTML). Moving them to `.tip` is also a move of styling out of Python and
into QSS.

> **Trap — the In-game tip is now load-bearing.** Under variant B it is the only
> place on screen that says how to enter layout mode, and it interpolates the
> hotkey from config **once, at tab construction**
> (`gui_in_game_overlay_settings.py:394`). That was safe while the hotkey could
> only be changed by hand-editing `config.json`. With an editable field it is
> not: change F9 to F10 and the only instruction on screen still says F9. The
> tip must be re-rendered whenever the hotkey changes — from the field and from
> the Settings dialog.

---

## 8. Cross-cutting: the Settings-dialog refresh port

Two values are now edited in two places each:

- `IN_GAME_OVERLAY_EDIT_HOTKEY` — In-game card 1 **and** the Settings dialog.
- `SHOW_OBS_REMINDER_ON_START_SCANNER` — OBS card 3 **and** the Settings dialog.

Both need the same thing: after `SettingsDialog.save()` writes config
(`ui/dialogs/__init__.py:1141-1171`), the tabs must re-read. The hook point is
where `setup_hotkeys()` is already called (`:1173`).

> **Trap.** That call sits behind a `hasattr` guard, and the comment right below
> it (`:1175-1179`) records what happened last time: when a class left the MRO
> the guard went quietly false and the timeline stopped refreshing after a save
> — no exception, green suite. The refresh must be a **named port**, not a
> `hasattr` probe.

The hotkey path itself is already re-entrant: `setup_hotkeys` tears down the
previous manager before rebuilding (`gui_run_control.py:115-133`).

---

## 9. Widget settings dialogs stay modal

All three settings surfaces stay as modal dialogs opened from the card 2 header.
Not moved into tabs, and the rule is applied uniformly.

| dialog | size | contents |
|---|---|---|
| `gui_overlay.py:351` | 700×760, min 640×680 | own `QTabWidget`: Basic / Advanced |
| `gui_in_game_overlay_settings.py:29` | 700×760, min 640×680 | own `QTabWidget`: Basic / Advanced |
| `ui/dialogs/__init__.py:1194` | 700×760, min 640×680 | own `QTabWidget`: Templates / Advanced / Announcers |

All three already contain **their own tab widgets**; nesting them inside a tab
would make three levels of navigation. They also demand 680px of content height,
while the main window's minimum is 1120×710 (`gui_app.py:71`) — inside a tab
that means a scroll area inside a scroll area. The mock itself implies modal:
its card 2 header already carries `Widget settings` / `Command settings`
buttons.

---

## 10. New functionality (as opposed to restyling)

Everything here is a behaviour change, not a redesign, and is listed separately
so it can be dropped without touching the layout work:

1. Editable **edit-mode hotkey** for the In-game overlay (today only editable by
   hand in `config.json`).
2. **Browser-source liveness** tracking in the overlay server (last-request
   timestamp + getter), for the OBS preview badge.
3. **Scanner-reminder checkbox** mirrored into the OBS tab.
4. **In-game running state** read from the real window instead of a config flag.
5. Twitch preview rendered from real templates.

## 11. Explicitly not doing

- The mock's `contextbar` (three tabs stay three tabs).
- Setup checklist card.
- Preview buttons, including `Reset positions`.
- Draggable preview.
- Tile icons and descriptions.
- `?` hover help on tiles (deferred; source data is incomplete — §3).
- In-game "Game-only visibility" / "Clamp to game bounds" toggles.
- OBS "Remember last canvas".
- Twitch tip card.
- Moving widget settings out of modal dialogs.
