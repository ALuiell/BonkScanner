# Functional Updates

Date: 2026-05-29

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## 1. Find A Reliable Runtime Signal For True Menu / Non-Gameplay State

Status: `[Open]`

Current branch notes:

- Existing recording auto-stop logic can reliably detect full process exit, but not `Exit to Menu` from an active run.
- Current known run signals are not sufficient because they can remain frozen in memory after leaving the run.
- This needs a focused reverse pass before `Live Stats` recording auto-stop can be considered robust.

Reverse task:

- Find a reliable runtime signal that distinguishes active run gameplay from:
  - main menu
  - post-run / returned-to-menu state
- The signal must remain valid even if old run pointers, seed, stats, or items still remain in memory as a frozen snapshot.

Verified manual observations on build `2026-05-14`:

- Cold menu:
  - `map_seed = 0`
  - `current_map_ptr = 0`
  - `current_stage_ptr = 0`
  - `has_loaded_map = False`
- Active run:
  - `map_seed` is non-zero
  - `current_map_ptr` and `current_stage_ptr` are non-zero
  - `has_loaded_map = True`
- After `Exit to Menu` from a run:
  - `map_seed` stays stuck at the previous run value
  - `current_map_ptr` and `current_stage_ptr` stay stuck
  - `has_loaded_map = True`
  - `is_resetting = False`
  - player stats and items can also stay stuck as a frozen snapshot of the last run

What this means:

- Current known signals are not enough to reliably detect that the run has ended and the player has returned to menu.
- `ProcessNotFound` only covers full game exit, not `Exit to Menu`.

Primary goal:

- Find a stable memory or runtime-logic signal that reliably indicates one of:
  - the player is currently in main menu
  - an active run is no longer in progress
  - the game is currently not in gameplay state
  - post-run / menu state differs from active in-run state even when old run objects still remain in memory

Preferred candidate types:

- global game-state enum
- menu / open-screen state
- scene/state-machine current state
- pause/menu controller state, if it distinguishes:
  - paused during a run
  - main menu
- run/session active flag
- map/session ownership flag that resets on real run end even if old objects are still retained in memory

Weak signals that should not be used as the final solution without strong confirmation:

- `map_seed` alone
- `current_map_ptr` alone
- `current_stage_ptr` alone
- `has_loaded_map` alone
- `stats stopped changing for a while`
- `items are empty`
- a generic `pause` flag that does not distinguish paused gameplay from main menu

Required validation states:

- cold menu after fresh game launch
- active run gameplay
- paused run
- exited from run back to menu

Extra validation states if possible:

- during death / end-run transition
- after full process exit

Expected reverse report output:

- the found entity / field / method / offset / path
- what that state actually means
- how it behaves in:
  - menu
  - active run
  - paused run
  - post-run menu
- how reliable the signal is
- whether it is safe to use for:
  - recording auto-stop on menu
  - recording keep-alive during paused run
  - recording auto-split only on true new run

Ranking guidance if multiple candidates are found:

- best primary signal
- possible fallback signal
- unsafe / weak signals that should not be used

Implementation target after reverse:

- `process gone => stop`
- `true menu / non-gameplay state => stop after grace`
- `new run state => split recording`
- `paused active run => do not stop`

Why this matters:

- This is the missing piece for making `Live Stats` recording lifecycle trustworthy.
- Without a true gameplay/menu discriminator, auto-stop can silently fail and keep recording stale snapshots from a dead run context.

## 2. Twitch IRC Chat Bot Integration

Status: `[Open]`

### Concept & User Flow
- The streamer enables the integrated Twitch Chat Bot in BonkScanner UI.
- The streamer enters their Twitch channel name (e.g. `streamer_name`).
- The bot connects securely, joins the channel's chat, and listens to user commands (e.g., `!stats`, `!banishes`, `!items`), posting real-time responses sourced directly from the local gameplay memory state.

### Architecture & Connection
- **Local Embedded Bot:** Runs inside a dedicated background thread (`QThread` or `asyncio`) in BonkScanner. This allows instant access to local run tracker variables (`live_run_tracker`) with zero network latency.
- **Dedicated Bot Account:** The bot runs under a single central account created by the developer (e.g., `MegabonkBot`). The streamer does NOT need to provide their personal Twitch account token.
- **Secure Token Delivery:** At startup, the app makes a secure GET request to the developer's server API (`/api/bot-credentials`) to retrieve the bot's username and public `oauth:...` chat-scoped token.
- **Twitch IRC Connection:** The bot establishes a TCP socket connection to `irc.chat.twitch.tv:6667`, authenticates as the bot account, and executes `JOIN #streamer_name`.

### Commands Spec & Outputs
- `!stats` / `!bonkstats` -> Sourced from live stats memory. Example: `"Live Stats: Damage: 125, Speed: 1.4, Luck: 2.2, XP Gain: +30% | Moais: 3, Shady: 2"`
- `!banishes` -> Sourced from banish list state. Example: `"Banished items: Garlic, Shield, Fireball (3/10)"`
- `!items` / `!tracked` -> Sourced from tracked item counts. Example: `"Tracked items: Magnet (3), Luck Cup (1)"`
- `!scanner` -> Informational command. Example: `"This channel is using BonkScanner for live gameplay stats tracking! Try !stats or !banishes."`

### Spam Protection & Moderation
- **Spam Cooldown:** Adjustable global and per-command cooldown (default: 5 seconds) to prevent rate limit blocks.
- **Access Tiers:** Toggles in the UI to restrict commands to:
  - Everyone (default)
  - Moderators & VIPs only
  - Subscribers & Mods only
- **Command Customization:** Toggles to enable or disable individual commands.

