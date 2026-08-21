# Functional Updates

Date: 2026-08-20

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## Open Updates

### In-Game Map Activity Markers

Status: `[Implemented / Requires In-Game Acceptance Test]`

Goal:

- Add optional activity markers over the game's full map so a player can return to a useful activity that the game has already exposed through normal play.
- Keep this strictly as a quality-of-life memory aid. BonkScanner must not reveal activities that the player has not approached or otherwise discovered through normal gameplay.
- Implement the feature entirely in the existing external application through read-only process-memory access and the current in-game overlay. BepInEx, injected DLLs, and game-memory writes are out of scope.

Current phase and order of work:

- The icon assets, dynamic hotkey settings, read-only automatic discovery, exact Transform reads, FullMap projection, click-through renderer, and the first manual-placement interaction are implemented.
- Egg and Sus Bush are available as manual-only markers. They are intentionally absent from automatic discovery because the game does not expose them through the fixed map-activity allowlist.
- Automatic discovery is a separate opt-in setting and defaults to off. When enabled, it polls independently of whether `Tab` is held; holding `Tab` only controls whether the finished marker layer and manual palette are visible.
- The production cadence is `25 ms`: the shortest live useful selection window measured `93 ms`. After adding per-poll stage-boundary detection, 500 complete production polls averaged `0.2166 ms` with `0.5905 ms` p99 on the validation machine.
- Remaining work is an ordinary in-game acceptance pass: discover several activities, reopen the map, exercise tap/hold hotkeys, finish a run, start another run, and verify appearance, removal, input transparency, and run-boundary cleanup.

Fixed product scope:

- Render activity markers only over the large full map.
- Do not target the circular minimap in the first version. Its rotating camera, scale, crop, and limited space make a useful external implementation substantially more complex; integrating directly into the minimap would also move the design toward hooks or game-memory modification.
- Keep the game's normal interaction range unchanged. The previously observed `DetectInteractables.interactableRange = 5.0` requires the player to pass close to an activity.
- Do not implement a custom distance/field-of-view scan. Distance and camera direction cannot prove visibility through walls or terrain, while enumerating scene objects would expose activities before the fair-play condition is met.
- Exact activity placement is the target for the automatic release. The player's nearby position is allowed as a diagnostic/fallback measurement, but must not be presented as the object's exact location.
- Keep automatic discovery optional while community/streamer/developer feedback is still pending. Enabling `Map Activity Markers` alone must provide manual placement without silently enabling automatic activity reads.

Fixed activity allowlist:

| Marker | Game class candidate | Visual | Variants |
| --- | --- | --- | --- |
| Microwave | `InteractableMicrowave` | microwave front | Common/white, Rare/blue, Epic/purple, Legendary/gold |
| Shady Guy | `InteractableShadyGuy` | hat and shoulders | Common/white, Rare/blue, Epic/purple, Legendary/gold |
| Magnet Shrine | `InteractableShrineMagnet` | horseshoe magnet | one |
| Moai | `InteractableShrineMoai` | stone head profile | one |
| Challenge Shrine | `InteractableShrineChallenge` | two crossed swords | one |
| Boss Curse | `InteractableShrineCursed` | hooded figure and sword | one |

- Chests, Charge Shrines, Greed Shrines, Pots, and ordinary interactables are excluded. Chests are normally consumed immediately, while Charge Shrines already have a distinct map indication.
- `Boss Curse` currently maps to `InteractableShrineCursed`; it must not be confused with `InteractableBossSpawner`.
- `Egg` and `Sus Bush` are separate manual-only actions. They are selectable through `Add Hotkey` and the held palette, but are not class candidates and must never enter the automatic allowlist.

Fixed icon assets:

- Repository assets live under `src/media/map_markers/` as transparent `32 x 32` SVGs.
- `pictograms/` is the primary recognisable set. `shapes/` retains the accepted geometry-only alternative.
- Most glyph artwork is neutral `#F5F7FA`; Microwave and Shady Guy rarity is drawn as a separate white, blue, purple, or gold ring so the glyph itself is reusable. Egg keeps its cream shell and green spots, while Sus Bush keeps a green leafy silhouette with visible eyes.
- Dark pictogram variants are used only inside light-filled map markers. Settings rows and dropdowns use their light standalone counterparts so White Microwave, White Shady Guy, and Moai remain visible against the dark dialog background.
- The Challenge pictogram uses two crossed swords rather than axes or clubs.

Implemented settings and runtime controls:

- The `In-Game Overlay` widgets table now contains a separate `Map Activity Markers` row with enable, marker scale, hotkey-count summary, and `Settings` controls.
- This row is not a draggable Layout Mode HUD rectangle. Its configuration lives under `IN_GAME_OVERLAY.map_markers`, because the future renderer is anchored to the visible Full Map rather than to an arbitrary desktop position.
- `Settings` opens a dynamic list of assignments instead of fixed per-action hotkey fields. `Add Hotkey` and `Edit` record a keyboard input, Middle Mouse, Mouse 4, or Mouse 5 and assign one exact activity/rarity action, including Egg and Sus Bush.
- `Automatically mark discovered activities` is an independent checkbox inside the same dialog. It defaults to off; the table summary shows `Manual only` or `Auto on` so the active policy is visible without reopening the dialog.
- Plain `Tab`, `Escape`, movement keys, Left/Right Mouse, and wheel inputs remain reserved. Duplicate marker inputs and invalid/stale action identifiers fail closed during config normalization.
- The list is empty by default so the feature cannot steal an existing game/application input without an explicit user choice.
- Tap places the assigned exact marker at the cursor position captured on press. Holding the same input for `350 ms` opens the complete grouped palette; hovering selects an entry and releasing places that entry at the original anchor.
- The palette and markers remain click-through and use global key/mouse state, so they do not take focus from the game or interrupt held `Tab`.

Automatic discovery source:

Use only the short `DetectInteractables.currentInteractable` path previously exercised by the diagnostic chest investigation:

```text
GameAssembly.dll + MyPlayer TypeInfo
  -> static fields
  -> MyPlayer.Instance
  -> MyPlayer.playerInput
  -> PlayerInput.detectInteractables
  -> DetectInteractables.currentInteractable
```

- This path is entered only when `automatic_discovery` is explicitly enabled. With it off, the client still reads FullMap/player/stage identity for manual projection and cleanup but does not resolve `DetectInteractables`, read `currentInteractable`, run automatic lifecycle checks, or retain automatic markers.
- The current dump places `DetectInteractables.interactableRange` at `+0x20` and `currentInteractable` at `+0x28`; the production build must revalidate all game-build-sensitive paths and offsets.
- Poll this one game-selected pointer, not a list of all interactable objects.
- Resolve the selected object's IL2CPP class name and accept only the fixed allowlist above.
- Require a valid object pointer and recognized class. An unavailable, corrupt, or unsupported read creates no marker.
- Treat one valid selected-object observation as the initial hypothesis for sufficient positive evidence. A two-sample or time-stability rule may be added only if measurements show that it removes real false positives without losing fast fly-bys.
- The same object pointer seen again during the same map/stage updates the existing marker instead of creating a duplicate.
- Treat `currentInteractable` as an observation event, not as persistent marker state. Live testing showed nearby Pots temporarily replacing a Microwave as the selected target; losing selection must not remove a previously discovered marker.

Fair-play boundary:

- Do not enumerate every `BaseInteractable`, spawn list, scene object, or minimap icon on the map.
- Do not derive markers from the aggregate `InteractablesStatus` totals; those values say how many activities exist or were used, but not which individual locations the player discovered.
- Do not create a marker merely because an object exists inside generated map data or process memory.
- A marker may enter BonkScanner's local discovered-object ledger only after the corresponding object appears in `currentInteractable`, meaning the game's own interaction system has already selected it near the player.
- Never use a failed fog, position, class, or lifecycle read as permission to display an object. Unknown state must fail closed.
- Reading an exact Transform is permitted only after that individual object has appeared in `currentInteractable`.

Current reverse-engineering evidence:

- `InteractableMicrowave`: `rarity +0x80`, `usesLeft +0x84`, `isCooking +0x88`, `microwaveCenterTransform +0xC0`, `minimapIcon +0xD8`, `readyAtTime +0xF0`, and `hasItem +0xF4`.
- `InteractableShadyGuy`: `rarity +0x90` and `done +0xB0`.
- `InteractableShrineChallenge`: `done +0x68` and `hasGivenReward +0x80`.
- `InteractableShrineCursed`, `InteractableShrineMagnet`, and `InteractableShrineMoai`: `done +0x68`.
- `EItemRarity` currently maps `Common = 0`, `Rare = 1`, `Epic = 2`, and `Legendary = 3`; unsupported `Corrupted` and `Quest` values must fail closed unless product scope is expanded deliberately.
- `FullMap` exposes `mapCamera +0x20`, `worldSize +0x28`, `textureSize +0x2C`, `mapDisplayTransform +0x50`, `statsWindow +0x58`, `mapsOpen +0x60`, fog/visited collections, and `lastPos +0x80`.
- `FullMap.OnMapToggle(bool on)` is now reversed: it adds `+1` for `true` and `-1` for `false` to `mapsOpen`. `FullMap.IsMapOpen()` returns `mapsOpen > 0`, confirming that the field is an open-panel reference count rather than a Boolean.
- `FullMap.Awake` subscribes `FullMap.OnMapToggle` to static `FullMapUi.A_Toggle`; `FullMapUi.OnEnable`/`OnDisable` invoke that event with `true`/`false`. In the current game build, reading `FullMapUi` TypeInfo at `GameAssembly.dll + 0x2F9AF30`, then static fields, delegate, and delegate target produced a live managed `FullMap` instance.
- Live held/released `Tab` testing proved that `mapsOpen +0x60` changes with the real Full Map, including a short press and focus loss. The production client resolves the last live `FullMap` target from the multicast delegate because stale subscribers from previous runs remain in the invocation list.
- The exact external Unity Transform path is implemented: managed Component `+0x10` -> native Component -> native GameObject -> managed Transform handle, followed by the native hierarchy matrices/parent indices (`0x30` matrix stride). It produced exact world X/Z for the selected activities without enumerating scene objects.
- The marker scope combines live `FullMap`, `MyPlayer.Instance`, `MapController.currentStage`, and the stage index. A new run or an in-run stage transition therefore clears the discovered ledger, cached detector state, and tracked subclass identities.
- `MapInfo` exposes static `mapBoundsLower`, `mapBoundsUpper`, `mapCenter`, and `mapSize` vectors.
- `MyPlayer` exposes a static `Instance`; useful validation candidates include `playerInput`, `playerMovement`, `feet`, `minimapCamera`, and `minimapCameraScript`.
- The aggregate `InteractablesStatus` data contains counts but no individual object coordinates and is not a location source.

Implemented exact position and FullMap projection:

```text
selected currentInteractable
  -> managed Component / cached native Unity object
  -> exact object Transform.position (world X/Z)
  -> normalized FullMap coordinates
  -> visible map RectTransform rectangle
  -> game-client pixels
  -> overlay-local pixels
```

- The exact Transform is recovered only after the selected managed `BaseInteractable` passes the allowlist and lifecycle checks; no scene-wide GameObject or Transform list is scanned.
- Reversing `FullMap.QueueRevealFog` confirmed the projection used by the game:

```text
u = (world_x + world_size / 2) / world_size
v = (world_z + world_size / 2) / world_size
pixel_x = map_left + u * map_width
pixel_y = map_top + (1 - v) * map_height
```

- The visible content rectangle is read from `mapDisplayTransform`'s native RectTransform rect at `+0xA8` and transformed through its real hierarchy; no resolution-specific pixels are hard-coded.
- Held-`Tab` gameplay and `Escape -> Tab` use separate UI transforms without changing the active `FullMap` pointer or client resolution. `FullMap.mapDisplayTransform` remains the small held-Tab rectangle even while the pause Map is visible. The large viewport is resolved read-only through `UiManager.Instance -> PauseUi.map -> W_Map -> MapRender` when `PauseUi.current == PauseUi.map`; switching layouts therefore updates projection and clipping together without resolution-specific pixels.
- Unity/Win32 expose physical client pixels while Qt paints in logical pixels on a scaled monitor. The production path divides the FullMap viewport and physical cursor-to-client offset by the overlay window's device-pixel ratio before hit-testing, unprojection, or painting; this is required for `125%`/`150%` Windows scaling.
- In the synchronized `2560 x 1440` validation capture this resolved to `(left=33.3333, top=286.6667, width=1000.0000, height=1000.0000)`. Player world `X=-72.762466, Z=-246.898972` projected to `(412.06, 1198.17)`, coinciding with the game's own map arrow.

Marker record and scope:

Each discovered marker retains the minimal run-scoped identity needed by the renderer and lifecycle reader:

```text
marker_id
action_id
object_ptr
world_x, world_z
source                # automatic | manual
```

- Keep marker state in memory for the active run. Do not persist run-specific pointers or coordinates into `config.json`.
- Clear the ledger when the active `FullMap`, `MyPlayer.Instance`, current stage pointer, or stage index changes, and whenever the feature/overlay is stopped.
- Revalidate a cached object before reading subclass-specific fields. Never continue walking an old pointer after its run/map identity has expired.

Map-open detection and overlay behavior:

- Show map markers only while the full map is visibly open.
- The map is normally visible only while `Tab` is held. This does not block passive automatic discovery when the user has opted into it, but it makes mouse-based manual editing a separate input/design problem.
- Use the game's actual `FullMap.IsMapOpen()` condition rather than keyboard observation. Both disassembly and live held/released `Tab` tests prove it is `mapsOpen > 0`; a missing/stale FullMap fails closed and hides the layer.
- Keep the overlay `Qt.WindowTransparentForInput` during normal gameplay and normal map viewing.
- Normal automatic rendering must remain passive and click-through while the player holds `Tab`.
- Keep complete marker circles inside the active viewport at its four boundaries. White Microwave, White Shady Guy, and the light-gray Moai retain their activity/rarity fill but use dedicated dark pictograms so the activity silhouette remains readable.

Activity lifecycle:

- Shady Guy removes on its own `done +0xB0`; one live purchase changed it from `0` to `1` before the native object was destroyed.
- Moai, Challenge Shrine, Boss Curse, and Magnet Shrine remove on their own `done +0x68`. Every transition was captured live; Challenge removal deliberately does not wait for its later reward state.
- Microwave remains marked through every useful phase. Starting the last craft immediately sets `usesLeft = 0`, so it removes only when `usesLeft <= 0 && !isCooking && !hasItem`, after the final crafted item is collected.
- Loss of `currentInteractable` alone never removes a discovery. Re-approaching the same object pointer deduplicates it, and automatic discovery replaces a nearby same-family manual estimate.

Fixed manual mode: `Manual Map Placement`

- Use one manual mode on the visible Full Map. Remove the separate player-position Quick Mark, directional marker, and triangulation concepts; they either imply an inaccurate location or add too much interaction for a small, quickly traversed map.
- Do not use screenshots, screen recognition, image analysis, or map-symbol detection. Manual placement uses only the known FullMap rectangle, global cursor position, configured hotkeys, and the external overlay.
- A marker hotkey has an assigned default activity type and, for Microwave or Shady Guy, an assigned rarity.
- Assignments may use keyboard keys (`F1--F24`, letters/digits, supported named keys, and modifier combinations) or Middle Mouse/Mouse 4/Mouse 5; all are polled through the same non-capturing Windows input path.
- On hotkey press, capture the cursor's normalized map coordinate as an immutable placement anchor and show a ghost icon there. Cursor movement used to choose an icon must never move that anchor.
- A short press/release places the hotkey's assigned marker at the anchor.
- Holding the same hotkey opens the current compact Recordings-style list containing all fourteen exact actions, grouped visually after the four Microwave and four Shady Guy rarities. The palette scales down when necessary so every row remains reachable inside the active map viewport. A two-panel family/submenu alternative can still be tried later if the complete list feels too tall in play.
- The user selects by hovering and confirms by releasing the marker hotkey. The flyout remains visual/click-through and reads the global cursor; it must not accept a mouse click, take focus from the game, or break the held `Tab` state.
- Releasing a held palette outside a valid entry, closing Full Map, changing run/map identity, or invalidating the map rectangle cancels without creating a marker.
- Opening the editor does not require the game to be paused. The user may press `Escape` first when more time is needed, then hold `Tab` and use the same placement flow.
- Tapping the same action within `12 px` of its manual marker toggles that marker off, providing a lightweight undo without a separate edit mode. Dragging existing markers is deferred unless acceptance testing proves that toggle-and-replace is insufficient.
- Convert manual screen placement immediately back to world X/Z and retain `manual` provenance in the same run-scoped ledger.
- Other palette layouts may be prototyped later if the two-panel flyout tests poorly, but they are alternatives inside this one mode rather than separate manual modes.

Implemented architecture:

```text
MapMarkerMemoryClient
  -> always resolves FullMap/player/stage state for manual projection
  -> resolves currentInteractable/class/Transform/subclass state only when opted in
  -> resolves live FullMap state and exact RectTransform viewport

MapMarkerTracker
  -> owns the active-run discovered-object ledger
  -> deduplicates pointers and applies lifecycle/reset rules
  -> converts manual screen anchors back to world coordinates

core.map_markers
  -> converts exact world coordinates to full-map overlay pixels
  -> defines actions, settings normalization, palette geometry, and clamping

MapMarkerLayer + MapMarkerHotkeyController
  -> renders markers while the full map is open
  -> polls configured keyboard/mouse bindings and renders the held palette
  -> remains click-through in automatic and manual modes
```

- The tracker and memory/projection code remain Qt-free; the QWidget receives immutable snapshots on the GUI timer.
- The dedicated reader starts only when both In-Game Overlay and Map Activity Markers are enabled. It remains necessary for manual FullMap projection, but its automatic detector branch stays off unless the separate checkbox is enabled. It is not attached to the slower player-stat snapshots.
- Complete production polling remained below `1 ms` in the measured 500-sample worst case, so the current GUI-thread timer avoids an unnecessary worker/signal boundary. Revisit this only if later machines show visible timer stalls.
- Disabling the overlay closes the private read-only process handle, clears the run ledger and palette, and stops the `25 ms` timer.

Resolved research gates for the current game build:

- `[Resolved]` Live FullMap lookup, held/released `Tab`, map-open reference count, stale multicast subscribers, and fail-closed missing state.
- `[Resolved]` Exact common Component Transform reads for allowlisted activities.
- `[Resolved]` `QueueRevealFog` world projection and the real `mapDisplayTransform` content rectangle.
- `[Resolved]` Separate held-Tab `FullMap.mapDisplayTransform` and `Escape -> Tab` pause `MapRender` viewport chains, including runtime selection and boundary clipping with the same FullMap instance.
- `[Accepted]` Marker alignment has been confirmed in game on both the held-`Tab` map and the large `Escape -> Tab` map for the current validation layout.
- `[Resolved]` One-observation discovery, pointer deduplication, `25 ms` cadence, and competing unsupported interactables.
- `[Resolved]` Per-class lifecycle for Microwave, Shady Guy, Magnet, Moai, Challenge, and Boss Curse.
- `[Resolved]` Scope identity includes FullMap, `MyPlayer.Instance`, `MapController.currentStage`, and stage index; a new run or in-run stage transition clears all markers.
- `[Resolved]` Automatic discovery is opt-in/default-off; disabling it clears only automatic markers, preserves manual markers, and skips the detector/currentInteractable/lifecycle path.

Remaining in-game acceptance checks:

- Verify automatic icon alignment and lifecycle visually for several objects in one ordinary run, including a final Microwave craft and item collection.
- Toggle automatic discovery off and on during one stage; confirm the summary changes between `Manual only` and `Auto on`, automatic markers disappear when disabled, and manual markers remain.
- Transition to the next stage and then start a second run without restarting BonkScanner; confirm that no marker crosses either boundary.
- Exercise keyboard, Middle Mouse, Mouse 4, and Mouse 5 assignments where available; compare quick tap with the `350 ms` hold palette while `Tab` remains held.
- Verify palette inward clamping at all four map edges, cancellation when the map closes, manual toggle-off, and automatic replacement of a nearby manual same-family marker.
- Repeat the visual alignment pass at another resolution/UI scale and on map variants that materially change the FullMap layout, especially Graveyard crypt/main-map transitions.
- Verify the dark pictograms for White Microwave, White Shady Guy, and Moai in game, and repeat the already accepted two-map alignment check after any material map-layout or projection change.
- After a game update, revalidate TypeInfo RVAs, offsets, enum values, common Transform layout, and class names before treating the feature as compatible.

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
