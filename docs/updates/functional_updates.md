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
