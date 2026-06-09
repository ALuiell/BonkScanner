# Functional Updates

Date: 2026-06-04

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Open Updates

1. `[Partial]` Add Twitch bot `!powerups` command

   Implemented in the bot and covered by tests; still needs live Twitch/game
   verification. The command reports effective powerup duration using the current
   Powerup Multiplier stat (`PM`):

   - Rage, Shield, Coin, and Speed: `15 sec * PM`
   - Clock: `12 sec * PM`

### Twitch Commands

#### 1. Twitch Commons

Status: `[Open]`

Goal:

- Expand the built-in Twitch bot with common stream commands and automatic chat announcements powered by `LiveRunTracker`.
- Keep the feature focused on local live-run data that is already needed by Twitch commands and the OBS overlay.
- Prefer configurable command names/messages where streamers may want different wording.

Command ideas:

- `!chests`
  - Track how many chests the player has opened during the current run.
  - Store the data per map/stage in `LiveRunTracker`, for example:
    - Map 1: 15 opened chests
    - Map 2: 20 opened chests
    - Map 3: 0 opened chests
  - The Twitch command should return a compact per-map summary and a run total.
  - Also investigate whether free chest openings from the key item mechanic can be detected.
  - This requires reverse engineering or dump research to find a reliable signal for "key proc opened this chest for free".
  - If detectable, add free chest counts to the same statistics, either per map or as a run total.

- Disabled/Banned items command
  - Add a command for viewers to see important items that the streamer has disabled in-game.
  - Command name is not decided yet.
  - The streamer should be able to configure a short list of notable disabled items, especially popular build-defining items that viewers may expect to see.
  - Example items: Soul Harvester, Anvil, Idol Juice, and other high-impact items.
  - The command should output only the important configured items, not every possible disabled item, so the chat response stays readable.
  - Future implementation can either read the real disabled-item state from game memory if available, or use streamer-managed configuration first.

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

- Commands list command
  - Add a manual command that returns the list of currently available Twitch bot commands.
  - Command name is not decided yet; likely candidates are `!commands` or `!help`.
  - This should work as an alternative to the periodic commands-list auto announcer.
  - The command should only list enabled commands and should respect streamer configuration.
  - Keep the output short enough that viewers can call it on demand without creating chat spam.

Announcement ideas:

- End-of-run auto announcer
  - When the player finishes a run or dies, automatically post a full-run summary to Twitch chat.
  - Reuse the same run summary data used by existing run tracking and overlay systems where possible.
  - Include high-signal totals such as final time, map/stage progress, kills, score/damage-related stats if available, items, weapons, tomes, and future chest/cap information once implemented.
  - Make this optional in Twitch bot settings, because some streamers may prefer manual summaries only.

- Commands-list auto announcer
  - Add an optional periodic/event-based announcement that lists available Twitch bot commands.
  - Intended to replace manual setup in external bots such as Nightbot.
  - Support a configurable interval, for example every 30 minutes.
  - Consider also triggering it on selected events, such as bot connection, run start, or stage transition, with cooldown protection.
  - The message should stay short and only list enabled commands.
  - This should share the same command-list formatting/source as the manual commands list command.


