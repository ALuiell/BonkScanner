# Functional Updates

Date: 2026-08-18

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## Open Updates

### In-Game Map Activity Markers

Status: `[Planned / Requires In-Game Verification]`

Goal:

- Add optional activity markers over the game's full map so a player can return to an activity they already discovered, such as a Microwave, Shady Guy, Chest, Moai, or another shrine.
- Keep this strictly as a quality-of-life memory aid. BonkScanner must not reveal activities that the player has not approached or otherwise discovered through normal gameplay.
- Implement the feature entirely in the existing external application through read-only process-memory access and the current in-game overlay. BepInEx, injected DLLs, and game-memory writes are out of scope.

Recommended hybrid model:

1. Automatically discover an activity only after the game itself selects it as the player's current interaction target.
2. Record an approximate position immediately, using the player's position at the time of discovery.
3. Show the resulting type-specific marker only while the full map is open.
4. Let the user move, replace, hide, or delete an automatically created marker through a manual marker-edit mode.
5. Later, replace the approximate player position with the discovered object's exact Unity Transform if live testing shows that the approximation is not accurate enough. This must not require enumerating undiscovered map objects.

Current product decision:

- Ship two discovery paths: automatic proximity discovery through the unmodified `currentInteractable`, and explicit manual placement for an activity the player saw but did not approach.
- Keep the game's normal interaction range unchanged. Live verification read `DetectInteractables.interactableRange = 5.0`, which in practice requires the player to stand nearly next to a Microwave.
- Do not implement a custom `20--25 m` memory-based field-of-view detector in the current scope. Distance and camera-angle checks cannot prove that an object is not behind a wall or terrain, while scene-wide object enumeration would read undiscovered activities before the fair-play filter is applied.
- Do not write a larger value into `interactableRange`; that would alter the game's own prompt and interaction behavior rather than add an external QoL marker.
- Revisit longer-range automatic discovery only if it gains a reliable positive visibility signal, such as robust on-screen recognition, without exposing hidden object locations.

Automatic discovery source:

Use the short, already live-validated `DetectInteractables.currentInteractable` path:

```text
GameAssembly.dll + MyPlayer TypeInfo
  -> static fields
  -> MyPlayer.Instance
  -> MyPlayer.playerInput
  -> PlayerInput.detectInteractables
  -> DetectInteractables.currentInteractable
```

- Read only this short chain on the fast activity-marker lane. Existing chest investigation found `25 ms` reliable for short-lived interaction targets; the final interval should be confirmed with Microwaves, Shady Guys, and representative shrine classes.
- Resolve the selected object's IL2CPP class name and map only an explicit allowlist of supported `BaseInteractable` subclasses to marker types.
- Candidate classes include `InteractableMicrowave`, `InteractableChest`, `InteractableShadyGuy`, `ChargeShrine`, `InteractableShrineMagnet`, `InteractableShrineGreed`, `InteractableShrineMoai`, `InteractableShrineChallenge`, `InteractableShrineCursed`, and `InteractableShrineBalance`.
- Require a valid object pointer and recognized class. An unavailable, corrupt, or unsupported read creates no marker.
- Prefer a small stability requirement, such as two agreeing observations or approximately `50--100 ms`, if live tests show that it avoids incidental targets without missing fast fly-bys.
- The same object pointer seen again during the same map/stage updates the existing marker instead of creating a duplicate.
- Treat `currentInteractable` as an observation event, not as persistent marker state. Live testing showed nearby Pots temporarily replacing a Microwave as the selected target; losing selection must not remove a previously discovered marker.

Fair-play boundary:

- Do not enumerate every `BaseInteractable`, spawn list, scene object, or minimap icon on the map.
- Do not derive markers from the aggregate `InteractablesStatus` totals; those values say how many activities exist or were used, but not which individual locations the player discovered.
- Do not create a marker merely because an object exists inside generated map data or process memory.
- A marker may enter BonkScanner's local discovered-object ledger only after the corresponding object appears in `currentInteractable`, meaning the game's own interaction system has already selected it near the player.
- Never use a failed fog, position, class, or lifecycle read as permission to display an object. Unknown state must fail closed.
- Optional fog-state validation may be added as a second positive check, but it must not replace proximity-based discovery or become a filter over a map-wide hidden-object scan.

Marker record and scope:

Each discovered marker should retain enough identity to reject stale pointers and survive ordinary overlay refreshes:

```text
marker_id
marker_type
object_ptr
map_seed
current_map_ptr
stage_ptr / resolved stage identity
world_x, world_y, world_z
position_source       # player_nearby | exact_object | manual
discovered_at
last_confirmed_at
activity_state
manually_adjusted
```

- Keep marker state in memory for the active run. Do not persist run-specific pointers or coordinates into `config.json`.
- Manual marker preferences and icon visibility settings may persist, but individual run markers must not.
- Clear or invalidate the ledger on a new run, map reset, relevant stage transition, `MyPlayer.Instance` replacement, or a confirmed map identity change.
- Revalidate a cached object before reading subclass-specific fields. Never continue walking an old pointer after its run/map identity has expired.

Position acquisition:

For the MVP, capture the player's world position when the target is discovered.

- `PlayerMovement.lastGroundedPosition` is a candidate approximate source and has been observed changing with live movement.
- Characterize its accuracy while running, jumping, flying, falling, and approaching an object without touching the ground. If it can lag materially during normal discovery, do not ship it as the only position source.
- Approximate positions should be labelled internally as `player_nearby`; the expected error is bounded by the interaction range rather than being presented as the object's exact center.
- Manual adjustment must preserve the marker's discovery provenance while replacing only its displayed coordinates.

For a later exact-position path:

- Start from the already discovered `currentInteractable` pointer and resolve only that object's Unity Transform.
- Reconstruct and live-validate the current Unity native `Component/GameObject/Transform` layout reached through the managed object's cached native pointer.
- Do not introduce a scene-wide Transform or object scan merely to improve marker precision.

World-to-map projection:

The current dump exposes `MapInfo.mapCenter`, `mapSize`, and map bounds, while `FullMap` owns `worldSize`, `textureSize`, the fog state, and its display Transform. Native inspection indicates that fog/map cells are derived from world `X/Z` approximately as:

```text
u = (world_x + world_size / 2) / world_size
v = (world_z + world_size / 2) / world_size
```

- Verify the exact axis orientation, vertical inversion, map centering, and clamping on every supported map family.
- Resolve the visible full-map rectangle inside the game client so normalized `u/v` coordinates can be converted into overlay pixels.
- Test windowed, borderless, fullscreen, non-16:9, UI-scale, and resolution changes. Marker placement must follow the existing overlay's synchronized game-client geometry.
- If the map rectangle cannot yet be read reliably from Unity UI state, use a small resolution-aware calibration layer rather than hard-coded absolute pixels.
- Keep projection independent from discovery and marker state so it can be corrected without losing the run ledger.

Map-open detection and overlay behavior:

- Show map markers only while the full map is visibly open.
- A foreground-only `Tab` key observation can provide the first MVP signal, but it can desynchronize if the game ignores the key, a menu consumes it, or the binding changes.
- Prefer a persistent game/UI state such as `FullMap.mapsOpen` or active-state validation once the `FullMap` instance path is recovered.
- Keep the overlay `Qt.WindowTransparentForInput` during normal gameplay and normal map viewing.
- Enter an explicit marker-edit mode before accepting pointer input. Exiting the mode restores click-through behavior immediately.

Activity lifecycle:

- Classify lifecycle behavior per supported activity instead of applying one generic "remove after interaction" rule.
- A Microwave can remain useful after the first interaction and exposes state candidates such as `usesLeft`, `isCooking`, `hasItem`, and `readyAtTime`. Its marker may transition through available, cooking, ready, exhausted, or destroyed states.
- Shrines commonly expose `done`, `completed`, or `rewardGiven`-style fields. Confirm each class live before using those fields as authoritative.
- Chests expose their own type/opening state and already have aggregate counters, but an aggregate count change alone must not remove an arbitrary chest marker.
- When an exact individual completion cannot be attributed safely, retain the last known marker or mark its state uncertain; do not guess which location was consumed.
- Offer settings to hide completed markers immediately, keep them dimmed, or show only still-usable activities.

Manual marker mode:

- Provide a small type palette while the map is open.
- Allow creating a manual marker, dragging an automatic or manual marker, changing its type, and deleting it.
- Store marker coordinates normalized to the map, not as raw desktop pixels.
- Visually distinguish manual, approximate automatic, and exact automatic placement only if that distinction is useful to the player; provenance must remain available internally for diagnostics.
- Manual mode is both a fallback for unsupported activities and a correction tool for interaction-range position error.
- Manual placement is also the intentional path for activities seen from farther than the game's approximately five-metre interaction range. Automatic discovery must not attempt to infer those sightings from hidden scene objects.

Proposed architecture:

```text
ActivityDiscoveryReader
  -> read-only currentInteractable/class/subclass state
  -> emits discovered-target observations

MapMarkerService
  -> owns the active-run discovered-object ledger
  -> deduplicates pointers and applies lifecycle/reset rules
  -> never reads or renders hidden map objects

MapProjection
  -> converts world/normalized map coordinates to overlay pixels
  -> owns map rectangle, axis orientation, scale, and clamping

MapMarkerOverlayWidget
  -> renders markers while the full map is open
  -> handles explicit manual edit mode only
```

- Own `MapMarkerService` on `AppCoordinator` with other run-scoped services.
- Keep memory reading and projection Qt-free where practical; the QWidget layer should receive a ready-to-render immutable snapshot.
- Do not attach the 25 ms reader to the general 10-second player-stat snapshot. Start it only when map markers are enabled and an active run/player instance exists.
- Publish marker snapshots to the GUI thread through the existing scheduling/signalling boundary rather than mutating Qt widgets from the polling thread.
- Bound shutdown and invalidate all pointers before closing the shared memory client.

Suggested delivery stages:

1. **Diagnostic probe:** Log target class, object pointer, approximate player position, run/map/stage identity, and relevant subclass fields without rendering anything.
2. **Manual-only overlay:** Validate map-open detection, map rectangle, normalized coordinates, resizing, and edit-mode input behavior.
3. **Automatic MVP:** Add proximity-discovered markers using the approximate player position, deduplication, run resets, and manual correction.
4. **Lifecycle support:** Add verified available/completed/cooking/ready states class by class.
5. **Exact positioning:** Resolve only a discovered object's Transform if approximation tests justify the additional native Unity work.

Required live validation before implementation:

- Approach, leave, re-approach, and interact with at least two different Microwaves in one run; record pointer stability and every relevant field transition.
- Repeat for Shady Guy, a Chest, Charge Shrine, Magnet Shrine, Moai, Greed Shrine, and Challenge Shrine.
- Measure how long `currentInteractable` remains non-null during slow approach, immediate interaction, and fast fly-by.
- Compare the approximate player position with the visible activity location while grounded and airborne.
- Capture known world positions and their full-map screen positions on Forest, Desert, and Graveyard to solve and verify projection orientation.
- Verify stage transitions, boss rooms, Graveyard crypt/main-map transitions, reset, death, and a new run for stale-marker cleanup.
- Verify full-map open/close behavior with other menus, pause, focus loss, resolution changes, and the existing overlay layout hotkey.
- Confirm that no marker appears for any activity that was never selected by the game's interaction system.

Acceptance criteria for the first automatic release:

- An enabled marker appears only after a supported activity has been selected as `currentInteractable` during the current run.
- Re-approaching the same object does not create duplicates.
- No marker from a previous map, stage scope, player instance, or run survives into an unrelated map state.
- Marker placement remains useful across supported resolutions and can be corrected manually.
- Opening and closing the full map never leaves the overlay capturing gameplay input.
- A failed memory read, unresolved class, unknown coordinate transform, or unsupported lifecycle state cannot reveal or fabricate an activity.

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
