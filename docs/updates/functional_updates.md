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

Status: `[Implemented]`

Goal:

- Add an automatic announcer for the Twitch bot that triggers when the player picks up "The One Ring" (in-game name: "Golden Ring").
- Support multiple randomized messages to keep the chat reaction fresh.

##### What shipped

Two phrase pools, on every map: one for the first ring, one for every duplicate
after it. Six phrases and five respectively, one per line, drawn at random with
the recent draws excluded.

- `TwitchBotWorker._check_one_ring_announcement` ([src/twitch_bot.py](../../src/twitch_bot.py)), called from the socket loop beside `_check_stage_transitions`.
- Config: `one_ring_announcements` (default on), the `one_ring_announcement` and `one_ring_duplicate_announcement` template pools, and `announcer_recent_lines`, all in `DEFAULT_TWITCH_BOT` ([src/app/config.py:163](../../src/app/config.py:163)). Checkbox in the Announcements card; two multi-line editors in the command dialog's Announcers tab.
- Tags: `{streamer}`, `{stage}`, `{time}`, `{count}`. `SafeFormatter` renders an unknown tag as `--`, so a typo costs a dash rather than the announcement.

**`{streamer}` only inside Gollum's voice.** `target_channel` falls back to
`username`, so by default the bot posts *from the streamer's own account* — and a
plain narrator line like "X has found The One Ring" then reads as X describing
themselves in the third person. That is what removed the two lines this pool used
to have; the remaining four that name `{streamer}` are all Gollum speaking, where
naming the ring-bearer is the character rather than self-reference. Judge a new
line by that test, not by whether it contains the tag.

Two things left for later: `{streamer}` renders `target_channel`, which is a
lowercase login rather than the display name Twitch also returns at auth; and
`username != target_channel` is a free, exact test for "a separate bot account is
posting", if a third-person register is ever wanted as its own pool. Do not try to
make one tag serve both — "you has found" is where that ends.

**Pools are newline-separated strings, not lists.** Every template in that dict is
coerced with `str()`, and a one-line value is a valid pool of one — so the
original single-phrase config needed no migration path at all. The pre-pool
default is in `LEGACY_ONE_RING_TEMPLATES` and is upgraded on load, because a
config still holding exactly it was never edited by hand and a pool of one reads
as a broken randomiser.

**Flat odds, no weights.** The ring turns up on the order of once a session, so a
line weighted at a tenth would simply never be read; with an event this infrequent
the useful knob is variety per sighting.

**Two exclusions of different scope, and the scopes are the whole design:**

- *Within a run — absolute.* Nothing repeats until every variant has been spent,
  then the cycle starts over and the record is cleared. This is the half that
  matters for the duplicate pool, where one run can draw several times: without
  it a five-line pool lets ring 4 repeat ring 2. Held in
  `_pool_lines_used_this_run`, cleared when `run_id` changes.
- *Across runs — a preference.* The last `len(pool) // 2` draws are avoided **when
  possible**, and yield the moment the run-scoped rule disagrees. Long enough that
  a new run does not open by repeating the last one, never long enough to force a
  repeat inside a run or to corner a hand-shortened pool.

The across-runs half **is persisted** to `TWITCH_BOT["announcer_recent_lines"]`:
an in-memory memory would be cleared between streams — before it was ever
consulted — leaving a plain uniform draw. Safe to write from the bot thread:
`user_config["TWITCH_BOT"]` **is** `config.TWITCH_BOT` ([src/app/config.py:1050](../../src/app/config.py:1050)) and
`save_config` takes `config_lock`. Both memories hold phrase text, so editing a
line drops it out by itself.

One test here is white-box on purpose. "A new run forgets what the previous one
spent" has **no** behavioural expression: a pool the previous run left spent is
re-filled by the exhaustion branch anyway, so the observable sequence is identical
either way — a tamper run proved the behavioural version vacuous. It asserts on
`_pool_lines_used_this_run` instead.

**Every duplicate line must hold for any count above one.** "A second precious"
reads as a bug on the third ring; a line either names `{count}` or says nothing
about the number.

Decisions worth keeping:

- **Read off the 1 s lane, not the 10 s snapshot.** The inventory is read every
  second by the `passive_items` task ([src/app/refresh_tasks.py:204](../../src/app/refresh_tasks.py:204)), but that lane
  never appends a snapshot — it publishes `_fast_items` and folds its deltas into
  the tracked-item state, so `RuntimeStateSnapshot.latest_snapshot.items` is the
  10 s copy. `RuntimeStateSnapshot.fast_items` was added to carry the fast one to
  the boundary, beside `luck`, which already rides that same pass; the announcer
  prefers it and falls back to the snapshot when it is `None`. Without this the
  message trails the pickup by up to ten seconds on stream.
- **Level-triggered on the inventory, not edge-triggered on a pickup.** An edge
  would have to survive a torn read, a skipped pass or a reconnect to fire at
  all. "The bag holds more rings than have been announced" stays true on every
  tick until it is answered, so a read that fails costs a tick rather than the
  announcement.
- **The latch is a count, not a flag.** It is what lets ring 2 be new while ring 1
  is old. Two rings appearing between one tick and the next is still one event and
  draws the first-pickup line only — the duplicate pool fires on an *observed*
  increase past what was announced.
- **The first usable read of a run seeds the latch.** Whatever the inventory
  already holds was not picked up under the bot's watch, so a mid-run connect --
  or a reconnect after a dropped socket -- stays quiet. An *unavailable* read is
  not allowed to seed, because "no rings" from a failed read would announce on the
  next successful one.
- **No map gate at all.** The first version was Forest/Desert-only, gated on a
  *fresh* `powerup_map_context` that was not Graveyard — scope control, not a
  requirement. Nothing here ever depended on the map: the inventory and `run_id`
  are the same facts everywhere, and `run_id` holds across Graveyard's crypt and
  boss-room transitions — which is exactly the property the Event Timer item
  below records as making those transitions invisible to seed and pointer — so
  the latch cannot double-fire there. The gate was removed rather than inverted,
  which also drops the wait for a context that no longer decides anything.

Matching is via `fold_item_match_name` ([src/core/tracker/items.py:70](../../src/core/tracker/items.py:70)), which collapses all four spellings the item reaches this code under -- `GoldenRing`, `Golden Ring`, `The One Ring`, and the game's `No Implementation` placeholder -- onto one key. Do not replace it with a literal list here; it would drift from `core/item_metadata.py`.

Covered by `OneRingAnnouncerTests` in `src/tests/test_twitch_bot.py`, tamper-tested against reinstating the map gate and against removal of the seeding branch, the fast-lane preference, either exclusion, the exclusion's persistence, the duplicate pool, and the counting latch.

##### Remaining

- Condition-driven lines, **if** they are ever wanted: a pickup on Stage 1, or before 5:00, is a genuinely different event and `current_stage_index` / `game_time_seconds` are both already on the runtime snapshot. Do this as a *condition* rather than a weight — a weighted line on an event this rare is a line nobody reads.

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

### Support & Community

#### 1. Supporters List in the Footer

Status: `[Partial]` -- **the UI is built, tested and unreachable. Only the data is missing.**

The visual half was written deliberately ahead of the data, because it is the
perishable half: reproducing this popup from a description later is far more
work than writing the twenty lines that read a JSON file. What remains is a
reader and a single call.

The seam is `FooterView.set_supporters` ([src/ui/footer.py](../../src/ui/footer.py)).
Hand it names and the footer link becomes `♥ N supporters` and the popup grows
the list; hand it nothing and the strip is exactly what ships today. **Nothing
calls it in production.** `src/tests/test_support_popup.py` drives it directly,
so the widget is covered rather than merely unused -- including the empty case,
malformed entries, the tier marker, the cap, and going back to empty.

It accepts plain strings and mappings both, so a `supporters.json` needs no
shape negotiation: `"Nyxaria"` and `{"name": "Nyxaria", "tier": "gold"}` are
both valid rows, and any truthy `tier` marks the name.

Design reference:

- [redisign_ui/support_footer_proposal.html](../../redisign_ui/support_footer_proposal.html) — open in a browser. The whole main window is drawn to scale around the strip, so the proposal can be read in context rather than as a floating snippet.
- Section **4, "Надстройка: счётчик вместо слова «Support»"**, is this item. Sections 1-3 are the footer that already exists; section 5 records the header heart-icon variant and **why it was rejected** — do not resurrect it without reading that section first.
- The supporters list inside the Help dialog appears only as prose in this document, not in the mockup. An earlier revision of that file drew it; the rewrite that matched the mockup to the real window dropped it.

Goal:

- Replace the footer's `Support` caption with `♥ N supporters` once there is a list to back it, and show the names on click.
- Keep it a statement of fact rather than a request. "14 people support this" reads differently from "Support", and the difference is the entire argument for the feature.

What already exists (on `visual_redesign`):

- The strip itself, `#appFooter`, 28 px, built by `build_footer` ([src/ui/footer.py:226](../../src/ui/footer.py:226)) and added to the root layout in `build_layout` ([src/ui/layout.py:221](../../src/ui/layout.py:221)).
- `SupportPopup` ([src/ui/footer.py:70](../../src/ui/footer.py:70)) — a `Qt.Popup` frame holding a title, one line of context and the Patreon/Ko-fi buttons. **This is the widget that grows into the list**; it is not a new construction. Its card is pinned to 268 px ([src/ui/footer.py:98](../../src/ui/footer.py:98)) because the width is what sets the note's wrap.
- The four URLs, unchanged, in [src/app/config.py:243](../../src/app/config.py:243).

##### What blocks it

The UI is a few dozen lines on top of what is already there. The data is the actual work.

- **The Patreon API is not an option.** It needs OAuth and a refresh token, and the token would have to live inside a binary that is handed to everyone. That means either a credential in the build or a server in between; neither is worth it for a name list.
- So the source is a hand-maintained `supporters.json`, updated per release. That leaves one real decision — how it reaches the running app:

| Delivery | Freshness | Network cost | Notes |
| --- | --- | --- | --- |
| Bundled in the build | Frozen until the next release | None | Safest. Nothing to fail offline. |
| Fetched from `raw.githubusercontent` | Current between releases | One extra GET | Must ride the existing update check (see below), never a new startup path. |
| Both — bundled floor, fetched override | Current, with an offline floor | One extra GET | Most code of the three; degrades to the bundled list when the request fails. |

- **If it is fetched, it must not sit on the path to the first window.** That rule is why commit `d3796f0` exists. The cheapest correct place is a second GET beside the update check, which already runs on a daemon thread and already talks to GitHub: `start_update_check` ([src/ui/dialogs/update_prompt.py:9](../../src/ui/dialogs/update_prompt.py:9)) → `check_and_update` ([src/app/update_flow.py:18](../../src/app/update_flow.py:18)) → `GITHUB_API_URL` ([src/infra/updater.py:16](../../src/infra/updater.py:16)). `check_and_update` already carries an optional `report` callback back to the GUI thread through `schedule`; a supporters payload should use the same hop rather than inventing a second one.

##### Degradation rules (non-negotiable)

- No list, empty list, missing file, or failed request → the footer shows plain `♥ Support` exactly as it does today. **Never** `♥ 0 supporters`, never a spinner, never an error. An empty card reads as a broken feature; the absence of the counter reads as nothing at all, which is correct.
- The popup must never show a "loading" state. It is opened by a click, and by then the answer is either known or the counter was never shown in the first place.

##### UI specification

**Implemented as described below -- this section is now the record of what was
built and why, not a brief.** Read it before changing any of it; several of
these values are the answer to a measurement rather than a preference.

Footer link, `#footerSupportLink`:

| State | Caption | Colour |
| --- | --- | --- |
| No data | `♥  Support` | `#93726E`, heart `#A0635F` |
| Data | `♥  14 supporters` | same |
| Hover, either | — | `#FF6F61`, underline `#4B2B2F` |

The hover colour is Patreon's own, and is deliberately the *only* place it appears in the strip. The resting colour is warmer than the neighbouring `#8A94A3` links by exactly enough to be findable and not enough to compete with the header's status dot, which is the one element in the window that speaks in colour. This is the balance the mockup's section 5 argues at length; keep it.

Popup, `SupportPopup`:

- Card widens from 268 px to 400 px -- `NARROW_WIDTH` and `WIDE_WIDTH` on the
  class. The narrow width is set by where the note wraps, the wide one by two
  columns of display name.
- `MAX_LISTED = 24`. Names past it are not drawn and the count still includes
  them, so the note reads "Thank you, and 6 more". A scroll bar inside a popup
  is a worse answer than a number.
- Tiers sort to the top; within a tier the given order is preserved rather than
  alphabetised, because a hand-maintained list means something by its order. Surface `#101419`, border `#2A3542`, radius 11 — unchanged, these are the existing `#supportPopupCard` values at [redisign_ui/bonkscanner_redesign.qss:1488](../../redisign_ui/bonkscanner_redesign.qss:1488).
- Title `#B9C2CE`, 12.5 px, weight 800. Note `#8A94A3`, 11 px.
- Names in a two-column grid, 11.5 px, `#B9C2CE`, ellipsised on overflow — a display name is user-supplied text and can be arbitrarily long.
- A higher tier, if tiers are used at all, is `#FF6F61` and weight 700 with a `♦` prefix. One distinction, not a ladder; three tiers in a footer popup is a pricing page.
- The Patreon and Ko-fi buttons stay at the bottom, below a `#1B222B` rule. They keep `#PatreonButton` / `#KofiButton` ([redisign_ui/bonkscanner_redesign.qss:1321](../../redisign_ui/bonkscanner_redesign.qss:1321)) so the popup and the settings card cannot drift apart.

Overflow: when the list outgrows the popup, move it to a card in the Help dialog — names in three columns, all four platform buttons — and leave the footer counter as the entry point. Help is where a long block costs nothing, because people open it deliberately. Do **not** put the card on a main-window tab: on Logs it is pushed off-screen by the log within seconds, and everywhere else it takes space from data.

##### Open decisions

- Delivery mechanism — one of the three rows above.
- Whether tiers exist at all, or the list is flat.
- Whether the count includes past supporters or only current ones. `N supporters` is read as "right now", so a lapsed-inclusive count needs different wording.
- ~~`KOFI_SUPPORT_URL` is a Ko-fi **shop item** rather than a donation page.~~
  Resolved: it points at the profile now.

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
