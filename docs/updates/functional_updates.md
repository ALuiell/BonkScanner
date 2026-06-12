# Functional Updates

Date: 2026-06-04

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Open Updates

### Twitch Commands

#### 1. Twitch Commons

Status: `[Partial]`

Goal:

- Expand the built-in Twitch bot with common stream commands and automatic chat announcements powered by `LiveRunTracker`.
- Keep the feature focused on local live-run data that is already needed by Twitch commands and the OBS overlay.
- Prefer configurable command names/messages where streamers may want different wording.

Implemented and archived on 2026-06-12:

- `!chests`
- `!disabled` highlighted disabled-items command
- Manual commands list command (`!bonkhelp` and aliases)
- Periodic commands-list auto announcer with a configurable interval
- `!items` / `!tracked` total count update
- `!presets`

Remaining open work:

- `!cap`
  - Track when the current run reaches important stat caps.
  - Difficulty cap should be user-configurable, for example `500%`.
  - The app should poll the normal live player stats and record the first run time when the configured difficulty value is reached.
  - XP gain cap should use a fixed target of `10x`.
  - The command should show whether each cap has been reached and, if so, at what run time.
  - Example output idea: `Difficulty cap 500% reached at 10:00; XP gain 10x not reached yet.`
  - Store the first reached timestamp only; do not keep updating it after the cap has already been recorded.

- `!records`
  - Add a streamer-managed records command.
  - The streamer should be able to configure multiple records, usually by character and optional build name.
  - Example output idea: `Dicehead / build name: 1,000,000; Fox: 900,000; Character 3: 850,000.`
  - Support short custom labels so the command can show either just a character name or a character plus build description.
  - Keep the output compact enough for Twitch chat limits.

Announcement ideas:

- End-of-run auto announcer
  - When the player finishes a run or dies, automatically post a full-run summary to Twitch chat.
  - Reuse the same run summary data used by existing run tracking and overlay systems where possible.
  - Include high-signal totals such as final time, map/stage progress, kills, score/damage-related stats if available, items, weapons, tomes, and future chest/cap information once implemented.
  - Make this optional in Twitch bot settings, because some streamers may prefer manual summaries only.

---

## Hotkey Improvement — Modifier-Aware Triggering

Status: `[Open]`

Date discussed: 2026-06-10

### Problem

Hotkeys (e.g. skip chest animation, run control hotkeys) fail to trigger when the user holds a game key simultaneously. The hotkey system currently matches exact key combinations, so `Shift + F9` is treated as a different event from `F9` alone and the hotkey does not fire.

### Proposed Solution — Game-Key Whitelist

Instead of registering a raw hotkey listener that requires an exact match, switch to a raw key-press listener that checks the full set of currently pressed keys on every keydown event.

Trigger logic:

```
if hotkey_key in pressed_keys:
    modifiers = pressed_keys - {hotkey_key}
    if modifiers ⊆ GAME_KEYS:
        → trigger action
    else:
        → ignore (non-game modifier present, e.g. Ctrl, Alt, Win)
```

### GAME_KEYS Whitelist

The whitelist covers keys a player commonly holds during active gameplay:

| Category       | Keys |
|----------------|------|
| Movement       | W, A, S, D, Arrow keys |
| Actions        | Q, E, R, F, G, T, Z, X, C, V, B |
| Jump / Sprint  | Space, Left Shift |
| Slots / Skills | 1 – 9, 0 |
| UI / Map       | Tab |

**Excluded** (treated as non-game modifiers — hotkey will NOT fire):
- Right Shift, Ctrl (right), Alt, Win key — these can be part of system shortcuts.
- Left Ctrl is debatable; currently excluded to avoid conflicts with system shortcuts like Ctrl+C.

### Why Whitelist Instead of "Any + Hotkey"

- `Ctrl + F9`, `Alt + F9` may be system or browser shortcuts — should not be hijacked.
- Whitelist gives precise control with minimal user-visible side effects.
- GAME_KEYS should be configurable in settings so users can adapt it to custom game keybindings.

### Additional Considerations

- **Debounce**: Ensure one physical key press produces exactly one trigger (no repeat-key spam on hold).
- **Configurability**: Expose GAME_KEYS as a user-editable list in config/settings for players with non-default bindings.
