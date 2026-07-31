# Functional Updates

Date: 2026-07-20

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

Remaining open work:

- `!shrines`
  - Track the player stat bonuses gained from activating shrines on the current map.
  - Build a fingerprint catalog for every stat value that each shrine type can grant, similar to the existing Chaos Tome fingerprint detection.
  - Detect shrine activations by matching newly added permanent stat modifiers against those fingerprints.
  - Associate every detected shrine-stat event with the current map seed and maintain a per-seed activation counter so the same modifier is not counted more than once.
  - Reset the current-map shrine statistics when the seed changes, while keeping enough event data to produce a compact map summary.
  - The Twitch command should report the accumulated stat gains from shrines on the current map, for example: `Shrines: DMG +20% | Luck +10% | XP +15%`.
  - Fingerprint discovery and live validation are required before implementation to distinguish shrine modifiers reliably from items, tomes, and other permanent stat sources.

#### 2. Charge Shrine Documentation and `!shrines` Groundwork

Status: `[Open]`

Goal:

- Rebuild the Charge Shrine mechanics documentation from the current game dump and verified runtime captures before implementing shrine tracking or a Twitch `!shrines` command.
- Replace speculative or incorrect fingerprint data with values derived directly from `GameAssembly.dll` and confirmed through controlled 15-shrine batches.

Confirmed runtime findings:

- Shrine rewards are written to `StatInventory.permanentChanges`.
- Charging all 15 map shrines produces exactly 15 reward modifiers after the rewards are applied.
- Luck changes the observed rarity distribution.
- Clean batches with `Beacon x0` and `Beacon x1` both produced nominal rarity values; Beacon did not increase reward magnitude in the controlled test.
- Earlier `1.075`-scaled modifiers came from an unidentified source and must not be attributed to Beacon without new evidence.
- Several values in the current reverse document were corrected by runtime tests, including Armor, Evasion, Damage, Crit Chance, Luck, Pickup Range, Projectiles, Extra Jumps, Gold Gain, and XP Gain.

Required reverse-engineering work:

- Revisit `EncounterUtility.GetRandomStatValue` and reconstruct every shrine stat case, base value, and modify type from the current assembly.
- Revisit `EncounterUtility.GetRandomStatOffers`, its rounding path, and rarity selection order.
- Revisit `EncounterData.GetOffers` and `ItemBeacon.GetRewardMultiplier`; explain why static-analysis claims about Beacon scaling conflict with the clean runtime batch.
- Confirm the exact source of the historical `1.075` multiplier.
- Verify the current address and pointer chain for `AchievementTracker.chargedShrines`; the documented TypeInfo RVA did not resolve as a valid IL2CPP class pointer in the tested build.
- Confirm whether the completion counter increments before or after offer selection and whether it is suitable as a delayed-write reward budget.

Validation requirements:

- Run controlled 15-shrine batches with low and high Luck and with Beacon absent/present.
- Snapshot permanent modifiers immediately before and after each batch.
- Require every observed modifier to match a dump-derived fingerprint within float32 tolerance.

- Keep screenshots and exact memory values as fixtures for future automated tests.
- Do not implement `!shrines` until all 28 shrine stat fingerprints and the reward-budget source are confirmed.

Documentation anchor:

- `docs/recovery/reports/2026-06-15-shrines-mechanics-and-fingerprints.md`

#### 3. The One Ring Announcer

Status: `[Open]`

Goal:

- Add an automatic announcer for the Twitch bot that triggers when the player picks up "The One Ring" (in-game name: "Golden Ring").
- Support multiple randomized messages to keep the chat reaction fresh.

Example trigger messages:

- "Ash nazg durbatulûk... One Ring to rule them all, One Ring to find them, One Ring to bring them all, and in the darkness bind them! 👁️🌋"
- "[Streamer's Name] has found The One Ring... Keep it secret, keep it safe! 🧙‍♂️"

From the perspective of Gollum (using his signature speech style):

- "Ssss... Our precioussss! [Streamer's Name] found our precious! *gollum-gollum* 🐟💍"
- "Filthy, tricksy viewerssss want to steal it... But The One Ring is ours now! 👁️" (using "tricksy" as a classic Gollum reference)

#### 4. `!chaos` / `!chaostome` Roll Frequency Statistics

Status: `[Open]`

Goal:

- Extend the existing Chaos Tome tracking so chat can see not only the accumulated total bonuses, but also which Chaos stats have rolled most often and least often.
- Reuse the current per-stat roll counters already maintained by Chaos Tome tracking rather than introducing a second counting system.
- Keep the feature focused on the existing `!chaos` / `!chaostome` command output first, with optional UI exposure later if it proves useful.

Planned implementation notes:

- `LiveRunTracker` already stores the number of tracked rolls per Chaos stat, so the new work should mainly expose and format that data instead of re-detecting rolls.
- Add a structured helper that returns Chaos stat totals together with their roll counts, sorted in the same in-game order already used by the current Chaos summary.
- Decide and document the shipped scope for the frequency window:
  - either current run only;
  - or current BonkScanner session while the app stays open.
- If both views are valuable, keep the user-facing command compact and choose one default output, while leaving room for a second variant or suffix later.
- Example direction:
  - total view: `Chaos Tome Lv37: DMG +84% | Luck +21% | XP +30%`
  - frequency view: `Most rolled: DMG x5 | Luck x3 | XP x2`
- If the command tries to show both totals and frequency data in one message, it must still stay short enough for Twitch chat limits.

Open product decision:

- Confirm whether the first shipped version should report Chaos roll frequency for:
  - the current run only;
  - the whole app session;
  - or both, with one of them clearly marked as the default/stat-friendly view.

#### 6. Chest Statistics in Recordings and Compare Runs

Status: `[Open]`

Goal:

- Expose the chest breakdown in Compare Runs the same way the rarity totals from item 5 are exposed, behind its own toggle so the two can be shown independently.

What is already done:

- **The recording side needs little or no work.** Snapshots already carry `chests_opened`, `chests_total`, `chests_opened_by_stage`, `chests_total_by_stage`, `paid_chests`, `key_procs`, `expected_key_procs`, `free_chests` and `keys_count` — verified against `stats_recordings/950k.jsonl` (metadata `version: 6`). The remaining work is reading them back and rendering the comparison.

Remaining work:

- Add a Compare Runs toggle for the chest block, a sibling of the rarity one rather than a shared switch: a viewer comparing luck between runs and one comparing looting efficiency want different rows on screen.
- Decide which fields are worth comparing. Paid versus Key procs versus inherently free is the interesting split, and `expected_key_procs` beside the actual proc count is the one figure that says whether the Key stack paid off. Raw `chests_opened` alone compares map progress more than player decisions.
- Handle older recordings explicitly. Even inside a single version-6 file the early snapshots predate some keys — `chests_total`, `expected_key_procs` and `free_chests` are absent from the first few rows of `950k.jsonl` — so the comparison needs a real missing-value path rather than treating absence as zero, which would read as "no chests opened" instead of "not recorded".
- Keep the `Expected` label distinct from the rarity card's. Here it counts expected **key procs**; in item 5 it counts expected items per tier. The two now appear in the same tab and the same comparison view.

### In-Game Overlay

#### 1. Item Cooldown Display (Bob's Light and other timed items)

Status: `[Open]`

Goal:

- Show the live countdown to the next trigger of cooldown-driven passive items (first target: Bob's Light / `ItemBobLantern`), so the player can time movement and pulls around the next explosion.
- Ship it in one of three placements, to be decided: a new in-game overlay widget, an extra block inside the existing Powerups widget, or a Live Stats card. The read path below is identical for all three; only the projection and the renderer differ.

##### Verified memory read path

Confirmed live on 2026-07-31 against a running `Megabonk.exe` with `tools/probe_item_cooldown.py`. The probe was repaired in the same session (it had been calling a `PlayerStatsClient` method that no longer exists and walking a stale pointer chain) and is the reference implementation for this feature.

Pointer chain to the item object — all of it already exists in `PlayerStatsClient`, nothing new has to be resolved:

```text
PlayerStats TypeInfo (module_offset TYPE_INFO_OFFSET)
  -> class_ptr + CLASS_STATIC_FIELDS_OFFSET
  -> + STATIC_ROOT_OFFSET -> + OWNER_STATS_OFFSET      = owner_stats
owner_stats + INVENTORY_CONTAINER_OFFSET (0xA0)
  -> + PASSIVE_ITEM_DICT_OFFSET (0x50)                 = passive item Dictionary
     (fallback: owner_stats + PLAYER_INVENTORY_OFFSET 0x28
        -> + ITEM_INVENTORY_OFFSET 0x20
        -> + ITEM_INVENTORY_ITEMS_DICT_OFFSET 0x10)
dict + DICT_ENTRIES_OFFSET (0x18) / DICT_COUNT_OFFSET (0x20)
  -> entry = entries + DICT_ENTRY_START_OFFSET (0x20) + index * DICT_ENTRY_SIZE (0x18)
  -> entry + DICT_ENTRY_KEY_OFFSET   (0x08)            = item enum id (ItemBobLantern = 85)
  -> entry + DICT_ENTRY_VALUE_OFFSET (0x10)            = item object
```

Use `PlayerStatsClient._resolve_preferred_passive_item_dict(owner_stats)` ([src/infra/memory/player_stats_client.py:533](../../src/infra/memory/player_stats_client.py:533)) rather than re-deriving the chain. The container hangs off `owner_stats` **directly**; going through `PLAYER_INVENTORY_OFFSET` first yields a non-null pointer that then reads a null dictionary, which is exactly how the probe was broken.

Per-item cooldown fields, `ItemBobLantern` (offsets relative to the item object):

| Offset | Type | Field | Status |
| --- | --- | --- | --- |
| `0x18` | i32 | `amount` (stack count) | Confirmed — same value as `ITEM_STACK_COUNT_OFFSET` |
| `0x30` | f32 | `cooldownMin` | From `dump.cs`, not re-verified live |
| `0x34` | f32 | `cooldownMax` | From `dump.cs`, not re-verified live |
| `0x38` | f32 | `cooldownReductionPerAmount` | From `dump.cs`, not re-verified live |
| `0x3C` | f32 | `cooldown` — effective CD in seconds | **Confirmed live** (42.00 s at `amount = 1`) |
| `0x40` | f32 | `nextExplodeTime` — absolute game-time mark | **Confirmed live** |
| `0x44` | f32 | `radius` | From `dump.cs`, not re-verified live |

The clock these are measured against is `MyTime.time`, available as `PlayerStatsClient.get_my_time_seconds()` ([src/infra/memory/player_stats_client.py:1246](../../src/infra/memory/player_stats_client.py:1246)), which resolves `_resolve_my_time_static_fields() + MY_TIME_TIME_OFFSET (0x04)`.

##### Measured semantics

- `nextExplodeTime` is **not** a countdown. It is an absolute mark on the same `MyTime.time` axis, so the displayed value is `remaining = nextExplodeTime - my_time`. Observed: `my_time 118.45`, `nextExplodeTime 144.97`, remaining `26.52 s`.
- Re-arming is exact. Across one trigger the mark moved `102.95 -> 144.97`, a delta of `42.02 s` against a `cooldown` field of `42.00` — the game writes `nextExplodeTime = my_time + cooldown` at the moment of the explosion, so a rising `nextExplodeTime` is itself the trigger event and can drive a "just exploded" pulse in the UI.
- Pause freezes it. With the game paused, `my_time` held at `96.81` across 17 s of wall-clock and `remaining` stayed at `6.14 s`. Never derive the countdown from a local monotonic clock; every tick must re-read `my_time`. This is the same rule the KPS clock and the Event Timer already follow.
- `cooldown` stayed at exactly `42.00 s` at `amount = 1` across the whole observation. `cooldownReductionPerAmount` is therefore unexercised in the capture — stack scaling is documented but **not measured**.
- Stage/phase logic is irrelevant here. Unlike powerup effects, which need `resolve_ui_context` to pick between `stage_timer`, `crypt_timer` and `final_swarm_timer`, an item cooldown lives entirely on `MyTime.time` and needs no phase resolution. Do not route it through `core/tracker/powerups.py`'s UI-context machinery.

##### Implementation notes

Read side:

- Add a `get_item_cooldowns(owner_stats)` to `PlayerStatsClient` returning one record per cooldown-capable item: `item_id`, `name`, `stack_count`, `cooldown_seconds`, `next_trigger_time`, plus the `my_time` the batch was read against. Return `my_time` **from the same pass** — computing `remaining` in the renderer against a separately sampled clock reintroduces skew across the tick.
- Identify items by class metadata (`item + ITEM_CLASS_META_OFFSET (0x0)` -> `+ CLASS_META_NAME_PTR_OFFSET (0x10)` -> ASCII string), with `ITEM_ENUM_NAMES_BY_ID` as the fallback, matching `_read_passive_item_dictionary`. Do not match on substrings like `"bob"`: the field layout is per-class, so reading `0x3C`/`0x40` off the wrong class returns plausible floats rather than an error.
- Keep a per-class offset table (`{"ItemBobLantern": CooldownLayout(cooldown=0x3C, next=0x40)}`) rather than a single global constant. Every additional timed item needs its own `dump.cs` entry confirmed before it is added.
- Reuse the passive-item layout cache. `_read_passive_item_dictionary` already memoises `(stack_address, item_name)` per slot, invalidated on `DICT_VERSION_OFFSET (0x2C)` ([src/infra/memory/player_stats_client.py:739](../../src/infra/memory/player_stats_client.py:739)). Extending that tuple with the cooldown addresses makes the per-tick cost two extra float reads for the one item, instead of a second full dictionary walk. Respect the existing rule: **only a clean walk may be memoised** — memoising an incomplete walk is what previously made items disappear from recorded runs for tens of consecutive snapshots.

Refresh side:

- Ride the existing `powerups` task in `RefreshTasks` ([src/app/refresh_tasks.py:468](../../src/app/refresh_tasks.py:468)), registered at `FAST_TRACKER_INTERVAL_MS` (500 ms default, floor 100 ms) at [src/app/refresh_tasks.py:222](../../src/app/refresh_tasks.py:222). A 500 ms tick against a 42 s cooldown is far more than enough, and the task already resolves `owner_stats` through the shared `RefreshTickContext` pass cache, so no additional pointer walks are paid.
- If the display ends up in its own widget, give it its own `required` predicate next to `_should_refresh_powerup_tracker` ([src/app/refresh_tasks.py:900](../../src/app/refresh_tasks.py:900)) so the read is skipped when nothing shows it — the established demand-gating pattern, and the reason the fast lane stays affordable.
- Store the result in run-scoped tracker state with a TTL, as `core/tracker/powerups.py` does (`POWERUPS_SNAPSHOT_TTL_SECONDS = 1.5`). A missed read must degrade to "no reading", never to a stale countdown that keeps ticking. Clear it on run reset alongside the other powerup state.

Render side — the three candidate placements:

- **New in-game overlay widget.** Register the id in the widget tuple at [src/gui_in_game_overlay_window.py:408](../../src/gui_in_game_overlay_window.py:408), add defaults to `IN_GAME_OVERLAY["widgets"]` in [src/app/config.py:115](../../src/app/config.py:115) (`{"enabled": ..., "x": ..., "y": ..., "scale": 1.0}`), add the checkbox/scale controls in `gui_in_game_overlay_settings.py`, add an HTML builder beside `build_powerups_overlay_html` in [src/projections/in_game_html.py:227](../../src/projections/in_game_html.py:227), carry the data on `InGameOverlayProjection` ([src/projections/in_game.py](../../src/projections/in_game.py)) and paint it in the `refresh` body of `gui_in_game_overlay.py` next to the `powerups` block at [src/gui_in_game_overlay.py:350](../../src/gui_in_game_overlay.py:350). Anything not carried on the projection is simply invisible to the widgets — that is documented on the dataclass and has already shipped as a bug once.
- **Inside the Powerups widget.** Cheapest path: extend `build_powerups_overlay_html` with a second block. Note the widget currently hides itself entirely when no powerup is active (`setVisible(False)` at [src/gui_in_game_overlay.py:360](../../src/gui_in_game_overlay.py:360)); an item cooldown is active for the whole run, so that visibility rule has to change or the cooldown line disappears whenever no buff is up. This is the main argument for a separate widget.
- **Live Stats card.** Follows the existing card pattern in `src/ui/tabs/player_stats/live_stats.py`; useful for verification but does not serve the in-game use case.
- Colour treatment should reuse the existing convention in `in_game_html.py`: `CRITICAL_COLOR` under ~5 s remaining, `TEXT_SHADOW` on every span so the text survives a bright background.

##### Validation required before shipping

- Re-verify `0x3C`/`0x40` with `amount >= 2` and confirm whether `cooldown` drops by `cooldownReductionPerAmount` per stack; the current capture only covers `x1`.
- Confirm behaviour across a stage transition and a Graveyard crypt/boss transition: `MyTime.time` is expected to be continuous there (unlike `stage_timer`), but this has not been captured with a lantern equipped.
- Confirm what `nextExplodeTime` holds before the first trigger of a freshly picked-up item, and that the item is not present in the dictionary at all before pickup.
- Confirm the field reads as zero/garbage on a `game over` screen and that the TTL, not a stale float, is what clears the display.
- Add a characterization test with a fake memory backend covering: normal countdown, the re-arm jump, a paused clock (unchanged `my_time` over several ticks), a torn read, and an item whose class has no cooldown layout.

Reference tool:

- `tools/probe_item_cooldown.py` — prints stack count, effective cooldown, `nextExplodeTime` and remaining seconds every 500 ms, plus the rest of the passive inventory for context. Run it with the game attached; it is read-only.

### Help & Documentation

#### 1. Contextual Help Buttons With Deep Links

Status: `[Open]`

Goal:

- Add more visible `Help` buttons near the relevant UI areas so users can open documentation from the exact place where they need it.
- Make each help button jump directly to the matching documentation section instead of only opening the generic top of the help window.
- Example target behavior: pressing `Help` from the `OBS Overlay` tab should open the help dialog directly on the `OBS Overlay` explanation.

Planned implementation notes:

- Keep the existing help dialog, but add support for opening a specific section/anchor inside the loaded help content.
- Add tab-level help entry points for the main workflow areas, especially:
  - `Templates`
  - `Scores`
  - `Session Stats`
  - `Live Stats`
  - `Recordings`
  - `Compare Runs`
  - `OBS Overlay`
  - `Twitch Bot`
- Add additional in-tab help buttons where a tab contains multiple non-obvious sub-areas or nested tabs.
- Ensure nested areas can still point to the most relevant parent documentation section even if there is not yet a one-to-one subsection for every control.
- Keep the three bundled help files (`ENG`, `UA`, `RU`) aligned so deep-link targets exist consistently across languages.

Why this helps:

- Users will not need to manually search the help text every time they forget what a tab does.
- Feature discovery should improve, especially for `OBS Overlay`, `Recordings`, `Compare Runs`, and Twitch bot setup.
- This should reduce repetitive support questions about the purpose of specific tabs, controls, and nested views.

### Chaos Tome Fingerprint Tracking Optimization

Status: `[Planned / Requires More Verification]`

Goal:

- Explore recovering Chaos Tome rolls from permanent modifier fingerprints during attach or full snapshots, potentially moving Chaos Tome tracking from the continuous `500ms` fast poll lane to the `10s` core snapshot.

Required Characterization Tests Before Implementation:

- Attaching after the Chaos Tome has already reached a higher level;
- Multiple modifiers and stacked/aggregated modifier values;
- Delayed modifier writes after a level-up;
- Transiently missing or failed modifier reads;
- Reset at the start of a new run.

Until these cases are reliably validated, keep the existing `500ms` task and external behavior unchanged.

## Live Run Refactor Fixes

#### 3. Event Timer: Phase-Aware Game-Time Model (Refactor Fixes)

Status: `[Planned / Requires In-Game Verification]`

Goal:

- Build a reliable Event Timer projection from the game timer that is authoritative for the currently active map phase, including normal stages, Graveyard crypts, boss/ghost phases, pauses, timer resets, and timer jumps.

Problem Analysis:

- **`stage_timer` is not a universal run clock:** Normal stages reset it to `0.0` on entry and can force it forward to approximately `530--590s` to trigger Ghost Phase. A reset or a large positive jump is therefore gameplay state, not a read failure or a clock desynchronization.
- **Graveyard has multiple timer families:** Crypt UI countdowns are backed by an upward `crypt_timer`; the main outdoor phase uses `stage_timer`; the post-boss ghost phase is most reliably represented by an upward `final_swarm_timer` that continues across boss-room and portal movement.
- **Raw room identity is insufficient:** On Graveyard, seed, map pointer, stage pointer, and raw `stage_index` remain static through internal transitions. On Forest and Desert, the Boss Room reuses the Stage 3 pointer and raw stage behavior. The active timer cannot safely be selected from pointer or index changes alone.
- **UI semantics differ from raw memory:** A UI countdown may be `duration - raw_elapsed`, while the raw timer itself only increases. Some timer values continue after the UI reaches `00:00`, and Ghost Phase uses a different display rule.

Proposed Model:

Introduce a phase-aware resolver and a per-segment game-time synchronizer:

```text
PhaseTimerResolver
  -> identifies the active phase from timer availability, timer resets/jumps,
     and map/activity context
  -> selects the authoritative raw timer and display policy for that phase
  -> begins a new segment when the phase or source changes

GameTimerSynchronizer (one active segment)
  -> observes (local_monotonic_time, raw_timer_value)
  -> emits crossed whole game seconds while the raw timer advances
  -> treats an unchanged raw timer as pause
  -> predicts the next boundary only to improve read scheduling
  -> never uses wall-clock time as the displayed game time source

EventTimerProjection
  -> converts the synchronized raw value to elapsed / remaining / overtime UI text
```

Phase timer source and display policy should be explicit data, not inferred in rendering code:

| Phase family | Preferred raw source | Raw direction | Typical UI policy |
| --- | --- | --- | --- |
| Normal Forest/Desert stage | `stage_timer` | increasing | remaining time from stage duration, then Ghost Phase/overtime |
| Forest/Desert boss room | `stage_timer` | increasing after reset | remaining time from boss duration, then Ghost Phase/overtime |
| Graveyard crypt | `crypt_timer` | increasing | remaining time from the seed-specific crypt duration; clamp UI at `00:00` if required |
| Graveyard main map | `stage_timer` | increasing | remaining time from the 960s main-map duration, then Ghost Phase formatting |
| Graveyard post-boss swarm | `final_swarm_timer` | increasing | elapsed/phase-specific swarm presentation; preserve continuity across portal movement |

Segment lifecycle:

1. Resolve the best active timer source from map-specific timer availability, timer values, and activity-dictionary markers. Do not rely solely on `map_seed`, `stage_ptr`, or raw `stage_index`.
2. On the first valid read for a source, create a segment and establish its raw baseline; do not invent elapsed time from local clock.
3. While the selected raw timer increases normally, synchronize its integer-second boundaries exactly as in the KPS clock design. Use the local prediction only to optionally increase read frequency near the next boundary. Measured constraints for that fine window are recorded in [functional_updates_archive.md](functional_updates_archive.md), under the archived KPS item's "Considered and rejected: chasing the boundary with a variable interval" — a ~7 ms floor from the game's per-frame write, a 13 µs read, and Windows' 15.6 ms timer resolution, which together mean this needs its own thread rather than a faster `QTimer`.
4. If the raw timer is unchanged, preserve the projected value and mark the segment paused. Resume from the next advancing raw value without adding local elapsed time.
5. If the selected source changes, or the phase detector observes a valid reset, known jump, or confirmed activity transition, close the current segment and start a new one. This is an expected transition, not an error.
6. If a timer rollback or jump has no matching phase evidence, mark the timer state uncertain and re-enter a short calibration/confirmation mode rather than immediately displaying a fabricated countdown.
7. Render the current segment through its explicit display policy. The resolver, not the UI layer, owns phase selection and duration semantics.

Validation Required Before Implementation:

- Capture live traces for every Forest and Desert transition: Stage 1 -> 2, Stage 2 -> 3, Stage 3 -> Boss Room, boss death -> Ghost Phase.
- Capture Graveyard Crypt 1 start/exit, main map entry, Crypt 2 entry, boss entry, boss death, and return through the portal.
- For each trace, record active timer-family values, map/stage pointers, raw `stage_index`, relevant activity dictionary changes, and the visible UI timer.
- Verify seed-specific crypt durations and the exact display behavior at `00:00`.
- Add characterization tests for pause, delayed reads, source switching, timer reset, expected timer jump, and unexplained timer discontinuity.

Benefits:

- Event Timer remains synchronized with game time even when the application is delayed or the game is paused;
- map-specific timer semantics are isolated from generic synchronization mechanics;
- expected stage resets and Ghost Phase jumps no longer appear as false desynchronizations;
- the UI uses one authoritative phase/timer projection instead of duplicating fragile map rules across overlays.
