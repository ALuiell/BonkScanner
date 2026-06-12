# Functional Updates

Date: 2026-06-04

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
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

Status: `[Implemented]`

Date discussed: 2026-06-10
Date implemented: 2026-06-12

### Problem

Hotkeys (e.g. skip chest animation, run control hotkeys) fail to trigger when the user holds a game key simultaneously. The hotkey system currently matches exact key combinations, so `Shift + F9` is treated as a different event from `F9` alone and the hotkey does not fire.

### Implemented Solution — Game-Key Whitelist

The app now uses a raw keyboard hook and tracks pressed physical scan codes. A
hotkey triggers only on a new keydown of its final configured key, so keyboard
auto-repeat and later presses of held game keys do not retrigger the action.

Trigger logic:

```
if event is a new keydown of the hotkey trigger key:
    if configured hotkey keys are pressed:
        extra_keys = pressed_keys - configured_hotkey_keys
        if no extra_keys:
            trigger globally
        elif game window is active and extra_keys ⊆ GAME_KEYS:
            trigger
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

**Excluded by default** (treated as non-game modifiers — a plain hotkey will NOT fire):
- Right Shift, Ctrl (right), Alt, Win key — these can be part of system shortcuts.
- Left Ctrl is excluded to avoid conflicts with system shortcuts like Ctrl+C.

Configured combinations remain supported. For example, when the configured
hotkey is `Ctrl+F9`, Ctrl is a required part of that hotkey rather than an extra
blocked key. Multi-step hotkeys containing a comma continue to use the standard
`keyboard.add_hotkey()` implementation.

### Why Whitelist Instead of "Any + Hotkey"

- `Ctrl + F9`, `Alt + F9` may be system or browser shortcuts — should not be hijacked.
- Whitelist gives precise control with minimal user-visible side effects.
- GAME_KEYS is configurable in Settings as `Allowed Held Game Keys` so users can adapt it to custom game keybindings.

### Implemented Safeguards

- One physical trigger-key press produces one action until that key is released.
- Left and right modifiers are distinguished through scan codes.
- Extra whitelisted keys are accepted only while the game window is active.
- Exact configured hotkeys continue to work globally.
- Reconfiguring or closing the app removes only BonkScanner's owned hook rather than all hooks registered through the `keyboard` module.
- Callbacks remain short and forward GUI work through `after(0, ...)`.
