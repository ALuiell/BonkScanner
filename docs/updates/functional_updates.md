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

#### 5. Item Rarity Loot Tracking (`!luck` / Luck Rarity Widget / OBS Overlay / Live Stats)

Status: `[Open / Mechanics Verified]`

Goal:

- Compare the rarities the player *actually* received against the rarities the game's own model *expected* to give them at the Luck they had at each moment, and expose that through the existing In-Game Overlay `Luck Rarity` widget, a mirrored OBS Overlay widget, a Twitch command, and a Live Stats card.
- Because Luck (`PlayerStatsNew` stat ID `30`) scales continuously during a run, expected counts cannot be computed retrospectively from end-of-run Luck. For every acquisition $j$ the instantaneous $\text{Luck}_j$ is captured and expectations accumulate:
  $$E[R_k] = \sum_{j=1}^{N} P(R_k \mid \text{Luck}_j), \quad R_k \in \{\text{COMMON}, \text{UNCOMMON}, \text{RARE}, \text{LEGENDARY}\}$$
- **Scope is the current run only.** Nothing accumulates across runs or across an app session; Compare Runs is where multiple runs are put side by side.
- The widget is an extension of `Luck Rarity`, not a new concept: that widget already renders $P(R_k \mid \text{Luck})$ for the current instant. This adds the cumulative actual-vs-expected line underneath it.

##### Verified Game Mechanics (Megabonk `v2.1.7`)

Evidence levels: `[asm]` disassembled from `GameAssembly.dll`; `[dump]` declaration in the IL2CPP metadata dump; `[game]` direct in-game observation; `[live]` our own earlier live capture; `[assumed]` accepted without verification, low risk.

**Rarity roll.** The rarity model our `Luck Rarity` widget already implements is confirmed correct, instruction for instruction.

- `[asm]` `Rarity.CalculateRarityWeights(float[], float)` — RVA `0x42D1B0`. Computes `S = ln(luck + 1.0) * 1.5` (`addss` 1.0f at `0x18042D1B6`, `logf` at `0x18042D1C9`, `mulss` 1.5f at `0x18042D1FF`), then `W_i = Base_i * 1.5^(-k_i * S)` via `powf` at `0x18042D235`, then normalizes by `Enumerable.Sum`.
- `[asm]` `k_i = length - 1 - i`, computed in the loop from the array length rather than a table — hence exactly `3 / 2 / 1 / 0`.
- `[asm]` Base weights are immediates written into the array by `Rarity.GetItemRarity` (RVA `0x42D3F0`): `0x428C0000` = **70.0**, `0x41700000` = **15.0**, `0x40C00000` = **6.0**, `0x3FC00000` = **1.5**.
- `[asm]` The weight array is **exactly 4 elements**. `Corrupted` and `Quest` do not participate in the normalization, so dividing by the sum of four is correct.
- `[asm]` Luck is passed as a **fraction**, not a percentage (`0.5` means "+50%"): `mov edx, 0x1e` (stat 30) at `0x1804539F7` in `InteractableChest.OpenChestImplementation` (RVA `0x453990`), result fed straight into `addss xmm1, 1.0f`. Our code passes raw `stat.value`, which is already a fraction — correct.
- `[asm]` The game applies no clamp; `luck < -1` would yield `NaN`. Our `max(luck, -0.999999999)` is more defensive than the game and unreachable in practice.
- `[assumed]` Tier selection is a cumulative sum against `Random.Range(0,1)` over indices `0 -> 3`.
- `[game]` If the drawn tier's pool is empty the game falls back to an adjacent tier. Unreachable in practice: duplicates stack rather than leaving the pool, so a tier can only empty through deliberate mass banishing or lobby-disabling.

**Rarity tiers and naming.** The game and this project use different names for the same four droppable tiers. There is no fifth droppable tier.

- `[dump]` `EItemRarity`: `Common=0, Rare=1, Epic=2, Legendary=3, Corrupted=4, Quest=5`.
- `[dump]` `ERarity`: `New=0, Common=1, Uncommon=2, Rare=3, Epic=4, Legendary=5`.
- Our `core/item_metadata.ITEMS` uses `COMMON / UNCOMMON / RARE / LEGENDARY`. The correspondence with `EItemRarity` is positional: our `UNCOMMON` is the game's `Rare` (weight 15), our `RARE` is the game's `Epic` (weight 6). **Not yet verified per item** — see Open Items.

**Item sources.** Every source below yields items; only the first group uses the Luck model above.

| Source | Rolls via `GetItemRarity(luck)` | Evidence |
| --- | --- | --- |
| Paid map chest (`EChest.Normal`) | yes | `[asm]` |
| Free map chest (`EChest.Free`) | yes | `[asm]` |
| Crypt chest (`EChest.FreeCrypt`) | yes | `[asm]` |
| Ghost chest (`EChest.Ghost`) | yes | `[asm]` |
| Chest dropped by mob / elite / boss / cactus / egg | yes | `[asm]` — same `InteractableChest` path |
| Skeleton King Statue, Character Fight | yes — they spawn an enemy whose death drops a chest | `[assumed]` |
| Corrupt chest (`EChest.Corrupt`) | **no** — forces `EItemRarity.Corrupted`, which is outside our four tiers and drops out of both sides | `[asm]` |
| Shady Guy (merchant, one item chosen from three offers) | **no** — `Rarity.GetShadyGuyRarity(float, float[])`, RVA `0x42DA60`, separate weights | `[dump]` |
| Moai statue | **no** — own model, see below | `[game]` |
| Microwave | **no** — not a roll at all: the player names the item to create (`UseMicrowave(EItem eItemToCreate)`) and pays for it with others of the same tier | `[game]` |

- `[game]` **Moai does not spawn a chest.** The player opens the statue, is offered 2 or 3 items, picks **one**, and it goes straight to the inventory. Its Luck model differs by statue mode:

  | Mode | Options | Effective Luck |
  | --- | --- | --- |
  | 0 | 2 | `Luck * 0.5` |
  | 1 | 3 | `Luck * 1.0` |
  | 2 | 3 | `Luck * 1.5` |
  | 3 | 3 | ignored — always Legendary |

- `[game]` **Microwave** takes **one item per use and returns one** of the same tier. A microwave's own rarity sets how many uses it has — green 3, blue and purple 2, legendary 1 — and it is spent once they are gone. `[dump]` `InteractableMicrowave.usesLeft` is at `+0x84`. The audit's reading of those 3/2/2/1 figures as a *per-craft item cost* was wrong; they are the appliance's use count. Measured live 2026-07-25: three crafts, one item consumed each, `numUsed` moving only after the third.
- `[game]` Graves and Pots do not yield items.
- `[game]` No other item source is known to exist.
- `[asm]` `Clover` and `Beacon` have no special branch in the roll; `Clover` simply raises the Luck stat. Difficulty, stage index and map type do not affect the weights.
- `[assumed]` One chest opening yields exactly one item. Duplicates stack (`ItemBase.amount`) and remain full rolls. `Key` (id 0) is in the Common pool; `CageKey` (69) and `CryptKey` (81) are `EItemRarity.Quest` and excluded from drop pools — consistent with `rarity=None` in our table. Banishing removes an item from its tier pool but does not alter the weights.

**Interactable counters.** These decide what we can and cannot observe, and several earlier assumptions about them were wrong.

- `[dump]` `InteractablesStatus.InteractableStatusContainer`: `numTotal` at `+0x10`, `numUsed` at `+0x14`. Our reader maps these to `StatValue(current=numUsed, max=numTotal)` correctly.
- `[game]` **The chest counter only ever counts chests spawned at map generation.** Forest: 3 maps x 46. Graveyard: 69 on the main map plus 6 per crypt.
- `[live]` Free *map* chests do increment it — this is what the existing `!chests` breakdown `free = opened - chestsBought` rests on.
- `[game]` **Dropped chests are invisible to every counter**: they do not increment `numUsed`, do not raise `numTotal`, and do not touch `chestsBought` or `chestsPurchased`. There is currently no way to observe that a dropped chest was opened.
- `[game]` **`numUsed` counts exhausted or completed interactables, not individual interactions.** The microwave's entry moves only once the appliance is spent (after 3 / 2 / 1 crafts), and the Shady Guy's moves once when trading ends, after all purchased items are already in the inventory. `OnInteractableUsed` may well fire per interaction; what is verified is that the readable field does not.
- `[assumed]` Counters reset on every map generation, consistent with the known per-stage reset of `MapStat.CHESTS.current`.
- `[live]` `chestsBought` (RunStats) and `chestsPurchased` (MoneyUtility) are cumulative for the run and survive map transitions.

##### Detection Design

Because dropped chests cannot be observed, the count of chest openings cannot drive the maths. The design is inverted: **every confirmed item gain is treated as a roll**, and only the three sources with a different model are excluded. No per-item source attribution is required.

**Microwave** — the most reliable of the three signals, not the weakest. Its trigger is a **decrease in an individual item's count**, not a drop in the total — a craft consumes 1 and yields 1, leaving the total unchanged, so a total-based signal would miss every craft.

- `[game]` **One item other than the microwave reduces a count: `Za Warudo`.** It breaks and leaves the inventory when the player is killed, granting a second life. It is the only self-consuming item in the game. Treated as a craft it would raise a phantom `LEGENDARY` debt and silently swallow the next genuine legendary, so `actual` would undercount while `expected` did not. It must be named explicitly and never open a debt.
- On a decrease, record the consumed tier as a **debt**, and let the next gain of that tier settle it without counting. Deliberately not a time window: `[game]` the craft takes 2-3 s but its output lands on the ground, so it only reaches the inventory when the player walks over it. Measured gaps of 8.6 / 12.6 / 9.3 s were the player being chased off by mobs and coming back, not craft latency — there is no upper bound to size a window against.
- Mis-settling the debt is harmless. If a chest yields a same-tier item before the player collects the craft output, the debt is settled by the chest item and the craft output is counted instead — and since both carry the same tier, the totals are identical either way. Item identity never enters the maths.
- The one guard needed is for a craft the player never collects: **clear outstanding debts on map generation**. An item left on the floor of the previous stage is not coming, and the interactable counters reset at that boundary anyway.
- No identity resolution is needed. Two same-tier appearances in one window are not ambiguous for our purposes: we count rarities, not items, so it does not matter which of the two is labelled the craft output — either assignment yields the same tally. Excluding the whole window instead would discard a chest legitimately opened during the craft.
- If no appearance of that tier arrives, close the window with no exclusion (the craft was interrupted).
- `[game]` The craft output is always **the same tier as the input** — a white item in yields a white item out — so keying the subtraction on the consumed tier is safe. The microwave never raises a tier.

**Shady Guy** — `[game]` the merchant sells exactly one item, chosen from three offers, and its counter fires once after the item is granted. The exclusion therefore drops the single **preceding** gain. `[game]` The counter does not fire if the player browses and leaves without buying, so a window never opens spuriously. Trading takes about 5 s, so a few seconds of lookback is enough. If it ever proves too greedy, bound it by `DetectInteractables.currentInteractable` rather than by elapsed time.

**Moai** — `[game]` the statue grants exactly one item, picked from 2 or 3 offers, and its counter fires at the interaction, before the grant. The exclusion drops the single **following** gain.

All three sources therefore share one rule — **one increment, one excluded gain** — differing only in direction. At the observed acquisition rate of roughly 1.8 per minute, two gains landing inside the same narrow window is rare, so mislabelling one of them is both uncommon and cheap.

**Window sizes, measured live on 2026-07-25** (`tools/probe_loot_sources.py`, 250 ms sampling):

| source | direction | window | measured gaps |
| --- | --- | ---: | --- |
| Moai | forward | 3 s | 0.75 / 1.00 / 1.77 s |
| Shady Guy | backward | 2 s | same tick, twice (<= 0.25 s) |
| Microwave | untimed debt | — | see above |

Moai's counter fires when the player picks, not when the statue opens, so deliberation never lands in the gap — the earlier estimate of 20 s was wrong by an order of magnitude. The merchant's counter and its item arrive together, so its window only needs to absorb the case where a 1 s poll splits them across two ticks. Both of those items go straight to the inventory, which is why their gaps are short and consistent; only the microwave's output waits on the ground, which is why it gets a debt rather than a window.

At the production 1 s cadence every one of these collapses to "this tick or the next", so the implementation needs a short pending queue, not a multi-second scan.

**Ambiguity rule** — where a window still cannot be resolved, the affected gains are dropped from **both** `actual` and `expected`. Consistency between the two numbers matters more than completeness.

**Unresolvable rarity is dropped from both sides.** If a gained item's rarity cannot be resolved against `ITEMS`, it contributes to neither `actual` nor `expected`. Accumulating expectation for an item whose actual tier we cannot record would drift the two apart. This is what makes chest *source* genuinely irrelevant: an item from a Corrupt chest carries `EItemRarity.Corrupted`, which is not one of our four tiers, so it falls out of both sides on its own and needs no special handling. The rule matters more for game updates — new items our table does not know yet would otherwise skew the numbers silently.

**Sanity check** — map-spawned chest openings *are* countable, so item gains must always be at least that number. Logging both and watching the excess is a cheap standing check that no unknown item source exists. This uses a counter we already read.

##### Implementation Notes

- **One task reads the whole loot sample.** Items, the interactable counters and Luck are consumed by the existing `passive_items` task in a single pass, so all three carry one timestamp and are **coherent by construction**. The "did the counter move before or after this gain" question and the "which Luck applied to this roll" question both stop existing rather than being solved. This is what the named sources are for: within one `RefreshTickContext` a key resolves once and every consumer in that pass sees the same value.
- **Luck needs a narrow source of its own.** It is currently only available inside `PLAYER_STATS` on the 10 s full snapshot. Add a reader for stat `30` alone under its own key; reusing `PLAYER_STATS` would pay for a full per-stat walk on every fast pass. Moving it also fixes the In-Game Overlay's Luck widget lagging up to 10 s, which is worth having on its own.
- **The interactable counters cost no extra read.** `get_map_activity_values` already walks the whole `InteractablesStatus` dictionary and returns every key, `Moais` / `Shady Guy` / `Microwaves` included. It resolves today through `MAP_ACTIVITY_VALUES` on the 10 s snapshot ([player_stats_refresh.py:288](../../src/app/player_stats_refresh.py:288)), whose consumers are `chests_total`, `pots_total` and `PowerupMapContext.from_activity_max` — **not** Stage Summary, which does not use this source. Adding a second consumer is exactly the case the pass cache exists for, and reading it every second also fixes `PowerupMapContext` being absent for the first ten seconds of every run.
- **Optional: skip the fast walk once a map is spent.** `numUsed == numTotal` for all three keys means no further exclusion window can open on this map, which fits `RefreshTask.required` in a few lines. Worth having, but do not expect much from it: the counters reset on every map generation, so it re-arms per stage, and it never fires at all if the player leaves one statue or merchant untouched.
- **Luck sampling needs no further precision.** `[game]` A chest deposits its item instantly on interaction, so only our own ~1 s poll separates the roll from the observed gain — and no Luck source moves the stat enough in one second to shift the rarity probabilities beyond hundredths of a percent. With Luck read in the same pass as the gain there is nothing left to correct for; do not build a matching buffer.
- **`process_item_deltas` must learn to handle decreases** before any of this can work — see Build Order below.
- **Late attach is a hard unavailable state**, stricter than `!chests`. Attaching mid-run leaves both `expected` *and* `actual` wrong, since items already held are absorbed into the baseline by `initial_item_increase_candidates`. The widget must say the run is not measurable rather than show partial numbers.

##### Deliverables

**Twitch `!luck`** — a single message, pipe-separated like every other command, pairing each tier's current chance with what it has actually produced:

```
Luck: Legendary 54.88% - 116 (exp 118) | Epic 29.28% - 78 (exp 78) | Rare 9.76% - 38 (exp 36) | Common 6.08% - 45 (exp 45)
```

When the run is not measurable — the app was not running from its start — the actual and expected halves drop out and only the chances remain:

```
Luck: Legendary 54.88% | Epic 29.28% | Rare 9.76% | Common 6.08%
```

- The chance half always works, since it depends only on the current Luck and not on when the app attached. Omitting the rest leaves a shorter command rather than a broken-looking one; `!chests` keeps its own `Expected: --` instead, because there the value sits inside one whole message and a gap would read as a fault.
- **Chat uses the game's own rarity vocabulary — `Legendary / Epic / Rare / Common`** — not our internal keys. Our `ITEMS` labels the middle two `UNCOMMON` and `RARE`, one tier down from what the game calls them, which is invisible where colour carries the meaning and actively wrong in plain text: a viewer reading "Rare" pictures the blue tier while we mean the purple one. Chat is the only surface with words, so it is the only place this mapping is needed.
- No abbreviations. The line runs about 120 characters against a 500-character limit, so shortening buys nothing and costs readability.

**In-Game Overlay** — extend `LuckRarityOverlayWidget` with a `Show Expected Frame` toggle alongside the existing `show_bar`, adding a compact panel of actual-versus-expected counts under the probability row.

Layout, all of it settled against a real game frame on 2026-07-25 rather than against a mockup:

- **Two selectable layouts, `expected_layout: "column" | "row"`.** `column` is a two-by-two block of `● 116 (118)` with the dot carrying the tier colour; `row` is a single line of `116/118` per tier, no dots. They trade roughly 45 px of screen against legibility — a real user preference, not an unmade decision — and share every other rule, so the branch is one arm in the HTML builder. Default to `column`: someone enabling the frame for the first time should meet the readable form, since a cramped first impression gets the whole frame switched back off.
- **Either layout stretches across the widget's width**, first cell flush left, last flush right. Growing numbers eat the centre gap instead of changing the footprint. `row` works without dots precisely because of the stretch — at ~38 px of gap the whitespace separates the groups the way the dot does in `column`. Keep a minimum centre gap so cells can never touch.
- **Anchor to the percentage row, not to the bar.** `show_bar` can hide the bar, so anchoring to it leaves the block without a reference in two of the four toggle states. The percentage row is always drawn. In Qt: give the block the label's width inside the shared `QVBoxLayout` rather than computing offsets. On the captured frame the percentage row measures slightly wider than the bar and the cause is not determinable from a screenshot — verify all four toggle combinations by eye.
- **Never tie the figures to the bar's segment geometry.** The bar is proportional, so a tier at 1% is a segment one pixel wide and nothing can sit under it. Only the tier order (`LUCK_RARITY_ORDER`) and the colours are shared with it.
- With the bar hidden, `column` reads airier than it does with the bar present — the bar was doing structural work, filling the span and tying the two text rows into one block, and without it the centre is visibly empty while `row` stays tight. Cosmetic rather than broken, and worth leaving alone in a first version; if it grates, centring each column within its half instead of pinning to the extremes closes the gap at the price of one conditional.
- **Actual in the tier colour, expected in the muted grey already used for the `|` separators.** A darker tint of the tier hue is unreadable over grass and wood; white outranks the actual figure when the hierarchy should run the other way. One grey for all four beats four hand-picked shades.
- **One decimal below 10, whole numbers above.** Dropping tenths outright turns `1 (0.8)` into `1 (1)`, reading as "exactly on expectation" when the player was ahead, and `0 (0.4)` into `0 (0)`, as if nothing had been expected.
- Stress-tested on the same frame: `column` holds a 147 px centre gap at `999 (999)` and 87 px at an unreachable four digits; `row` has 38 px today and 8 px at `999`. The largest single-tier count across the real recordings was 116.
- No rarity words anywhere in the overlay, so the naming question that governs chat never reaches it and the two surfaces cannot disagree.
- **Enabling the frame or switching layout changes the widget's height**, which trips `_keep_widgets_inside_bounds` and makes a widget near an edge jump. One fix covers both, and the default position should sit high enough that the extra rows do not land on the item hotbar.

**OBS Overlay** — the same content, colours, tier order and both toggles, with its own `expected_layout`. Configured **separately** from the in-game widget rather than mirroring it: "show it to chat but not to me" has to be expressible, and the two surfaces have genuinely different space budgets.

**Live Stats** — a new `Loot` tab holding the existing chest card, moved across unchanged, plus a new rarity card beside it. Leave an empty placeholder card in the slot the chest card vacates in `Stats`, to be filled later.

- The rarity card is four lines, one per tier, each carrying the current drop chance, the actual count and the expectation — the same grouping the Twitch line uses, so the two read alike:

  ```
  Legendary   54.88%     116 (exp 118)
  Epic        29.28%      78 (exp 78)
  Rare         9.76%      38 (exp 36)
  Common       6.08%      45 (exp 45)
  ```

- This card is where the **streamer** learns why the data is unavailable ("app was not running from the start of the run"). Viewers see nothing; the one person who can act on it sees the reason.
- Label its `Expected` apart from the chest card's — expected counts by rarity versus expected key procs — since the two now sit side by side meaning different things.

**Recordings and Compare Runs** — serialize the per-tier actual and expected totals into the recording snapshots so Compare Runs can diff luck between runs, behind its own toggle. This is the most interesting use of the data: a single run's legendary count is mostly noise, and only across runs does a deviation mean anything. Older recordings have no such field, so the comparison needs an explicit missing-value path rather than a zero. The chest breakdown gets the same treatment under a separate toggle — see item 6, where the recording side already exists.

**Twitch Bot settings** — enable/disable and permissions for `!luck` alongside the other commands, in the same shape as the existing entries.

**Visual consistency** is a reuse requirement, not a style guideline. `ITEM_RARITY_COLOR_MAP` and `COLOR_MAP` in `core/item_metadata.py` are already shared by the in-game overlay, the OBS overlay and the GUI cards. Every new block takes its colours from there; anything that hardcodes its own will drift at the first edit.

**Attribution** — surface the model's provenance in a tooltip, so the numbers read as a stated model rather than as our own claim about the game's internals.

##### Chests Stay Their Own Thing

The chest count takes no part in this feature's maths, and nothing about the existing chest tracking changes. Whether a chest was paid for or opened by a Key proc says nothing about the roll inside it — that distinction is what `!chests` exists for, and its `Expected` counts expected *key procs*, an unrelated quantity.

- `!luck` carries **no chest count at all**, only the two lines above.
- Neither overlay shows one either. The game's own HUD already lists `Chests 9/46`, `Moais 3/3`, `Shady Guy 5/5` and `Microwaves 1/1` in the corner, so an overlay copy would duplicate what the player is already looking at.
- The Live Stats chest card moves into the new tab **unchanged**, keeping its current layout and semantics, with the new rarity card beside it.

The one thing to watch is that this puts **two cards labelled `Expected` side by side** meaning different things. Label them apart — expected key procs versus expected counts by rarity — or the first question asked will be why one reads 12.4 and the other 1.4.

The deviation is written as `116 (exp 118)` rather than a signed `+0.6` throughout: a bare delta loses scale, reading identically against an expectation of 1.4 and of 15.

##### Build Order and Tests

Item 7 holds the step-by-step build plan, the prerequisite fix to `process_item_deltas` and the full test list. It is written to be handed to an implementer on its own; this item is the design that plan must not re-open.

##### Offline Validation (2026-07-25)

`tools/replay_loot_expectation.py` replays the model over the recordings in `stats_recordings/`. It accumulates expectation from the disassembled formula against the Luck recorded at each moment, and tallies `actual` through our own `ITEMS` rarity table — two independent paths, so agreement is evidence rather than tautology.

Seven ordinary runs, 1396 acquisitions, Luck sweeping from single digits to `11497%` (where `P(Legendary)` passes 50%):

| tier | actual | expected | sigma | z |
| --- | ---: | ---: | ---: | ---: |
| LEGENDARY | 632 | 630.9 | 16.4 | +0.1 |
| RARE | 335 | 339.7 | 15.8 | −0.3 |
| UNCOMMON | 181 | 163.2 | 11.8 | +1.5 |
| COMMON | 248 | 262.1 | 11.5 | −1.2 |

What this settles:

- The formula, its constants, and the fractional Luck units hold across the whole Luck range, not merely at one point.
- **Our four rarity labels map correctly onto the game's tiers.** A misaligned label would have shown up as tens of sigma over this many samples. The planned live read of `RunUnlockables.availableItems` is no longer needed for that purpose.
- The residual `+1.5` on UNCOMMON is the expected signature of the exclusions the replay does not implement: Moai rolls at `Luck * 0.5` in mode 0 and the merchant uses its own weights, and at high Luck those land in the thin middle tiers. Roughly a dozen such items per run.
- `950k` recorded 77 map chest openings against 277 acquisitions. Three quarters of the data comes from drops the chest counter cannot see, which is the measured form of why the counter cannot drive the maths.

Recordings made with cheats are unmistakable and must be filtered before pooling. Ordinary play sits at 1.7-1.9 acquisitions per minute in every long run; cheated ones start at 2.2 and reach 33/min, usually with one item gaining +99 to +198 in minutes. Pooled over 23 such runs the model "fails" by up to 28 sigma — an artefact of the fixture, not the model.

The script doubles as a regression, but on itself: run against the same fixtures it must keep producing the same table. **Do not expect the live tracker to match it.** The replay reconstructs gains from consecutive 10 s snapshots, so several acquisitions share one Luck sample and the Moai, merchant and microwave exclusions cannot be applied at all — they resolve inside a second. The live tracker has both, and should therefore land closer to expectation than the replay does. A disagreement between the two is the design working, not a defect.

The 10 s recording interval is otherwise harmless to the feature: what gets serialized is the accumulated per-tier totals, computed continuously on the 1 s lane and merely sampled for writing. The interval only sets the granularity of a Compare Runs timeline, which over a two-hour run is ample.

##### Open Items

- Nothing blocking. The exclusion window sizes were measured on 2026-07-25 and are recorded above, and `Za Warudo` is confirmed to be the only self-consuming item.
- No way to detect a dropped-chest opening. **This does not block the feature** — it only limits the context line to "items acquired: N" instead of "chests opened: N".
- Whether `EChest.FreeCrypt` draws from a separate pool is unconfirmed; it does not affect the rarity distribution either way.

##### Superseded Assumptions

Recorded so they are not re-derived. Every claim in the dump-based audits that lacked a disassembly listing and touched observable game behaviour turned out to be wrong; the listings themselves held up.

- The five-rarity scale including a droppable `Epic` distinct from `Rare` — there are four droppable tiers under two different naming schemes.
- "Moai spawns an `EChest.Free`" — reported with a listing, contradicted by gameplay. The audit prompt had stated this as a hypothesis to check, and the answer echoed it back.
- "Dropped chests register in `InteractablesStatus` via `InteractableChest.Awake`" — they do not.
- "`InteractablesStatus["Microwaves"]` increments on every craft" — measured: it moved only after the third and final craft of a green microwave.
- "A craft consumes 3 / 2 / 1 items depending on the tier" — those figures are the appliance's use count by its own rarity. Every craft takes exactly one item and returns one.
- Estimated exclusion windows of 20 s for Moai and 8 s for the merchant, both derived from assumed player deliberation. Measurement put them at ~1 s and ~0 s: the Moai counter fires at the pick rather than at the interaction, and the merchant's fires together with its item.
- Reconciling item gains against the chest-opening counter, which assumed that counter sees every opening. It does not.
- Including Moai items as ordinary chest rolls — its Luck multipliers would have skewed the expectation systematically, not merely added noise.
- Function labels in the audits contradict each other across reports (`0x18112df20`, `0x51AF60`); treat any name in them as unverified unless a listing backs it.

##### References

- [2026-06-10-chests-and-keys-detection.md](file:///f:/Python/MegabonkReroll/docs/recovery/reports/2026-06-10-chests-and-keys-detection.md) — `EChest`, `ItemKey`, `InteractableChest`, `ItemInventory`, and the Item Source Elimination Algorithm this design deliberately replaces.
- [chests-command-detection.md](file:///f:/Python/MegabonkReroll/docs/design/game/chests-command-detection.md) — the live-tested counter semantics behind `!chests`, and the `DetectInteractables.currentInteractable` path.
- [2026-06-09-disabled-items-detection.md](file:///f:/Python/MegabonkReroll/docs/recovery/reports/2026-06-09-disabled-items-detection.md) — `RunUnlockables.availableItems`, needed for the rarity-label verification above.
- [In_Game_Overlay.md](file:///f:/Python/MegabonkReroll/docs/wiki/In_Game_Overlay.md) — `LuckRarityBarWidget` and the rarity probability rendering.
- [data_flow_architecture.md](file:///f:/Python/MegabonkReroll/docs/design/app/data_flow_architecture.md) & [data_flow_refactor_plan.md](file:///f:/Python/MegabonkReroll/docs/design/app/data_flow_refactor_plan.md) — the fast/slow refresh lanes a Luck task would join.

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

#### 1. Game-Time Synchronized KPS Calculation (Refactor Fixes)

Status: `[Planned]` — design settled against live measurement on 2026-07-26; not implemented.

Goal:

- Replace the strict ~1-second polling window requirement in `track_ui_kps` with a KPS calculation whose publication rhythm is driven exclusively by the continuously increasing `run_timer`. This first iteration deliberately does not cover Event Timer, `stage_timer`, map phases, or stage transitions.

Problem Analysis:

- **Rigid 0.9s–1.2s Sampling Window:** Current `track_ui_kps` ([combat.py:67](../../src/core/tracker/combat.py:67)) evaluates consecutive samples `(run_timer, mob_kills)` and only updates KPS if the game-time delta falls strictly between 0.9 and 1.2 seconds.
- **Baseline Resets on Lag:** If fast-polling delays or timer jitter cause `time_delta` to exceed 1.2s, the baseline sample is reset (`state.ui_kps_baseline = current_sample`) and that tick is lost outright, freezing the last displayed KPS in every consumer.
- **The published value is a raw kill delta, not a rate.** [combat.py:84](../../src/core/tracker/combat.py:84) publishes `kills - baseline_kills` with no division. It is only a correct kills-per-second figure because the gate guarantees the window is ~1 s wide.
- **The defect does not reproduce on a healthy machine.** Measured below: at the app's own cadence with no induced stalls, the current algorithm lost zero ticks in 81 samples. The fix targets the lag case specifically, and its priority should be read that way.

##### Live Measurement (2026-07-26)

`tools/probe_kps_sync.py` polls `run_timer`/`mob_kills` against a live run and drives several candidate KPS monitors over one shared sample stream, so the comparison is differential rather than sequential. Two scenarios, both at `interval=0.5` (the `FAST_TRACKER_INTERVAL_MS` default), against an active mid-run fight.

**Baseline conditions.** `run_timer` advanced in steps of 0.483–0.509 s per poll. The paired `run_timer`+`mob_kills` read spanned 16 ms at worst and never approached `KPS_GROUP_SPAN_LIMIT_SECONDS` (0.100), so the coherence gate at [refresh_tasks.py:720](../../src/app/refresh_tasks.py:720) withheld nothing during these captures.

**Clean cadence, 40 s, 81 samples:**

| monitor | publishes | ticks lost | measured window |
| --- | ---: | ---: | --- |
| current (0.9/1.2 gate) | 40 | 0 | 0.979–1.021 s |
| second-crossing, baseline = publishing sample | 40 | 0 | 0.979–1.021 s |
| second-crossing, 1 s window | 40 | 0 | 0.979–1.021 s |

**With emulated driver stalls (1 s stall at p=0.25 per tick), 50 s, 59 samples:**

| monitor | publishes | ticks lost | measured window | worst display freeze |
| --- | ---: | ---: | --- | ---: |
| current (0.9/1.2 gate) | 13 | 20 | — | **12.0 game seconds** |
| second-crossing, baseline = publishing sample | 42 | 0 | 0.492–2.016 s | 2.0 s |
| second-crossing, 1 s window | 42 | 0 | 0.991–2.017 s | 2.0 s |

A twelve-second frozen KPS readout is the measured form of the defect this item exists to fix.

##### Why the Baseline Cannot Be the Previous Publishing Sample

The algorithm as originally drafted here re-anchored the baseline to the sample that published. Measurement rejects it: the window collapses to **0.492 s under stalls and 0.500 s even on the clean run**, and the resulting peak read 567 KPS where the 1 s-window monitor read 352 over the same fight.

The cause is that a crossing detected *late* leaves the next crossing only milliseconds away in game time. A sample landing at `run_timer = 101.98` publishes and becomes the baseline; the very next poll at `102.48` has already crossed second 102 and publishes again over a 0.5 s interval. Dividing normalizes the units but not the quantization — a half-second window doubles the noise of every kill.

Anchoring only the *first* crossing after a reset (an intermediate proposal) does not fix this either. It bounds the first published interval and nothing after it; the 0.492 s minimum above was measured with that variant active.

##### Design: Second-Crossing Rhythm, Fixed Game-Time Window

Publication is synchronized to `run_timer`; measurement is over a window of fixed game-time length. The two are separate decisions and conflating them is what produced the variants above.

- **When to publish:** on each crossing of an integer `run_timer` second. This is the same rhythm the game's own HUD counter runs at — live validation on 2026-07-23 established that `run_timer` updates every 4.2–58.4 ms (20.8 ms median) and that its integer-second boundaries fall one local second apart during active play — so we match the HUD's cadence without needing to read at any exact instant.
- **What to measure:** the kill rate over the last ~1.0 game second, taken from the sample history `track_kills` already maintains, not from a private baseline pair.
- Application wall-clock time decides only when to perform a memory read. It never enters the formula.

Algorithm:

1. Keep one new piece of state: the last integer second published for, `floor(run_timer)`. The `ui_kps_baseline` pair is deleted.
2. Each fast read appends `(run_timer, mob_kills)` to `recent_kills_history` exactly as today.
3. If `run_timer` is unchanged, the run is paused: `track_kills` already collapses the sample and returns before `track_ui_kps` is reached ([combat.py:54](../../src/core/tracker/combat.py:54)). The last published KPS stays on screen and the second cursor does not advance. No new code is required for this case.
4. If `floor(run_timer)` has not advanced past the cursor, publish nothing and leave the previous value in place.
5. Otherwise set the cursor to the new second and select the baseline: **the newest history sample whose time is at or before `run_timer - 1.0`, admitting samples up to `TOLERANCE` seconds later than that mark** (`TOLERANCE = 0.05`, see the interval note below). Publish `round((kills - baseline_kills) / (run_timer - baseline_time))`, floored at zero.
6. If no sample qualifies — the history is shorter than the window, i.e. the first second of a run or of a reattach — publish nothing. KPS stays unavailable until the window fills.
7. Reset on `run_timer` rollback, `mob_kills` decrease, new run, or game process loss. `track_kills` ([combat.py:51](../../src/core/tracker/combat.py:51)) and `reset` already cover all four; only the second cursor needs adding to `reset_ui_kps`.

**The tolerance in step 5 is not slack, it is required — but it must be smaller than half the poll interval.** Without any tolerance, a poll landing a few milliseconds short of the one-second mark is rejected and the next-oldest sample is taken instead — measured at 500 ms, this puts the window at ~1.5 s for half of all publications, visibly over-smoothing the readout. But a tolerance that is too large *shrinks* the window at fine cadences: see the interval measurements below, where a 0.1 s tolerance at 100 ms polling pulled the window down to ~0.9 s. Since `FAST_TRACKER_INTERVAL_MS` has a hard floor of 100 ms, the tolerance must not exceed 0.05 s to stay under half of the tightest possible spacing. At `TOLERANCE = 0.05` the window measured 0.979–1.021 s across the 500 ms clean capture and sits at ~1.0 s at 100 ms.

##### Read Interval Is Configurable, and This Design Depends On That Being Free

The fast lane's cadence is `FAST_TRACKER_INTERVAL_MS` ([config.py:824](../../src/app/config.py:824)): default **500 ms**, hard floor **100 ms**, set through `config.json` (no GUI control). It is a single knob feeding five sites — the driver timer ([gui_app.py:306](../../src/gui_app.py:306)) and the `combat_metrics`, `powerups`, `expected_chest_inputs`, and `chaos_tome` tasks ([refresh_tasks.py:215](../../src/app/refresh_tasks.py:215)) — so KPS cannot be re-timed in isolation without giving it its own constant, the way `PASSIVE_ITEMS_REFRESH_MS` (1 s) and `event_timer` (1 s) already stand apart. The driver interval is also the floor for every task: at 1000 ms a 1 s task effectively runs at 1–2 s.

Measured across intervals on 2026-07-26 (`tools/probe_kps_sync.py`):

| interval | `run_timer` delta/poll | current algo (0.9/1.2 gate) | new (1 s window) |
| --- | --- | --- | --- |
| 1000 ms | 0.996–1.008 s | publishes, but sits **dead-center of the gate** — one skipped poll = ~2.0 s delta = lost tick + rebase | window 0.996–1.008 s, unaffected |
| 500 ms | 0.483–0.509 s | 0 ticks lost when clean | window 0.979–1.021 s |
| 100 ms | ~0.100 s | narrow subsecond gate, frequent holds | window ~0.9 s **only because a 0.1 s tolerance was too large** — fixed by `TOLERANCE = 0.05` |

The decisive point for this item: **after the change, the interval stops being a correctness parameter and becomes a cost/precision one.** Today 1000 ms actively breaks the current KPS (jitter throws deltas past the 1.2 s gate); afterward 1000 ms merely coarsens the window, and 100 ms merely multiplies read cost fourfold across the shared lane for fractions of a kill in the readout. That decoupling is an independent argument for the change, separate from the stall scenario.

##### What Changes On Screen

In healthy conditions, almost nothing — which is the point. Over the clean capture the new value matched the current one on **33 of 40 publications**, the other 7 differing by 1–3 kills purely from dividing by a 0.98–1.02 s window instead of treating it as exactly 1 s. The number continues to agree with the game's HUD counter in the normal case, and diverges only where the current algorithm published nothing at all.

Consumers of `current_ui_kps` that inherit the change: the Live Stats kills line ([refresh_tasks.py:743](../../src/app/refresh_tasks.py:743)), the recording snapshot's `kps` field ([player_stats_refresh.py:505](../../src/app/player_stats_refresh.py:505)), the OBS overlay widget ([obs.py:237](../../src/projections/obs.py:237)) and the In-Game Overlay's instant KPS ([in_game_html.py:33](../../src/projections/in_game_html.py:33)). Recordings written after this change carry rate-normalized instant KPS; runs recorded before it do not, so a Compare Runs diff of that field spans two slightly different definitions. The difference is within the 1–3 kill band measured above and needs no migration, but it should not be discovered later as a mystery.

##### Implementation Notes

- **`track_ui_kps` becomes a consumer of `recent_kills_history`.** `track_kills` appends to that deque one line before calling it ([combat.py:59](../../src/core/tracker/combat.py:59)), so the window is already in hand; `_CombatState.ui_kps_baseline` is removed and replaced by an integer second cursor. The 300 s trim above it stays as is.
- **This makes instant KPS the same computation as the windowed readouts,** differing only in window length and in being emitted on second-crossings rather than on demand. `average_kps_for_window` ([combat.py:88](../../src/core/tracker/combat.py:88)) picks the *oldest* sample inside its window, which is right for a 60 s or 300 s average and wrong for a 1 s one — at 0.5 s polling it would land 1.5 s back. Share the deque, not that selector; the new one takes the newest sample at or before the cutoff.
- **The module docstring is now false and must be rewritten.** [combat.py:6-11](../../src/core/tracker/combat.py:6) states that the 0.9/1.2 s gate exists to reproduce the game's own on-screen counter and that the two KPS notions are not interchangeable. After this change the gate is gone and the two notions differ only by window.
- **`LiveRunTracker` needs no new surface.** `current_ui_kps` ([live_run.py:741](../../src/core/tracker/live_run.py:741)), `track_kills` ([live_run.py:572](../../src/core/tracker/live_run.py:572)) and `_reset_ui_kps_unlocked` ([live_run.py:1132](../../src/core/tracker/live_run.py:1132)) keep their signatures. The `__init__` state list at [live_run.py:177](../../src/core/tracker/live_run.py:177) names `_ui_kps_baseline` and must be updated with it.
- **Do not touch the coherence gate.** When the combat group's span exceeds `KPS_GROUP_SPAN_LIMIT_SECONDS` the pass withholds the pair entirely and `track_kills` is never called ([refresh_tasks.py:720](../../src/app/refresh_tasks.py:720)). That is the lag case this design is built to survive: the skipped kills are not lost, they are counted at the next publication over a correspondingly longer window.
- **Delete `_last_fast_kps_game_time_seconds`** ([refresh_tasks.py:390](../../src/app/refresh_tasks.py:390)). It is written at [refresh_tasks.py:732](../../src/app/refresh_tasks.py:732) and read nowhere in `src/` — three occurrences in the repository, all in that one file: the docstring, the initializer and the write. It is not the second cursor this design needs and must not be repurposed as one; the cursor belongs next to the history it indexes, in `_CombatState`.

##### Tests

The two existing tests over this path — `test_current_ui_kps_uses_valid_one_second_tick` and `test_current_ui_kps_ignores_tiny_timer_jump_after_pause` ([test_live_run_tracker.py:367](../../src/tests/test_live_run_tracker.py:367)) — **pass unchanged both before and after this change** and therefore prove nothing about it. `100.0 → 100.5 → 101.0` crosses second 101 over a 1.0 s window and still yields 300; `586.522 → 586.770` crosses no integer second and still yields `None`. Keep them, do not count them as coverage.

Required new cases, each of which must fail against the current implementation:

- **Skipped second.** `100.0 → 100.5 → 102.4`: the current code loses the tick, the new one publishes a rate over the ~1.9 s window.
- **Late crossing must not shrink the window.** `100.0 → 100.5 → 101.98 → 102.48`: the second publication must measure over ~1 s, not over the 0.5 s between the two publishing samples. This is the case that fails the rejected variants and is the single most important test here.
- **Tolerance admits a near-miss.** At coarse spacing, a sample at `run_timer - 0.998` must be admitted as the baseline rather than deferring to one at `run_timer - 1.498`.
- **Tolerance must not shrink the window at fine spacing.** With samples 0.1 s apart, the baseline chosen for a publication must sit at ~`run_timer - 1.0`, giving a ~1.0 s window — not `run_timer - 0.9`. This is the case that catches a too-large tolerance; it failed at `TOLERANCE = 0.1` and passes at `0.05`.
- **Window not yet filled.** The first second after a reset publishes nothing.
- **Pause.** A repeated identical `run_timer` neither publishes nor advances the cursor, and the previous value remains readable.
- **Resets.** Rollback and kill-count decrease clear the cursor as well as the value, and the next run starts from an empty window.
- `track_ui_kps` currently has no unit coverage at the `combat.py` level at all — only indirect coverage through `LiveRunTracker`. Add the above at the pure-function level where the state is directly inspectable.

##### Validation

- Re-run `tools/probe_kps_sync.py` after implementation with a monitor mirroring the shipped code, and confirm on a live run that the app's `current_ui_kps` tracks it.
- **Open measurement, worth doing before implementing:** the stalls above were *emulated*. Log `lost_overshoot` occurrences from the real Qt-driven fast lane over a ten-minute run. If the production driver loses ticks at a rate comparable to the emulation, this change has a measured payoff; if it loses as few as the probe's tight loop did (zero in 40 s), the item is a correctness improvement for a rare condition and should be prioritized accordingly.

Benefits:

- KPS remains strictly anchored to `run_timer` rather than to application wall-clock time;
- UI updates follow the rhythm of the game's own elapsed seconds, which is also the HUD's;
- missed or delayed fast-ticks no longer create empty output windows — measured 42 publications against 13 under stalls;
- the measurement window cannot collapse below ~1 game second, so a late read produces a smoothed value rather than a spike;
- pauses preserve the last valid KPS and do not create false activity;
- the scope is isolated from stage/map logic, so it can be implemented and characterized independently.

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
3. While the selected raw timer increases normally, synchronize its integer-second boundaries exactly as in the KPS clock design. Use the local prediction only to optionally increase read frequency near the next boundary.
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
