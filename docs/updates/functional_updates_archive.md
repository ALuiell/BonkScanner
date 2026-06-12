# Functional Updates Archive

This file archives completed, shelved, or old functional updates, helping keep `functional_updates.md` focused on active tasks.

---

## Part 0: Completed / Done Items (Archived 2026-06-12)

### 0. Twitch Commons Follow-Up Commands

Status: `[Done]`

- The built-in Twitch bot now includes the originally planned follow-up utility commands for chests, disabled items, reroller presets, and command discovery.
- The active `functional_updates.md` file now keeps only the still-open Twitch bot work.

Goal:

- Expand the built-in Twitch bot with common stream commands and chat-facing helpers powered by `LiveRunTracker`, while keeping responses compact and configurable.

Implemented scope:

- `!chests` / `!chest`
  - `LiveRunTracker` stores chest progress by stage plus run totals.
  - The Twitch command returns compact per-stage output and overall totals.
  - Free chest openings are included in the chat response.

- `!disabled`
  - The app reads real disabled-item state from memory once a run exposes the data.
  - Streamers can configure a highlighted subset of important disabled items.
  - The Twitch response stays compact by showing only the highlighted items that are currently disabled.

- Manual commands list command
  - Implemented as `!bonkhelp` with aliases `!bonkcmds`, `!bonkcommands`, and `!bhelp`.
  - The response lists only currently enabled commands.

- `!items` / `!tracked` total count update
  - `Items ({count})` now counts duplicate stacks instead of only distinct item names.
  - Example: `Anvil x2` plus `Soul Harvester x2` contributes `4` to the total count.

- `!presets` / `!preset`
  - The command reports active reroller presets in both `templates` mode and `scores` mode.
  - Templates mode shows the active template names and condensed conditions.
  - Scores mode shows active tiers and score weights.

Code anchors:

- `twitch_bot.py`
- `live_run_tracker.py`
- `player_stats.py`
- `gui_dialogs.py`
- `gui_twitch.py`
- `tests/test_twitch_bot.py`
- `tests/test_live_run_tracker.py`
- `tests/test_player_stats.py`

---

### 1. Hotkey Improvement - Modifier-Aware Triggering

Status: `[Done]`

- Hotkeys now tolerate configured held gameplay keys such as `W` or `Left Shift` while still rejecting unrelated modifiers for plain hotkeys.
- The active `functional_updates.md` file no longer needs to keep this completed implementation note.

Goal:

- Fix hotkeys that stopped firing when the user held a gameplay key at the same time as the hotkey trigger.

Implemented scope:

- Raw keyboard hook with pressed scan-code tracking.
- One-trigger-per-physical-press behavior for the hotkey trigger key.
- Configurable `GAME_KEYS` whitelist exposed in Settings as `Allowed Held Game Keys`.
- Extra whitelisted keys are accepted only while the game window is active.
- Exact configured hotkeys continue to work globally.
- Left and right modifiers are distinguished through scan codes.
- Only BonkScanner's own hook is removed during reconfiguration or shutdown.

Code anchors:

- `hotkey_manager.py`
- `gui_run_control.py`
- `gui_dialogs.py`
- `config.py`
- `tests/test_hotkey_manager.py`
- `tests/test_gui_run_control.py`

---

## Part 0A: Archived & Shelved Planning Items (Archived 2026-06-12)

### 0. Twitch Commons End-Of-Run Auto Announcer

Status: `[Archived]`

Goal:

- When the player finishes a run or dies, automatically post a full-run summary to Twitch chat.
- Reuse the same run summary data used by existing run tracking and overlay systems where possible.
- Include high-signal totals such as final time, map or stage progress, kills, score or damage-related stats, items, weapons, tomes, and future chest or cap information once implemented.
- Keep the feature optional in Twitch bot settings, because some streamers may prefer manual summaries only.

Archive note:

- Moved out of the active `functional_updates.md` list to keep current Twitch bot work focused on still-open command tasks.

---

## Part 1: Completed / Done Items (Archived 2026-06-02)

### 0. Find A Reliable Runtime Signal For True Menu / Non-Gameplay State

Status: `[Done]`

- Implemented in [game_data.py](file:///f:/Python/MegabonkReroll/game_data.py) and [gui_player_stats.py](file:///f:/Python/MegabonkReroll/gui_player_stats.py).
- Resolves the issue where stats recording auto-stop could silently fail and keep recording stale snapshots from a dead run context.

Goal:

- Find a stable memory or runtime-logic signal that reliably indicates whether the player is currently in main menu / non-gameplay state, and use it to safely control the recording lifecycle.

Implemented scope:

- Reading `RuntimeGameMode` state directly from game memory (`GameManager`, `MyTime`, `LoadingScreen`, `PlayerMovement`, `MusicController`).
- Auto-stop recording on game over / main menu return, while keeping the recording armed to auto-start the next run.
- Prevent snapshot capturing while paused in game, while keeping the recording file open.

---

## Part 2: Completed / Done Items (Archived 2026-05-23)

### 0. Twitch IRC Chat Bot Integration

Status: `[Done]`

- The integrated Twitch Chat Bot is implemented in BonkScanner UI.
- Twitch account connection, IRC join flow, and chat command handling are already in place.

Goal:

- Let the streamer authenticate with their own Twitch account and run a local embedded chat bot that responds with live BonkScanner gameplay data in channel chat.

Implemented scope:

- UI support for enabling and configuring the Twitch bot
- Twitch auth/connect flow for the streamer's account
- IRC connection and channel join
- Chat commands such as `!stats`, `!banishes`, `!items`, and `!scanner`
- Basic cooldown/moderation-oriented behavior for chat command usage

Why this helps:

- Stream chat can query live run state directly from the local scanner.
- The feature works without any central shared bot service.

---

### 1. Hotkey for Particles Opacity

Status: `[Done]`

- Native hook export and loader support for `ToggleParticlesOpacity` are implemented.
- The optional config knobs for custom `ON/OFF` target values are still not added.

Goal:

- Add a hotkey for `Settings -> Effects -> Particles Opacity`.
- Intended behavior:
  - `OFF` -> set value to `0` if the game safely supports it
  - `ON` -> set value to `0.5` / `50%`
