# Functional Updates

Date: 2026-08-16

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Recently Implemented

### Build Progression Overlay Widget

Status: `[Implemented]`

Goal:

- Add one shared `Build Progression` feature to Live Stats, OBS Overlay, In-Game Overlay, and Twitch `!build`.
- Let each user keep a personal library of build checklists, choose one active build, and share individual builds as JSON files. BonkScanner does not ship predefined builds or Early/Mid/Late phases.
- Answer the two questions that matter during a run: what is still missing from the finished build, and whether each timed requirement is still on schedule.

Build definition:

- An item requirement contains an item name, required copies, and an optional deadline.
- A stat requirement contains a canonical player-stat name, a raw minimum threshold, and an optional deadline.
- A progress requirement contains a supported run counter such as kills or player level, a required whole-number target, and an optional deadline.
- Deadlines are `No deadline`, `Before tier`, or `Tier overtime`.
- `Before tier` means the requirement must be satisfied before the selected tier begins.
- Requirements without a target time remain neutral until completed and still count toward overall build completion.
- The build is complete only while every configured requirement is currently satisfied:
  - current item copies are greater than or equal to the configured count;
  - current stat values are greater than or equal to the configured threshold;
  - current progress counters are greater than or equal to the configured target.
- If an item disappears or a live value falls below its threshold, the build returns to an incomplete state.

Run lifecycle:

- The build library and active build selection persist between launches and runs.
- Switching the active build applies immediately on every live surface and starts that build's temporary transition timestamps cleanly.
- Runtime progress, completion timestamps, deadline state, and the `BUILD COMPLETE` state reset for every new game/run.
- Runtime progress must be keyed to the tracker's run identity and must never be written back into `config.json`.

Compact display behavior:

- Show a one-line header with the build name and completed/total requirements; do not repeat the current run time.
- Hide completed rows by default. `Show completed` restores the green checked rows without adding a `+N completed` summary.
- Group rows into `ITEMS`, `STATS`, and `PROGRESS`. Within each group, sort by nearest deadline; untimed requirements follow timed requirements and preserve their configured order.
- Keep item labels in their rarity colour and use status colour only on the symbol and deadline, so rarity and runtime state do not compete for the same text.
- Support a configurable maximum row count so the widget cannot grow across a large part of the OBS or game canvas.
- When every requirement is satisfied, collapse the widget to `BUILD COMPLETE` with the completion time.
- Keep OBS and In-Game presentation settings independent while both surfaces consume the same configured checklist and evaluated runtime state.
- Twitch `!build` sends unfinished requirements first and, when any exist, completed requirements in a second compact `COMPLETED:` message. Each message truncates only between complete requirement chunks.

Status semantics:

- neutral/gray: incomplete, but not yet inside the warning window, or no deadline is configured;
- yellow: incomplete and inside the warning window;
- red: incomplete after its target time;
- green: currently satisfied;
- color must always be paired with a symbol or label so status is not communicated by color alone.

Configuration UI:

- Expose one shared Build Manager from Live Stats and both overlay settings areas instead of maintaining separate definitions.
- Use the manager as a lightweight hub: clicking a card opens the existing full Configure Build editor, while a separate `Set Active` action changes the live build.
- Support creating, duplicating, deleting, importing, and exporting individual builds. Export files contain only portable definition data; imported builds receive new internal IDs.
- Keep only presentation controls local to the in-game overlay: enabled state, scale, maximum rows, and completed-row visibility.
- Let OBS choose a `Full`, `Compact`, or `Text only` presentation mode, plus scale, maximum rows, and completed-row visibility.
- The editor supports adding, removing, and reordering item/stat/progress requirements without introducing built-in presets.

Runtime and architecture notes:

- The Qt-free evaluator lives in `core`; `BuildProgressionService`, owned by `AppCoordinator`, owns only per-run transition timestamps.
- No new refresh task or polling loop was added. Existing combat, passive-items, event-timer, full-snapshot, and lifecycle tasks publish the data the service derives from.
- Live Stats, OBS, In-Game Overlay, and Twitch consume the same evaluated snapshot, so completion and deadline rules cannot drift.
- Reuse `RuntimeStateSnapshot.fast_items` for the freshest available inventory and fall back to `latest_snapshot.items` only when the fast reading is unavailable.
- Reuse `latest_snapshot.stats` initially, but note that the current Stats widget receives those values on the slower snapshot cadence. True real-time stat progress requires a narrow fast path for only the stats selected by Build Progression.
- The already-read fast run time is now published on the runtime snapshot so item counts, deadlines, and displayed time share one runtime boundary.
- Add tests for item-copy counting, stat thresholds, optional deadlines, warning/overdue transitions, row ordering, disappearing requirements, run reset, and the all-requirements-complete collapse.

Proposed layouts:

- [Shared Build Progression editor](../../ui_mockups/build_progression/build_progression_settings_v2.html) — historical layout reference; the implemented editor now keeps the catalog on the left and the selected requirement form plus deadline-sorted list on the right.
- [Interactive layout comparison](../../ui_mockups/build_progression/build_progression_overlay_options.html) — switch between in-progress, overdue, and complete states and optionally show completed rows.
- [OBS readable compact card](../../ui_mockups/build_progression/build_progression_overlay_options.fragment.html#bonk-obs-title) — bounded translucent card intended to remain legible on stream.
- [In-Game minimal HUD list](../../ui_mockups/build_progression/build_progression_overlay_options.fragment.html#bonk-ingame-title) — frameless, shadowed text intended to stay out of the player's way.
- [Ultra-compact urgent target](../../ui_mockups/build_progression/build_progression_overlay_options.fragment.html#bonk-focus-title) — only the next urgent missing requirement plus overall progress.

## Open Updates

### Build Progression

Status: `[Partial]`

Implemented behavior:

- Keep each entry in the Build Requirements list on one line instead of wrapping its deadline and action controls onto a second line.
- Apply the base item-rarity colours consistently. Verify that the `Stonks` power-up colour is visually distinct from the legendary-item colour rather than using the same colour one-to-one.

Planned item-requirement behavior:

- Keep the existing single required-copy target when no maximum is configured.
- Support a two-stage requirement with `Minimum copies` and an optional `Maximum copies`.
- Keep both controls in the existing `Required` row: `Min [value]` and `Max [value]`. A blank `Max` means no final target and introduces no additional control.
- The overlay must keep one compact count column between the item name and deadline, without `max` labels or parenthetical metadata:
  - before the minimum: `0/1`;
  - after the minimum is reached: `1/15`;
  - after the maximum is reached: `15/15` with the normal satisfied state.
- The count column stays visually separate from the item name; do not press it directly against the item label.
- The existing deadline control applies to the minimum stage. The maximum stage has no separate deadline in the first release.
- Evaluate the two stages as follows:
  - while the current count is below `Min`, the minimum is the active target;
  - after `Min` is reached and while the current count is below `Max`, the maximum becomes the active target;
  - when no `Max` is configured, reaching `Min` completes the requirement;
  - when `Max` is configured, only reaching `Max` completes the requirement and contributes the final completed count in the build header.
- Validate both inputs as positive integers. A blank `Max` means no second stage; when present, `Max` must be greater than or equal to `Min`. Existing definitions with one `required` value migrate that value to `Min` and leave `Max` blank.

Planned dynamic-cap behavior:

- Initially support `Track radius cap` for [Spicy Meatball](https://www.megabonkinfo.org/item/spicy-meatball) and [Grandma's Secret Tonic](https://www.megabonkinfo.org/item/grandmas-secret-tonic). It is off by default.
- With cap tracking off, the item uses the normal manual minimum/optional-maximum requirement.
- Show the cap option as one checkbox below the two count controls. Do not expose it for ordinary items.
- With cap tracking on, replace the normal controls with `First copy [1]` and `Cap [Auto]`. The first-copy value is fixed and the cap field is not manually editable.
- Preserve a manually entered maximum while cap tracking is enabled so turning the checkbox off restores the previous normal requirement.
- With cap tracking on, the first stage is a fixed `0/1` requirement with its own configurable deadline. The player must receive at least one copy before that deadline even when one copy does not reach the cap.
- Receiving the first copy captures `Size` and starts the second stage by replacing the target with the calculated cap count. The cap stage has no separate deadline in the first release.
- A later item-count change may recalculate the cap from the new captured runtime inputs, so a row may advance as `1/5`, then `2/3`, then `3/3`.
- Use the documented radius formula for both initially supported items without requiring a separate live-verification gate: `Radius(n, S) = min(max((3 + n) * S, 1), 8)`. The automatic target is the smallest whole copy count `n` that reaches radius `8`.
- Treat an active Build Progression cap rule as consumer demand for a narrow named `SIZE` source in the coordinator-owned passive-items task, following the existing fast `LUCK` source pattern. Build Progression must not call the memory client directly.
- While that demand exists, resolve `SIZE` alongside `PASSIVE_ITEMS` in every due passive-items pass and publish both through the tracker/runtime snapshot. When the item count changes, capture the `Size` value from that same coordinator pass; do not wait for the normal 10-second full player-stats snapshot.
- The narrow `get_size` reader may make up to three immediate physical attempts inside its one coordinator source resolution. Each failed cached-pointer attempt must allow the next attempt to resolve the pointer again. The per-pass source cache still exposes one logical `SIZE` result to all consumers.
- If all three attempts in the pickup pass fail, keep the cap target unresolved and render a neutral count such as `1/—`. Do not substitute `1.0`, the previous full snapshot, or another invented numeric value because it could falsely claim that the cap was reached. A later successful `Size` sample must not be retroactively assigned to that pickup; attempt a new capture only on the next observed copy-count change.
- Keep the overlay compact: show only the item name, current/target count, status symbol, and the first-stage deadline when configured. Do not display Size, radius, formulas, or technical metadata there.
- If extra copies of an auto-cap item are picked up beyond the calculated cap (e.g. 1 copy is enough for the cap, but a 2nd copy is obtained), do not artificially raise the required count to match current copies — keep the required target as the calculated cap and display `2/1`, not `2/2`.

Colour and status behavior:

- Keep the item name in its rarity colour.
- Keep the current/target count neutral.
- Use green only for the normal on-time satisfied state; keep yellow and red exclusively for warning and overdue deadlines.
- Do not introduce a separate colour for dynamic-cap requirements.
- Keep the status symbol in its own leading column before the item name on every overlay surface.
- A requirement obtained after its minimum deadline becomes `late completed` rather than returning to the normal on-time state. Show both the leading status symbol AND the deadline text on the right in orange (`#F97316`) instead of green text, and retain that late state while its optional maximum or dynamic cap is being tracked.
- Do not hide late-completed requirements when ordinary completed rows are hidden. When all final targets are complete but at least one requirement was late, use the corresponding late build-complete state instead of the normal fully on-time state.

Known issues & planned fixes:

1. **Auto-cap count target on extra pickups**: When a player obtains extra copies beyond what is required to reach the max cap (e.g., cap is satisfied with 1 copy, but a 2nd copy drops), the target count should remain at the calculated cap requirement (displaying `2/1`), rather than inflating the required target to match the current count (`2/2`).
2. **Late deadline text coloring**: When a requirement is fulfilled after its deadline expires, both the leading checkmark symbol and the deadline text label on the right must be colored orange (`#F97316`), rather than displaying an orange checkmark with green deadline text.
3. **State retention on mid-run build replacement**: When `replace_definition` is invoked mid-run (e.g., when the user edits and saves build settings during an active game), retain historical timestamps and flags (`_min_satisfied_at`, `_satisfied_at`, `_late`, `_cap_states`) for existing requirements instead of clearing them. This prevents previously on-time completed requirements from falsely converting into late-completed state on the subsequent evaluation tick.

Shared behavior:

- Apply the same min/max stages, cap targets, count formatting, and late-completed state to Live Stats, OBS Overlay, In-Game Overlay, and Twitch `!build`; all four surfaces must consume the same evaluated Build Progression snapshot.

Deferred:

- Defer the optional background panel for the Build Progression widget in the In-Game Overlay. Revisit it only if the brighter rarity colours and existing text treatment stop being sufficiently readable against the game world.

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

#### 4. Reject Partial Passive-Inventory Reads Before Item-Delta Tracking

Status: `[Implemented]`

Goal:

- Prevent transient or partial memory reads from being interpreted as real item losses followed by new pickups.
- Keep legitimate stack increases and genuine remove/re-acquire sequences countable without inflating Session Stats, OBS, or Twitch tracked-item totals.

Problem Analysis:

- `_read_passive_item_dictionary` previously returned the successfully decoded entries even when one or more live dictionary entries could not be decoded. The resulting tuple was a partial inventory, but downstream code received it as an available, authoritative sample.
- An unreadable stack count previously degraded to `x1` on both the full-walk and cached-layout paths. For a real stack such as `Anvil x4`, two consecutive failed reads could therefore appear as a stable decrease to `Anvil x1`.
- `process_item_deltas` deliberately confirms a decrease after a second agreeing sample and lowers its baseline so a genuinely removed item can be counted when it is acquired again. This is correct only when both samples are complete inventory reads.
- Combining those behaviors created phantom pickups. For example, `x4 -> x1 -> x1 -> x4 -> x4` confirmed a loss of three and then credited the same three copies again. Likewise, an entry omitted from two partial dictionary walks was confirmed as removed and credited again when decoding recovered.
- This failure shape has been observed in recorded data: individual items have temporarily disappeared from otherwise non-empty inventories. The existing whole-inventory empty guard cannot protect against a partial tuple that still contains other items.

Implemented Behavior:

1. Treat any walk with `broken_entries > 0` as an unavailable inventory sample. Do not publish the successfully decoded subset as a complete inventory.
2. Treat an unreadable stack count as an unavailable inventory sample instead of fabricating `x1`.
3. Preserve the last confirmed inventory and item-delta baseline when a sample is unavailable. A failed read must produce neither a loss nor a gain candidate.
4. Apply the same validity rule to the uncached dictionary walk, cached-layout path, 1-second passive-item lane, and 10-second full snapshot path.
5. Continue accepting a genuinely empty, successfully read dictionary as an empty inventory where run lifecycle logic requires it; distinguish this from a failed or incomplete walk.
6. Keep actual stack increases countable by `gained_count`, including multiple copies obtained during one run.
7. Keep genuine item removal and later re-acquisition countable once both sides are supported by complete inventory samples.

Implementation:

- The entire passive-inventory read now fails at the memory-client boundary, before it reaches `LiveSnapshotStore` or `LiveRunTracker`. Downstream consumers never receive a tuple with omitted entries.
- An incomplete walk or failed cached stack read invalidates the passive-item layout so the next pass performs a clean rebuild.
- `MemoryReadError` from a stack address now propagates through the existing refresh error path instead of becoming a plausible-looking `x1`.
- Fast and slow consumers share the same source-validity contract, so one lane cannot confirm a decrease produced by a bad sample from the other.
- Rejected samples follow the existing refresh failure path and never reach the tracker, so they cannot create loss or gain candidates.

Regression Coverage:

- A broken entry in an otherwise valid dictionary rejects the entire sample and preserves the previous tracked-item baseline.
- Two consecutive partial reads omitting the same item, followed by recovery, produce no loss event and no additional tracked pickup.
- Two consecutive unreadable stack counts for a real `x4` stack, followed by recovery, leave the tracked total unchanged.
- A torn stack read where the two stabilizing reads disagree remains rejected on both cached and uncached paths.
- A genuine `x1 -> x2 -> x2` increase is still credited once, while holding `x2` produces no further increments.
- A genuine, completely read decrease followed by a completely read re-acquisition remains countable according to the existing tracked-item rules.
- Fast and slow item lanes observing the same rejected sample cannot jointly confirm a false decrease.

#### 5. Untimed Moai Exclusion and Banished Items Support in Loot Tracker

Status: `[Implemented]`

Goal:

- Separate Moai exclusion mechanics from Shady Guy and eliminate the expiring forward time window for Moai statues.
- Guarantee that any item selected and obtained from an activated Moai statue is excluded from Luck rarity calculations (`actual` and `expected`), regardless of how long the player takes to choose the item.
- Track banished items as valid chest rolls in Luck calculations (`actual` and `expected`), since items can only be banished when dropped from chests onto the floor.

Mechanics & Problem Analysis:

- **Asymmetry between Moai and Shady Guy:**
  - `Shady Guy`: the counter increments *after* purchasing and receiving the item (closing the trade UI). Retaining the backward window (`SHADY_GUY_BACKWARD_WINDOW_SECONDS = 2.0s`) with retro-exclusion via `recent_gains` remains correct.
  - `Moai`: the counter (`InteractablesStatus["Moais"].numUsed`) increments *immediately upon interacting with the statue* (opening the 3-item choice interface), before the item is chosen.
- **Why the previous 3.0s forward window failed:**
  - `MOAI_FORWARD_WINDOW_SECONDS = 3.0s` assumed that item grant occurs within 1-2 seconds.
  - The player cannot leave the Moai selection prompt without taking an item (or ignoring the statue entirely). If the player deliberates, reads descriptions, or kites mobs for more than 3.0 seconds, the pending exclusion expires by timeout (`_expire_exclusions`).
  - When the item is finally taken, the tracker treats it as an unexcluded chest roll, inflating `actual` and `expected`.
- **Banished Items as Legitimate Chest Rolls:**
  - When an item drops from a chest onto the floor, the player can choose to banish it instead of picking it up.
  - Banished items do not enter `PASSIVE_ITEMS` (they enter `LIVE_BANISHES` / `snapshot.banishes`).
  - Because an item on the floor was rolled from a chest according to the player's Luck stat at that moment, ignoring banished items causes `actual` and `expected` to miss legitimate rolls.

Implemented Behavior:

1. **Untimed Moai Exclusion Queue:**
   - When the `Moais` counter increments ($\Delta > 0$), register an untimed pending Moai exclusion.
   - The very next confirmed item gain(s) on the current map consume the pending Moai exclusion and are excluded from `actual` and `expected` calculations.
   - No expiring forward time limit (`MOAI_FORWARD_WINDOW_SECONDS`) is applied.
2. **Map Scope & Cleanup:**
   - Outstanding Moai exclusions are cleared on map generation/transition (`note_map_identity` / `_clear_map_scoped_state`), ensuring an abandoned statue choice does not leak into subsequent stages.
3. **Shady Guy Isolation:**
   - Shady Guy continues using its dedicated backward-window and retro-exclusion pipeline without alteration.
4. **Banished Items Tracking:**
   - `LIVE_BANISHES` is read in the existing 1-second passive-item loot pass together with Luck; the 10-second snapshot remains a fallback consumer of the same source.
   - The first successful banish collection establishes a baseline. Later unique additions are retained in a run-scoped union, so cached, repeated, or transiently partial reads cannot count the same banish twice.
   - Each newly banished passive item is resolved against `ITEM_RARITY_BY_NAME` and counted with the Luck value from the observing pass as a valid chest roll in both `actual` and `expected`.
   - Weapons, tomes, and unknown non-item entries in the shared banish collection are ignored.
   - Banish rolls do not consume Moai, Shady Guy, or microwave exclusions and are not retained for Shady Guy retro-exclusion.
