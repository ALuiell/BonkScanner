# Functional Updates Archive

This file archives completed, shelved, or old functional updates, helping keep `functional_updates.md` focused on active tasks.

---

## Recently Handled Items (Archived 2026-08-08)

### Twitch Commands

#### 6. Chest Statistics in Recordings and Compare Runs

Status: `[Archived]`

Goal:

- Expose the chest breakdown in Compare Runs the same way the rarity totals from item 5 are exposed, behind its own toggle so the two can be shown independently.

What is already done:

- **The recording side needs little or no work.** Snapshots already carry `chests_opened`, `chests_total`, `chests_opened_by_stage`, `chests_total_by_stage`, `paid_chests`, `key_procs`, `expected_key_procs`, `free_chests` and `keys_count` — verified against `stats_recordings/950k.jsonl` (metadata `version: 6`). The remaining work is reading them back and rendering the comparison.

Remaining work:

- Add a Compare Runs toggle for the chest block, a sibling of the rarity one rather than a shared switch: a viewer comparing luck between runs and one comparing looting efficiency want different rows on screen.
- Decide which fields are worth comparing. Paid versus Key procs versus inherently free is the interesting split, and `expected_key_procs` beside the actual proc count is the one figure that says whether the Key stack paid off. Raw `chests_opened` alone compares map progress more than player decisions.
- Handle older recordings explicitly. Even inside a single version-6 file the early snapshots predate some keys — `chests_total`, `expected_key_procs` and `free_chests` are absent from the first few rows of `950k.jsonl` — so the comparison needs a real missing-value path rather than treating absence as zero, which would read as "no chests opened" instead of "not recorded".
- Keep the `Expected` label distinct from the rarity card's. Here it counts expected **key procs**; in item 5 it counts expected items per tier. The two now appear in the same tab and the same comparison view.

### Support & Community

#### 1. Supporters List in the Footer

Status: `[Archived]`

The visual half was written deliberately ahead of the data, because it is the
perishable half: reproducing this popup from a description later is far more
work than writing the twenty lines that read a JSON file.

The seam is `FooterView.set_supporters` ([src/ui/footer.py](../../src/ui/footer.py)).
Hand it names and the footer link becomes `♥ N supporters` and the popup grows
the list; hand it nothing and the strip is exactly what ships today. It is now
called once a launch from `start_supporters_load`
([src/ui/dialogs/update_prompt.py](../../src/ui/dialogs/update_prompt.py)).
`src/tests/test_support_popup.py` covers both halves -- the empty case,
malformed entries, the tier marker, the cap, going back to empty, and the
reader's silence on a failed request, an empty list and a malformed payload.

It accepts plain strings and mappings both, so a `supporters.json` needs no
shape negotiation: `"Nyxaria"` and `{"name": "Nyxaria", "tier": "patreon"}` are
both valid rows. The recognised tiers are `patreon`, `pack` and `kofi`,
normalised so `"Ko-Fi"` and `"ko_fi"` also land; an unrecognised but non-empty
tier is still marked, because a typo in the tier of someone who paid must not
read as "not a supporter".

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

##### Where the data comes from

- **The Patreon API is not an option.** It needs OAuth and a refresh token, and the token would have to live inside a binary that is handed to everyone. That means either a credential in the build or a server in between; neither is worth it for a name list.
- **The file may be a bare array or an object with a `supporters` key.** The second shape exists so the instructions for filling it in can live inside the file being filled in — JSON has no comments, and this is edited by hand months apart. Every other key is ignored.
- **The source is a hand-maintained `supporters.json` at the repository root, fetched from `raw.githubusercontent`** — not bundled. Bundling was rejected on the one point that matters in practice: a name added when someone subscribes would then wait for the next release, which turns a thirty-second browser edit into a build. Fetching costs one GET and a few minutes of CDN cache, and the list is a thank-you, not a clock.
- **It must not sit on the path to the first window.** That rule is why commit `d3796f0` exists. It is started from `deferred_update_check` ([src/gui_app.py](../../src/gui_app.py)), 1.5 s after `__init__`, on its own daemon thread.
- **It is its own request, not a passenger on the update check.** `check_and_update` returns before it reaches the network when `frozen_exe_path()` is `None`, so riding along would make the list invisible to every source run — including while working on the feature, where it reads as a bug each time it is rediscovered. The two share the delay and the footer, nothing else.
- **The network half lives in `app/`, not beside the widget.** `ui/` may not import `infra/` (`test_import_direction`), so the fetch is `app.supporters.load_supporters` → `infra.updater.fetch_supporters`, and `ui.dialogs.update_prompt.start_supporters_load` owns only the thread and the hop back to the GUI thread.

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
- Three states, distinguished by *platform* rather than by amount, all at weight 700: a Patreon subscription is `#FF6F61` with a `♦` prefix; a supporter pack is the same `#FF6F61` without the diamond, because the money is the same and only the recurrence differs; a Ko-fi tip is `#29ABE0`, the Ko-fi button's own blue, which reads as a different place rather than a higher rank. An entry with no tier stays `#B9C2CE`. A fourth state would turn a thank-you card into a pricing page — do not add one.
- The Patreon and Ko-fi buttons stay at the bottom, below a `#1B222B` rule. They keep `#PatreonButton` / `#KofiButton` ([redisign_ui/bonkscanner_redesign.qss:1321](../../redisign_ui/bonkscanner_redesign.qss:1321)) so the popup and the settings card cannot drift apart.

Overflow: when the list outgrows the popup, move it to a card in the Help dialog — names in three columns, all four platform buttons — and leave the footer counter as the entry point. Help is where a long block costs nothing, because people open it deliberately. Do **not** put the card on a main-window tab: on Logs it is pushed off-screen by the log within seconds, and everywhere else it takes space from data.

##### Open decisions

- Whether the count includes past supporters or only current ones. `N supporters` is read as "right now", so a lapsed-inclusive count needs different wording. Current intent: the list is grow-only — a one-time payment does not expire, and a lapsed subscription loses its `patreon` tier rather than its row.
- ~~`KOFI_SUPPORT_URL` is a Ko-fi **shop item** rather than a donation page.~~
  Resolved: it points at the profile now.

---

## Recently Handled Items (Archived 2026-08-03)

### Twitch Commands

#### 3. The One Ring Announcer

Status: `[Archived]`

Goal:

- Add an automatic announcer for the Twitch bot that triggers when the player picks up "The One Ring" (in-game name: "Golden Ring").
- Support multiple randomized messages to keep the chat reaction fresh.

##### What shipped

Two phrase pools, on every map: one for the first ring, one for every duplicate
after it. Six phrases and five respectively, one per line, drawn at random with
the recent draws excluded.

- `TwitchBotWorker._check_one_ring_announcement` ([src/twitch_bot.py](../../src/twitch_bot.py)), called from the socket loop beside `_check_stage_transitions`.
- Config: `one_ring_announcements` (**default off; opt-in**), the `one_ring_announcement` and `one_ring_duplicate_announcement` template pools, and `announcer_recent_lines`, all in `DEFAULT_TWITCH_BOT` ([src/app/config.py:163](../../src/app/config.py:163)). Checkbox in the Announcements card; two multi-line editors in the command dialog's Announcers tab.
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

### In-Game Overlay

#### 1. Item Cooldown Display (Bob's Light and other timed items)

Status: `[Archived]`

Goal:

- Show the live countdown to the next trigger of cooldown-driven passive items (first target: Bob's Light / `ItemBobLantern`), so the player can time movement and pulls around the next explosion.

**Reconnaissance is closed.** Nothing below is a guess any more: the whole field
layout, both stacking formulas, the re-arm rule, and the behaviour across stage
transitions, pause and the death screen were measured live on 2026-08-03 and
cross-checked against the published mechanics. What remains is writing it.

##### Decided: its own overlay widget

Not a second block inside the Powerups widget, for three reasons that are all
mechanical rather than aesthetic:

- **The Powerups widget hides itself when no buff is up** (`setVisible(False)` at
  [src/gui_in_game_overlay.py:373](../../src/gui_in_game_overlay.py:373)). An item cooldown is live for the whole run, so
  sharing that widget means deleting the rule -- and the widget then becomes
  permanently visible for everyone already using it. That is a regression in
  someone's existing layout to make room for a new feature.
- **Position and scale are per widget id.** One `x/y/scale` and one checkbox for
  both blocks means a growing item list drags the powerups with it, and
  `reclamp_to_parent` moves both at once.
- **The list is expected to grow.** Bob's Light is the first timed item, not the
  only one; `ItemUnstableTransfusion` is already a live candidate (see below).

The cost of a separate widget is small because this one is pure text: a plain
`DraggableOverlayWidget` plus `set_text` with RichText, no custom `paintEvent`
like `LuckRarityBarWidget`. Visually it is close to Powerups; structurally it is
a copy of the cheapest widget in the file.

**Hidden when there is nothing to show**, matching Powerups -- no timed item in
the inventory means there is nothing to say. Copy the edit-mode placeholder from
`build_powerups_overlay_html`, or the widget cannot be grabbed with the mouse
while the inventory is empty.

**Rows are coloured by the item's rarity**, via `ITEM_RARITY_BY_NAME` (163
entries, covering every timed class still queued for this widget).
`CRITICAL_COLOR` overrides under 5 s remaining, `TEXT_SHADOW` on every span.

Two dead ends are worth recording, because both looked right:

- `item_display_color` ([src/core/item_metadata.py:305](../../src/core/item_metadata.py:305)) is not an item colour
  catalog. Its map holds **one** entry, Golden Ring, as a special case for the
  ring announcer. Every timed item routed through it comes back
  `FALLBACK_COLOR` -- one colour for all of them, which is the opposite of what
  per-item colour is for.
- A hand-kept `{item_id: colour}` table works and was shipped briefly, but
  rarity is better: it needs no maintenance, it grows with the catalog, and it
  says something the player already reads elsewhere.

The cost of rarity is that two timed items of the same tier share a colour --
accepted deliberately, because the row's *name* is what identifies it and the
colour is carrying tier information that is real. Rarity colours are the
overlay's shared vocabulary: the Luck row, the bar and the expected block
already speak them, so `#E879F9` means "rare" everywhere it appears.

No stack suffix. The effective `cooldown` already reflects the stack, so `xN`
was saying it twice and costing width that a late inventory full of timed items
will need.

##### Verified memory read path

First confirmed live on 2026-07-31 with `tools/probe_item_cooldown.py` (repaired in
that session -- it had been calling a `PlayerStatsClient` method that no longer
exists and walking a stale pointer chain). Extended on 2026-08-03 with a capture
that logs every passive item's raw field block to JSONL rather than clearing the
screen, which is what made the stack, pickup, transition, pause and death-screen
findings below possible.

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

Use `PlayerStatsClient._resolve_preferred_passive_item_dict(owner_stats)` rather than re-deriving the chain.

**Neither route is "the right one" — either can resolve a live pointer to a drained dictionary, and which one does depends on run state.** The earlier note here claimed the container route was authoritative and the `PLAYER_INVENTORY_OFFSET` route yielded a null dictionary. Measured mid-run on 2026-08-03 with 25 items held, it was exactly inverted:

```text
owner_stats +0xA0 -> +0x50            = 0x...EF750   count=0  version=0  entries=0x0
owner_stats +0x28 -> +0x20 -> +0x10   = 0x...57AE0   count=25 version=25 entries=0x...DA80
```

So the resolver may not stop at the first **non-null** pointer; it has to prefer the one that actually **has entries**. That is the rule `get_passive_items` always applied by falling through on an empty *result*, and the helper now states it directly so the two cannot disagree.

They did disagree, silently, and not only for this feature: `_get_cached_key_count` used the helper and reported `key_count=0` for a player visibly holding `Key x1` — measured live, then fixed with the helper. `expected_key_procs` was reading a drained dictionary in exactly this state.

A second, related trap belongs to any consumer of the layout memo: it is cached per dictionary, so a reader must confirm the memo belongs to the dictionary it just walked. Skipping that check made `get_item_cooldowns` return correct-looking readings *through a drained dictionary*, purely because an earlier `get_passive_items` had left a live layout behind — a bug that only reproduces when the calls are made in that order.

Per-item cooldown fields, `ItemBobLantern` (offsets relative to the item object):

| Offset | Type | Field | Live value | Status |
| --- | --- | --- | --- | --- |
| `0x18` | i32 | `amount` (stack count) | 1 … 5 | Confirmed — same value as `ITEM_STACK_COUNT_OFFSET` |
| `0x30` | f32 | `cooldownMin` | 5.00 | **Confirmed live** |
| `0x34` | f32 | `cooldownMax` | 45.00 | **Confirmed live** |
| `0x38` | f32 | `cooldownReductionPerAmount` | 3.00 | **Confirmed live** |
| `0x3C` | f32 | `cooldown` — effective CD in seconds | 42 / 36 / 33 / 30 | **Confirmed live** at `amount` 1/3/4/5 |
| `0x40` | f32 | `nextExplodeTime` — absolute game-time mark | — | **Confirmed live** |
| `0x44` | f32 | `radius` — effective | 60 / 80 / 90 | **Confirmed live** at `amount` 1/3/4 |
| `0x48` | f32 | `radiusMin` | 50.00 | **Confirmed live** |
| `0x4C` | f32 | `radiusMax` (cap) | 250.00 | **Confirmed live** |
| `0x50` | f32 | `radiusPerAmount` | 10.00 | **Confirmed live** |

The layout is closed: every offset in the block has a name, and the two derived
fields match the published mechanics exactly.

```text
cooldown(n) = max(5,   45 - 3n)     -> 42 / 36 / 33 / 30 at n = 1 / 3 / 4 / 5
radius(n)   = min(250, 50 + 10n)    -> 60 / 80 / 90      at n = 1 / 3 / 4
```

The constants on the left of those formulas are `0x30`/`0x34`/`0x38` and
`0x48`/`0x4C`/`0x50`; the results are `0x3C` and `0x44`. **Read the results, do
not compute them.** A balance patch changes the constants in the fields, not the
meaning of the fields — and the formulas are then worth exactly what they are
worth here: expected values in a characterization test, which will report the
change as a disagreement with documented mechanics rather than as drifted
offsets.

The clock these are measured against is `MyTime.time`, available as `PlayerStatsClient.get_my_time_seconds()` ([src/infra/memory/player_stats_client.py:1246](../../src/infra/memory/player_stats_client.py:1246)), which resolves `_resolve_my_time_static_fields() + MY_TIME_TIME_OFFSET (0x04)`.

##### Matching on a field value does not work

Swept all 27 passive items for floats that track `MyTime.time`. Nine items have
one; **eight of them are not cooldowns**:

| Item | Offset | Lead over `my_time` | What it actually is |
| --- | --- | --- | --- |
| `ItemBobLantern` | `0x40` | +29.4 s | the real thing |
| `ItemGlovesBlood` | `0x30` | +3.7 s | sub-cycle proc timer |
| `ItemHolyBook` | `0x48` | +1.1 s | sub-cycle proc timer |
| `ItemCursedDoll` | `0x5C` | +0.9 s | sub-cycle proc timer |
| `ItemCampfire` / `ItemIdleJuice` | `0x54` / `0x50` | +0.6 s | sub-cycle proc timer |
| `ItemSpikyShield` | `0x3C` | +0.5 s | sub-cycle proc timer |
| `ItemBeefyRing` | `0x3C` | +0.1 s | sub-cycle proc timer |
| `ItemPhantomShroud` | `0x5C` | **−1.3 s** | mark of the *last* trigger, in the past |

`ItemIdleJuice 0x5C` is a third semantic again — it advanced 91.8 s over a 167 s
span, so it is neither a mark nor a countdown. And note `ItemSpikyShield` and
`ItemBeefyRing` carry their tick timer at **`0x3C`**, the same offset that holds
`cooldown` on the lantern.

**Every one of those eight was then named by the dump, exactly.** The live sweep
found which offsets move; `dump.cs` says what they are; the two agree to the
byte:

| Live sweep | `dump.cs` |
| --- | --- |
| `ItemBeefyRing 0x3C` | `nextUpdateTime` |
| `ItemSpikyShield 0x3C` | `nextUpdateTime` |
| `ItemCampfire 0x54` | `startCampfireTime` |
| `ItemIdleJuice 0x50` | `startCampfireTime` |
| `ItemCursedDoll 0x5C` | `nextAttackTime` (`attackCooldown` at `0x58`) |
| `ItemHolyBook 0x48` | `nextDamageTime` (`cooldown` at `0x4C`) |
| `ItemGlovesBlood 0x30` | `readyAtTime` (`cooldown` at `0x34`) |
| `ItemPhantomShroud 0x5C` | `speedResetAtTime` — a reset mark, which is why its lead was negative |

**The ninth hit was worse than wrong — it was not a field.** `ItemUnstableTransfusion`
declares exactly two floats, `chanceToStackPerAmount` at `0x30` and `totalChance`
at `0x34`. There is nothing at `0x40`; the "+272 s mark" read there was memory
past the end of the declared layout that happened to hold a plausible future
timestamp.

So the value heuristic scored **one true positive out of nine**, and its failures
are silent by construction: seven wrong-semantics fields and one read of nothing
at all, every one returning a well-formed float. This is the empirical case for
the per-class offset table, and for confirming a class in `dump.cs` before
reading a single byte of it.

##### Measured semantics

- `nextExplodeTime` is **not** a countdown. It is an absolute mark on the same `MyTime.time` axis, so the displayed value is `remaining = nextExplodeTime - my_time`.
- **Re-arming after a trigger is exact.** Twelve consecutive cycles: `+42.003`, `+42.003`, `+36.013`, `+36.007`, `+36.019`, `+36.018`, `+36.009`, `+36.001`, `+36.005`, `+36.012`, `+33.024`, `+33.018` against `cooldown` fields of 42.00/36.00/33.00. Deviation never exceeded 24 ms, and there is no accumulating drift — whole-second display needs no correction.
- **Any pickup re-arms the mark to exactly `my_time + 2.000 s`** — including the first one, where it moves the mark *backwards* by tens of seconds. This is the finding that breaks the naive model.

  Measured directly, with no sampling ambiguity at all, because **item selection pauses the game**: across the pickup the clock was frozen at `my_time 2257.802` and the game wrote `nextExplodeTime = 2259.802`. Difference: `2.000`.

  Two earlier stack-change samples, taken at 250 ms with the clock *running*, bound it consistently — `next − t_pickup ∈ [1.892, 2.138)` for x1 → x3 and `[1.966, 2.221)` for x3 → x4, intersecting at `[1.966, 2.138)`, which contains 2.000. Those read low (1.89, 1.97) only because the clock advanced between the game's write and the probe's read.

  A *proportional* rule was already excluded by those two samples before the exact one arrived: a common fraction `k` would need `k×36` in the first window and `k×33` in the second, giving `k ∈ [0.0526, 0.0594)` against `k ∈ [0.0596, 0.0673)` — disjoint. The published mechanics agree in words ("On pickup / amount change, the next explosion is scheduled about 2 seconds later"); the measurement makes "about" exact. After that first trigger the normal cycle resumes — observed `+42.005` against `cooldown 42.00`.

  Consequences:
  - the mark is **not monotonic**, so a "just exploded" pulse must fire on an
    *increase*, never on a change — a pickup moves it down and the real
    explosion follows 2 s later, which would double-fire a change-driven pulse;
  - no local model can predict it, which is the standing argument for re-reading
    the mark rather than extrapolating it;
  - because the selection screen holds the game paused, the first value the
    widget ever shows for a newly picked-up item is a **frozen `2s`**, held for
    as long as that screen is open. Correct, and indistinguishable from a stuck
    display to anyone who does not know why.
- **`remaining` goes briefly negative before a re-arm is observed.** Measured `−0.01 s` on the tick before the mark moved. Clamp at zero; the bound on that window is one read interval.
- **Pause freezes the clock bit-exact.** Two captures, 4.3 s and 17 s of wall-clock: `my_time` held the *identical* float across 68 consecutive reads, `stage_timer` froze with it, `remaining` held at exactly `30.08` and `27.45`, and the resume was clean with no catch-up. Never derive the countdown from a local monotonic clock — over that 17 s pause it would have burnt half a cooldown. Same rule the KPS clock and the Event Timer already follow.
- **A stage transition is a complete non-event.** Captured Stage 1 → 2 with a lantern equipped: `stage_index` flipped at `my_time 1938.33`, `stage_timer` reset at `1939.68` and then sat at a flat `0.00` for a further 4.15 s before advancing — while `MyTime.time` stayed continuous (no reset, no jump) and `nextExplodeTime` was **not touched at all**, holding `1946.850` straight through. `amount`, `cooldown` and the dictionary entry were unchanged; the item never left the dictionary. Nothing about a transition needs handling.
  - Two side findings, both for the Event Timer item rather than this one: `stage_index` and the `stage_timer` reset are **1.35 s apart**, so "stage changed" and "timer reset" are not one event; and on the reset tick `my_time` advanced only 0.058 s against 0.251 s of wall-clock, so a naive `game_delta/wall_delta < 0.9` pause detector fires falsely on a transition.
- **Graveyard is a non-event too, measured with every timer family in view.** One run, 5094 reads at 10 Hz, `MyTime.time` 3190 → 3582 with **zero** backwards steps. The crypt transition is the sharpest evidence: in a single tick `stage_timer` went `135.51 -> 0.00` and `crypt_timer` `40.96 -> 0.09`, while `nextExplodeTime` held `3428.065` unmoved and `remaining` kept descending `27.34 -> 27.25 -> 27.15`. `MyTime.time` advanced `0.091 s` on that tick against a normal `0.10`.

  Across the whole run — crypt entry, the boss, and 735 s of post-boss swarm — the mark re-armed eight times at `+42.013, +42.006, +42.006, +42.014, +42.014, +42.014, +42.014, +42.012` while `crypt_timer` swung `33 -> 41 -> 27 -> 39` and `final_swarm_timer` climbed from zero. `stage_index` held at `0` throughout, as Graveyard is documented to do. The item is indifferent to all of it.

  Not isolated as its own event: the **portal return**. It produced no timer reset — the crypt entry was the only reset in the run — so there may be nothing there to observe, but that is inference rather than measurement.
- Stage/phase logic is irrelevant here. Unlike powerup effects, which need `resolve_ui_context` to pick between `stage_timer`, `crypt_timer` and `final_swarm_timer`, an item cooldown lives entirely on `MyTime.time` and needs no phase resolution. Do not route it through `core/tracker/powerups.py`'s UI-context machinery. Graveyard is now the measured case for this, not the assumed one.

##### The death screen reads as valid, frozen data — this is the one real trap

The earlier plan assumed a `game over` screen would produce zeroes, garbage or a
failing read, and that the TTL would clear the display. **Measured, both halves
are false.** Across 97 s of wall-clock on the death screen:

```text
my_time      2146.530  frozen bit-exact, 385 consecutive reads
stage_timer   642.10   frozen
run_timer     918.61   frozen
amount            5    cooldown 30.00   nextExplodeTime 2164.473   remaining 17.94
dictionary   count 38, version 39, lantern still in its slot
```

Every read succeeds. Nothing degrades. The widget would sit on a frozen
`17.9s` forever, and the TTL would never fire because there is no failure to
detect. By these fields the death screen is **indistinguishable from a pause** —
both freeze the clock and hold everything else.

So: **the display is cleared by run-lifecycle state, not by the TTL and not by a
failed read.** The TTL still earns its place for the case it was meant for — a
read that genuinely fails — but it does not own end-of-run. The overlay's own
visibility rule does not help either: on the death screen the game window is
still the active window.

The upside is that pause needs no special handling at all. A frozen countdown is
the *correct* render while paused; the only question the freeze raises is
whether to keep showing the widget, and that is a lifecycle question.

**Re-confirmed through the shipped reader, on Graveyard.** The prediction above
was made from raw bytes; `get_item_cooldowns` then reproduced it exactly. 256
consecutive reads over 26 s of wall-clock on the death screen, `my_time` frozen
at `3581.537`, dictionary intact at `count 23, version 23`, and every call
returning `ItemCooldownReading(item_id=85, stack_count=1, cooldown_seconds=42.0,
next_trigger_time=3596.12)` -- a permanent `14.58 s`. **Zero exceptions across
all 5094 reads of the run.** There is nothing for a TTL to catch, because
nothing fails.

**`MyTime.time` also survives a run boundary**, which closes the other half of
the same hole: across a death, the menu and a new run it climbed 2231 -> 2739
with no reset, while the passive dictionary went `count 6, version 6` ->
`count 0, version 0`. So a mark left over from a previous run would subtract
against the clock into a perfectly plausible countdown. Nothing renders one
today only because the dictionary is re-read every pass and the item is absent
from it -- which is a property of the read path, not a guarantee, and is why the
reading belongs in run-scoped state that a run reset clears.

##### Implementation notes

**No new refresh task.** Everything rides the existing 1 s `passive_items` lane
([src/app/refresh_tasks.py:202](../../src/app/refresh_tasks.py:202), `PASSIVE_ITEMS_REFRESH_MS = 1_000`), which already walks
the passive item dictionary the cooldown fields hang off. This was reached by
elimination and it is strictly better than riding the 500 ms `powerups` lane:

- The mark is **absolute**, so an old mark is not a stale mark. It only moves on
  a trigger or a stack change, and a 1 s read bounds the wrong-reading window to
  one interval right after a trigger — during which `remaining` clamps to zero
  and reads as "about to fire", i.e. it degrades into the truth. Paying for a
  second dictionary walk at double the rate buys nothing.
- `cooldown` and `amount` are coupled through `cooldownReductionPerAmount`.
  Reading them in one pass means they cannot disagree.
- `my_time` is **not currently published** on `RuntimeStateSnapshot` — `powerups.py`
  consumes it internally and emits derived `remaining` values. It has to be
  published either way, and publishing it from *this* pass gives the item fields
  and the clock one timestamp. That removes the cross-lane skew question
  entirely, rather than answering it.

This supersedes the earlier note that `my_time` must come "from the same pass"
as a correctness rule: it is now true by construction, and the reasoning behind
it was in any case over-cautious for an absolute mark, where `mark − my_time` is
exact regardless of when each was sampled.

Read side:

- Add a `get_item_cooldowns(owner_stats)` to `PlayerStatsClient` returning one record per cooldown-capable item: `item_id`, `name`, `stack_count`, `cooldown_seconds`, `next_trigger_time`, plus the `my_time` the batch was read against.
- Identify items by class metadata (`item + ITEM_CLASS_META_OFFSET (0x0)` -> `+ CLASS_META_NAME_PTR_OFFSET (0x10)` -> ASCII string), with `ITEM_ENUM_NAMES_BY_ID` as the fallback, matching `_read_passive_item_dictionary`. Do not match on substrings like `"bob"`, and do not match on field values either — see the sweep above, which found the same `0x3C` offset holding an unrelated tick timer on two other items.
- Keep a per-class offset table (`{"ItemBobLantern": CooldownLayout(cooldown=0x3C, next=0x40)}`) from the first version, even with one entry. It costs nothing and it makes a substring match structurally impossible.
- Reuse the passive-item layout cache. `_read_passive_item_dictionary` already memoises `(stack_address, item_name)` per slot, invalidated on `DICT_VERSION_OFFSET (0x2C)` ([src/infra/memory/player_stats_client.py:739](../../src/infra/memory/player_stats_client.py:739)). Extending that tuple with the cooldown addresses makes the per-pass cost two extra float reads, instead of a second full dictionary walk.
  - **Addresses only, never values.** Measured: the dictionary `version` did *not*
    change when the stack went 1 → 3, because stacking mutates the existing item
    object and leaves the dictionary alone. Version-based invalidation is
    therefore blind to a stack change. Caching addresses is safe — the item
    pointer never moved across ~5300 samples and the lantern held slot 15 for the
    whole run — but a cached `cooldown` or `amount` would go stale in silence.
  - The existing rule still stands: **only a clean walk may be memoised.**
    Memoising an incomplete walk is what previously made items disappear from
    recorded runs for tens of consecutive snapshots.
- Marginal cost of the whole read, on a pass already paying for the dictionary walk: two 4-byte field reads plus one for `my_time` (`_resolve_my_time_static_fields` is cached, so it is one read and not a chain). At the ~0.004 ms per `ReadProcessMemory` measured for this process, that is **~12 µs per second** — which is why there is no demand-gating predicate for it and `_should_refresh_passive_items` is left alone.
- **Swallow failures silently**, exactly as `_publish_fast_luck` and `_publish_fast_map_activity` already do in this task body: no `record_memory_failure`, no `mark_fast_feature_failed`. `PASSIVE_ITEMS` keeps a single health owner. Without this a torn cooldown read would be reported as an inventory failure and would poison the feature-status panel. Cost is not the reason demand-gating exists; failure surface is, and this is how that half is paid instead.

Refresh side:

- Publish the result beside `luck` and `fast_items` in `runtime_snapshot` ([src/core/tracker/live_run.py:424](../../src/core/tracker/live_run.py:424)) — that pair is the precedent for "a fast-lane reading carried to the boundary", and `my_time` goes with it.
- Store it in run-scoped tracker state with a TTL, as `core/tracker/powerups.py` does (`POWERUPS_SNAPSHOT_TTL_SECONDS = 1.5`). A missed read must degrade to "no reading", never to a stale countdown that keeps ticking. Clear it on run reset.
- The TTL does **not** cover the death screen — see the trap above. That needs a lifecycle gate.
- Countdown granularity is 1 s, against an overlay that repaints every 500 ms ([src/gui_in_game_overlay.py:123](../../src/gui_in_game_overlay.py:123)), so each value is shown to two repaints. That is what a one-second countdown looks like; the only artefact is lane jitter occasionally dropping two seconds at once. **If that shows up on stream**, the fix is to call the same `my_time` publisher from `_refresh_powerups_task` as well, which makes the clock 500 ms — still without a new task. Do not start there.

Render side:

- Register the id in the widget tuple at [src/gui_in_game_overlay_window.py:420](../../src/gui_in_game_overlay_window.py:420), add defaults to `IN_GAME_OVERLAY["widgets"]` in [src/app/config.py:117](../../src/app/config.py:117) (`{"enabled": ..., "x": ..., "y": ..., "scale": 1.0}`), add the checkbox/scale controls in `gui_in_game_overlay_settings.py`, add an HTML builder beside `build_powerups_overlay_html` in [src/projections/in_game_html.py:227](../../src/projections/in_game_html.py:227), carry the data on `InGameOverlayProjection` ([src/projections/in_game.py:10](../../src/projections/in_game.py:10)) and paint it in the `_overlay_fast_tick` body next to the `powerups` block at [src/gui_in_game_overlay.py:363](../../src/gui_in_game_overlay.py:363).
- Anything not carried on the projection is simply invisible to the widgets — that is documented on the dataclass and has already shipped as a bug once.
- `remaining` is computed **in the HTML builder**, from the carried mark and the carried `my_time`, not at read time. A `remaining` frozen at read time would be up to a full lane interval stale by the time it is painted.
- Ordering needs no sort: one dictionary layout held for the entire run, the lantern never left slot 15 and its pointer never moved. Preserve dictionary order.

##### Validation

Closed on 2026-08-03, all on Forest with a lantern equipped: stack scaling at
x1/x3/x4/x5, twelve consecutive re-arms, two stack pickups, the first pickup
from an empty slot captured at 20 Hz, a Stage 1 → 2 transition, two pauses
(4.3 s and 17 s), and 97 s on the death screen. Each is recorded in the sections
above with its numbers.

**The first pickup is not a validation item at all** — it is resolved by design.
The widget is **level-triggered on the inventory**, never
edge-triggered on a pickup: it renders whatever timed items are in the
dictionary this pass, so there is no pickup event to detect and nothing to miss
if a pass is skipped. Same reasoning as the One Ring announcer, which reaches
the same conclusion from the opposite direction — an edge would have to survive
a torn read to fire at all.

The questions that were hiding behind it are all absorbed by guards that exist
anyway, so none of them can produce a visible defect:

| Question | Measured answer | Guard, kept anyway |
| --- | --- | --- |
| Is the item in the dictionary before pickup, with `amount = 0`? | **No.** Absent from all 851 pre-pickup reads; the entry appears with the pickup. | render only `amount >= 1` |
| Is `nextExplodeTime` garbage for a tick after a fresh pickup? | **No.** `cooldown 42.00` and the mark are both correct on the *same* read the entry first appears on — the fields are written with the entry, not after it. Zero ticks at 20 Hz with `cooldown <= 0`. | skip `cooldown <= 0` — insurance against an unobserved state, not a fix for a known one |
| Can `remaining` be negative? | **Yes**, for up to one read interval before a re-arm is seen (`−0.01` measured). | clamp at zero |

The dictionary `version` bumped 4 → 5 with the added entry. Together with the
earlier measurement that a *stack* change leaves the version untouched, that
closes the cache-invalidation story: the version sees new items, never changed
ones — which is exactly why addresses may be memoised and values may not.

Still open, none of it blocking:

- ~~**Graveyard crypt/boss transitions.**~~ **Closed 2026-08-03**, and closed against the shipped reader rather than raw bytes — see below.
- **A second item for the layout table.** Resolved from `dump.cs` rather than guessed: of 86 `ItemBase` subclasses, 33 own a timing-shaped float and 30 own an absolute mark, but almost all of those are sub-second tick timers. Only three share the lantern's shape — an explicit effective-`cooldown` float paired with a mark — and are therefore worth rendering:

  | Class | `cooldown` | mark |
  | --- | --- | --- |
  | `ItemToxicBarrel` | `0x40` | `readyAtTime` `0x44` |
  | `ItemGoldenShield` | `0x44` | `readyAtTime` `0x48` (second pair: `selfDamageCooldown` `0x50` / `nextSelfDamageReadyTime` `0x4C`) |
  | `ItemEnergyCore` | `0x3C` | `nextSpawnTime` `0x44` (plus `nextOrbTime` `0x4C`, an intra-burst timer) |

  None were in the tested inventory, so all three are dump-derived only. Confirm the period live before adding one: a name says what a field *is*, not whether its period is long enough to be worth a line on screen — `ItemGlovesBlood` has a textbook `cooldown`/`readyAtTime` pair and runs at ~3.7 s.
- ~~**A characterization test.**~~ **Done** — `src/tests/test_item_cooldowns.py`, 19 tests over a fake memory backend: the countdown, the re-arm jump, the backwards re-arm on a pickup, the negative-`remaining` tick, a frozen clock across passes, a torn field, a torn stack count, a class with no layout entry, a class-name mismatch, a drained dictionary, and a stale layout from another dictionary. `max(5, 45−3n)` is asserted at n = 1/3/4/5.

  Tamper-tested against removal of the class-name check, the `cooldown <= 0` guard, the per-item error isolation, the entries-aware resolver, and the layout-ownership check. **One test was found vacuous and replaced**: the cost assertion read "warm pass < cold pass", which a tamper that walked the dictionary twice satisfied happily because it inflated both sides. It asserts exact read counts now (23 cold, 16 warm, 3 of them floats) and catches that tamper. A relative bound cannot see a defect that scales both sides of the comparison — which is the only defect a cost test exists to find.

Reference tools:

- `tools/scan_timed_items.py` — parses `.tools/il2cppdump_out/dump.cs` and prints every `ItemBase` subclass owning a timing-shaped float, split by whether it carries an absolute mark. This is what produced the 86/33/30 counts and the three-candidate shortlist above. Run it first when adding an item; it is the cheap half of the work and it is what stops a value-based guess from ever being made.
- `tools/probe_item_cooldown.py` — live console view: stack count, effective cooldown, `nextExplodeTime` and remaining seconds every 500 ms, plus the rest of the passive inventory. Read-only.
- The 2026-08-03 capture used a second, throwaway variant that appended a full raw field block per item to JSONL instead of clearing the screen. **That is the form worth rebuilding if this ground is ever re-walked** — the pickup re-arm rule, the eight false-positive tick timers and the death-screen behaviour are all deltas across ticks, and none of them are visible in a display that overwrites itself. Log `stage_index`/`stage_timer` alongside, or a transition cannot be located afterwards, and write to a per-process file: two capture processes appending to one path corrupted 25 lines out of 5322 by interleaving.

---

## Recently Handled Items (Archived 2026-07-26)

### Twitch Commands

#### 2. Item Rarity Loot Tracking (`!luck` / Luck Rarity Widget / OBS Overlay / Live Stats)

Status: `[Archived]`

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

- `[game]` **Microwave** takes **one item per use and returns one** of the same tier. A microwave's own rarity sets how many uses it has — green 3, blue and purple 2, legendary 1 — and it is spent once they are gone. `[dump]` `InteractablesStatus.usesLeft` is at `+0x84`. The audit's reading of those 3/2/2/1 figures as a *per-craft item cost* was wrong; they are the appliance's use count. Measured live 2026-07-25: three crafts, one item consumed each, `numUsed` moving only after the third.
- `[game]` Graves and Pots do not yield items.
- `[game]` No other item source is known to exist.
- `[asm]` `Clover` and `Beacon` have no special branch in the roll; `Clover` simply raises the Luck stat. Difficulty, stage index and map type do not affect the weights.
- `[assumed]` One chest opening yields exactly one item. Duplicates stack (`ItemBase.amount`) and remain full rolls. `Key` (id 0) is in the Common pool; `CageKey` (69) and `CryptKey` (81) are `EItemRarity.Quest` and excluded from drop pools — consistent with `rarity=None` in our table. Banishing removes an item from its tier pool but does not alter the weights.

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

#### 1. Item Rarity Loot Tracking — Implementation Plan

Status: `[Partial / Archived]`

Note from step 4, which the plan did not anticipate: the rarity model had to move from `src/projections/in_game_html.py` down to a new `src/core/luck_rarity.py` before the tracker could use it at all — `core/` may not import `projections/` (§2 layer table), and this step is the model's second consumer. `in_game_html` re-exports both public names, so the overlay, its window and `tools/replay_loot_expectation.py` still import them at the old address.

Note from step 1's tamper check, worth keeping: a naive decrease that skips confirmation passed the **entire** existing `test_live_run_tracker.py`, including `test_tracker_does_not_double_count_after_transient_item_drop`, whose sequence ends before the re-armed increase is confirmed. A test named for the scenario is not the same as a test that covers it.

Outstanding from step 3: `src/tests/test_read_census.py` loads `tools/read_census.py` by path, and `tools/` is gitignored (`.gitignore:54`), so the census update for the new `LUCK` source cannot be committed. The test therefore guards nothing on a clean checkout. Either except that one file from the ignore or stop treating the test as protection.

The design, the verified game mechanics, the measured constants and the output formats all live in item 5. **Read item 5 first; this item is the build order only.** Nothing here re-opens a decision made there — where this plan says something is decided, it is decided, and the reasoning is in item 5.

Six steps. Steps 1 and 2 are independent of the rest and each fixes something on its own, so they can land separately.

---

**Step 1 — Handle item-count decreases in `process_item_deltas`**

`src/core/tracker/items.py:117`, with `_PendingItemIncrease` in `src/core/tracker/snapshots.py`.

The function copies previous counts into `confirmed_counts`, and its `current_count <= confirmed_count` branch drops the pending entry and `continue`s without writing back. `previous_item_counts` is therefore monotonically non-decreasing for the life of a run.

- Add a confirmed-decrease path **symmetric with the existing increase path**. Increases are held pending and credited only when a later read agrees, because the game rebuilds the item array in place and a mid-write read shows a torn count. Do the same for decreases: one low read is a torn read until a second confirms it. A plain assignment would make every torn read look like a microwave craft in step 4.
- Expose the confirmed decrease as an observable event, not only as a baseline adjustment — step 4 consumes it as the microwave signal.

This is a live bug independent of the feature: after an item leaves the inventory, its stale high baseline means re-acquiring it never registers, so `process_item_gain` never fires and the tracked-item rules behind the OBS overlay, Session Stats and the Twitch commands silently miss it.

Tests in `src/tests/`, alongside `test_live_run_tracker.py` and `test_passive_items_fast_lane.py`:

- a single low read does not lower the baseline; a second agreeing read does;
- a torn read that dips and recovers produces neither a gain nor a loss;
- after a confirmed decrease, re-acquiring the same item credits the gain exactly once.

Done when: those tests pass and no existing item-delta test regresses.

---

**Step 2 — A narrow `LUCK` source**

`src/app/read_sources.py`, `src/infra/memory/player_stats_client.py`.

- Add a reader for stat `30` alone and give it its own key. Do **not** reuse the `PLAYER_STATS` key: it resolves a full per-stat walk, which would then run on every fast pass.
- No task yet — step 3 is where it gets consumed. Keeping the reader separate from the wiring makes the memory-side change reviewable on its own.

Done when: the source exists and resolves the same value the full snapshot reports for `Luck`.

---

**Step 3 — Read the whole loot sample in one pass**

`src/app/refresh_tasks.py` (`_refresh_passive_items_task`, around line 486), `src/app/player_stats_refresh.py:288`, `src/gui_in_game_overlay.py`.

Make the existing `passive_items` task consume **three** sources in the same pass: `PASSIVE_ITEMS`, `MAP_ACTIVITY_VALUES` and the new `LUCK`.

- This is the point of the whole shape. Within one `RefreshTickContext` a key resolves once and every consumer in that pass sees the same value, so items, counters and Luck all carry one timestamp. Step 4's Moai and merchant exclusions need that — at this cadence the counter increment and the gain land in the same tick — and the "which Luck applied to this roll" question disappears rather than needing a matching buffer.
- The counters cost no extra read: `get_map_activity_values` (`src/infra/memory/game_data_client.py:517`) already walks the whole dictionary and returns every key. The 10 s snapshot keeps its own consumption — `chests_total`, `pots_total` and `PowerupMapContext.from_activity_max`, **not** Stage Summary, which does not use this source — and the pass cache shares one physical walk whenever both are due. Reading it every second also fixes `PowerupMapContext` being absent for the first ten seconds of every run, which the comment at that site already notes.
- Publish Luck on `RuntimeStateSnapshot` and repoint the In-Game Overlay `luck_rarity` widget at it. The widget currently reads `latest_snapshot.stats["Luck"]` on the 10 s slow tick (`_refresh_in_game_overlay_slow_widgets`); move it to the fast tick and update the comment there, which explicitly justifies the slow pairing this step removes. Drop `luck_rarity` from `in_game_overlay_requires_player_stats_refresh`.
- Check the task's `required` predicate still fits. `passive_items` uses `_should_refresh_full_player_snapshot`; confirm that covers the case where the Luck widget is enabled, since Luck now rides this task.
- **Error policy, decided:** the full snapshot stays the health owner for `MAP_ACTIVITY_VALUES`. It records health in its own task body rather than through `read_source` callbacks, so a second consumer does not steal that accounting — whichever task resolves the key first performs the physical read, and the snapshot still records its own success or failure from the cached result. The item task keeps swallowing failures the way it already does for `PASSIVE_ITEMS`. Put the reasoning in the code comment; the existing one there explains the equivalent decision for `PASSIVE_ITEMS`.
- Optional, a few lines: skip the fast dictionary walk once `numUsed == numTotal` for all three keys, via `RefreshTask.required`. The counters reset per map so it re-arms each stage, and it never fires if the player leaves one statue untouched. Worth having, not worth much.

Done when: one tick yields items, counters and Luck together; the Luck widget updates at the fast cadence; memory-health behaviour for `MAP_ACTIVITY_VALUES` is unchanged from today.

---

**Step 4 — The loot tracker**

New `src/core/tracker/loot.py`, modelled on `src/core/tracker/chests.py`; snapshot type in `src/core/tracker/snapshots.py`; wired through `src/core/tracker/live_run.py`.

State per run: `actual[tier]`, `expected[tier]`, the tracked-acquisition count, an availability flag, and the pending structures below. Copy the `expected_detected_run_reset` pattern from `_ChestState` so a spurious reset does not wipe a valid run.

Rules, all already decided in item 5:

- Every confirmed item gain is a roll. Accumulate `expected[tier] += P(tier | Luck_j)` using `calculate_luck_rarity_probabilities` (`src/projections/in_game_html.py:157`). `Luck_j` is the value read in the **same pass** as the gain, courtesy of step 3 — no buffer, no nearest-sample matching. A gain confirmed a tick late still carries the Luck from the pass that observed the rise, because `_PendingItemIncrease` holds that snapshot.
- Rarity resolves through `ITEM_RARITY_BY_NAME` and `normalize_item_name_for_rarity`. **If it does not resolve, the gain contributes to neither side** — that is what makes Corrupt-chest items and post-update unknown items harmless.
- **Microwave:** a confirmed decrease opens a *debt* for the consumed tier; the next gain of that tier settles it and is not counted. No timer — the craft output lies on the ground until collected. Debts queue; clear outstanding debts on map generation.
- **`Za Warudo` never opens a debt.** It leaves the inventory when the player dies, and treating that as a craft would swallow the next genuine legendary.
- **Moai:** a counter increment excludes the *next* gain, 3 s forward window.
- **Shady Guy:** a counter increment excludes the *preceding* gain, 2 s backward window.
- Where a window cannot be resolved, drop the affected gain from **both** sides.
- Late attach is a hard unavailable state — both `actual` and `expected` are wrong once existing items are absorbed into the baseline by `initial_item_increase_candidates`.
- Log map-spawned chest openings beside the acquisition count. Gains must always be at least that number, and the excess is the standing check that no unknown source exists.

Tests — this is the part that matters. The powerup timing work needed two live captures to find behaviour that had looked obvious, and this is the same shape of state machine over noisy reads.

*Exclusions*

- a decrease opens a tier debt; the next same-tier gain settles it uncounted, while other-tier gains in between count normally;
- a second decrease before the first settles queues rather than replaces;
- debts clear at map generation, and a same-tier gain after that boundary counts;
- a `Za Warudo` decrease opens no debt;
- a Moai increment excludes the next gain, a Shady Guy increment the preceding one;
- an increment with no gain in its window expires without excluding anything;
- the counters resetting at map generation is not read as an increment.

*Accumulation*

- expectation uses the Luck sampled at the gain's timestamp, not at confirmation;
- an unresolvable rarity contributes to neither side;
- a stack increase on an already-owned item counts as a full roll;
- attaching mid-run yields the unavailable state, not partial numbers;
- a new run clears state, and a spurious reset does not.

Done when: those tests pass and `tools/replay_loot_expectation.py` still reproduces its recorded table — it exercises the model, not the tracker, so it must be unaffected.

*Landed 2026-07-25 as `src/core/tracker/loot.py` and `src/tests/test_loot_rarity_tracker.py`, thirteen tests.* Each was tamper-checked by breaking the decision it names and confirming it reddens — a green suite proves nothing here, as step 1 established:

| decision broken | test that reddened |
| --- | --- |
| the debt never settles | `..._a_decrease_opens_a_tier_debt...` (and the queue test with it) |
| a repeat debt dedupes instead of queueing | `..._a_second_decrease_before_the_first_settles_queues` |
| map generation leaves debts standing | `..._debts_clear_at_map_generation` |
| `Za Warudo` opens a debt | `..._za_warudo_leaving_the_inventory_opens_no_debt` |
| the two window directions swapped | `..._moai_excludes_the_next_gain_and_shady_guy_the_preceding_one` |
| the forward window never expires | `..._an_increment_with_no_gain_in_its_window_excludes_nothing` |
| a counter *drop* read as movement | `..._counters_resetting_at_map_generation_is_not_an_increment` |
| Luck taken at confirmation | `..._expectation_uses_the_luck_at_the_gain_not_at_confirmation` |
| unresolvable rarity defaulted to a tier | `..._an_unresolvable_rarity_contributes_to_neither_side` |
| `gained_count` forced to 1 | `..._a_stack_increase_on_an_owned_item_is_a_full_roll` |
| the late-attach grace widened | `..._attaching_mid_run_yields_the_unavailable_state` |
| the run clearing made a no-op | `..._a_new_run_clears_state` |
| the `expected_detected_run_reset` guard removed | `..._a_spurious_reset_does_not_wipe_a_valid_run` |

One mutation was **survived**, and it is worth recording rather than patching: removing `loot.reset` from `_reset_for_new_run` leaves `..._a_new_run_clears_state` green, because the loot lane recognises a run clock that has gone backwards on its own and has already cleared by then. Two mechanisms enforce one property; the test asserts the property. Deleting the clearing itself reddens it.

The first version of the stack test was also survived, which is the more useful finding: `x1 -> x2` yields `gained_count == 1`, so it never exercised the multi-copy path at all. It now goes on to `x2 -> x4` in one pass.

---

**Step 5 — The four output surfaces**

Formats are fixed in item 5's Deliverables. Do not redesign them.

- **Twitch `!luck`** — `src/twitch_bot.py`, dispatch around lines 229-269, plus a `commands_cfg` entry and the Twitch settings panel. One pipe-separated message. Uses the **game's** rarity vocabulary (`Legendary / Epic / Rare / Common`), which differs from our internal keys by one tier. When unavailable, the actual and expected halves drop and only the chances remain.
- **In-Game Overlay** — `src/gui_in_game_overlay_window.py` (`LuckRarityOverlayWidget`), `src/projections/in_game_html.py`, settings in `src/gui_in_game_overlay_settings.py`, defaults in `src/app/config.py`. A `Show Expected Frame` toggle beside `show_bar`, plus `expected_layout: "column" | "row"` as a sub-option of the frame, defaulting to `column`. Anchor the block to the percentage row, not to the bar. Colours from `ITEM_RARITY_COLOR_MAP`; expected in the muted separator grey. Handle the height change tripping `_keep_widgets_inside_bounds`.
- **OBS Overlay** — `src/projections/obs.py` and the widget config list in `src/app/config.py`. Same content and layouts, its own copy of both toggles. `projections/` may import `core/` only, so publish the summary on `RuntimeStateSnapshot` rather than computing it in the projector.
- **Live Stats** — a new `Loot` tab in `src/ui/tabs/player_stats/`, holding the existing chest card moved across unchanged plus the new four-line rarity card. Leave an empty placeholder card where the chest card was in `Stats`. Label this card's `Expected` distinctly from the chest card's, which counts key procs.
- **Recordings** — serialize the per-tier totals into the recording snapshots, behind its own Compare Runs toggle. Older recordings lack the field and need an explicit missing-value path, not a zero.

*Formatting tests*

- one decimal below 10, whole numbers above;
- the unavailable state drops the actual and expected half of the Twitch line and keeps the chances;
- both overlay layouts emit four cells in `LUCK_RARITY_ORDER`.

---

**Step 6 — Live run and the residual check**

Play a full ordinary run with the app attached from the start, then compare the tracker's totals against `tools/replay_loot_expectation.py` on the same recording.

They will **not** match, and that is correct. The replay works from 10 s snapshots, so it shares one Luck sample across several gains and cannot apply any exclusion at all. The live tracker should land *closer* to expectation than the replay does.

The specific thing to check: the replay leaves a `+1.5` sigma residual on UNCOMMON, attributed in item 5 to the un-excluded Moai and merchant items. With the exclusions live, that residual should shrink. **If it does not, an item source exists that this design does not account for** — and the logged gap between acquisitions and map-spawned chest openings is where it will surface.

### Live Run Refactor Fixes

#### 1. Powerup Timing: Repeat Pickups and Multiplier Stability (Refactor Fixes)

Status: `[Partial / Archived]`

Goal:

- Keep an active powerup's pickup and expiry marks stable while the buff is refreshed by repeat pickups of the same type.
- Stop the Twitch `!powerups` command from reporting `none active` when the reader is merely a tick behind rather than genuinely empty.

Problem Analysis:

- **The game keeps `added_time` at the first pickup.** Re-picking an active buff rewrites `expiration_time` but leaves `added_time` untouched, so `expiration_time - added_time` grows on every refresh. The sanity window that exists to reject records surviving a timer epoch eventually rejected a mark that had been observed continuously, and the pickup mark jumped.
- **The expiry mark is coupled to the pickup mark.** `raw_expiration` looks independent of duration, but `resolve_ui_context` is resolved *from* `pickup_time = expiration_time - duration`. On Graveyard the `pickup_time >= my_time - final_swarm_timer` branch switches the timer between `stage_timer` and the final-swarm clock, so any wobble in the computed duration throws the expiry mark across a phase boundary.
- **The multiplier is not a trustworthy duration source at a repeat pickup.** It is served from a `5s` cache whose only force-refresh trigger is a change in the *set* of active effect ids, and re-picking an already active buff does not change that set.
- **A missed read is not an empty read.** `POWERUPS_SNAPSHOT_TTL_SECONDS` (`1.5s`) empties the snapshot on the first missed tick, and the Twitch handler converted that into the literal string `none active`, which is indistinguishable from a successful read that found nothing.
- **Ruled out:** sampling skew between `stage_timer` and `my_time` was investigated and is not a factor. `get_powerup_tracking_snapshot` reads both back-to-back from the same already-resolved `MyTime` static block, so the pair inside one snapshot is coherent. The `250ms` fast lane publishes a separate `FastStageTimerContext` that `apply_snapshot` never consumes.

Implemented:

- Per-effect observation history in `_PowerupState`, reconstructing "still the same buff" from `added_time`, clock direction, and expiry monotonicity, since the game exposes no instance id.
- An effect's duration is frozen while nothing about it moves, so a single bad multiplier read cannot re-time a buff the game already committed to.
- When the pickup itself is caught, the duration is taken as `expiration_time - added_time`, which the game writes in one frame and which no multiplier read can distort.
- At a repeat pickup the duration is bounded by the game's own numbers rather than by the multiplier: the pickup happened between the previous read and this one, so `expiration_time - my_time <= D <= expiration_time - previous_my_time`. The multiplier is believed only inside that one-tick-wide window.
- A *changed* multiplier must be read twice before it is published, so a one-frame misread never reaches the duration maths.
- `powerups.recent_snapshot` keeps the last read past the strict TTL and marks it `stale`; the Twitch handler now separates fresh, stale, and absent, and never invents `none active`.

Live validation on 2026-07-24:

- 353 ticks over 176s, 10 repeat pickups across 4 effect types.
- `added_time` never moved on a repeat pickup and the pickup mark never jumped; zero reads were rejected. One capture reached `expiration_time - added_time` of 252s against a 224s window, which the previous logic would have rejected.
- One repeat pickup recorded 98.07s for a buff the game had granted 111.6s of, caused by the multiplier cache being a full TTL behind. Replaying the capture through the new bound reduces the worst repeat-pickup duration error from `13.50s` to `0.48s`.
- The maximum gap between reads was `0.505s`, with none above `0.7s`. The powerup snapshot therefore never went stale during the capture, so the Twitch stale and absent branches were never exercised by it.

Second live capture on 2026-07-24, with `Powerup Multiplier` deliberately raised immediately before each repeat pickup:

- 152 ticks over 76s, 3 repeat pickups. `added_time` never moved and the pickup mark never jumped.
- One repeat pickup landed on the last tick before the multiplier cache caught up: memory held `9.136` while the published value was still `8.576`. The bound recorded the granted `136.63s` exactly, where `base * multiplier` would have recorded `128.64s`. Replaying the same capture with the bound removed reproduces that `-7.99s` error, so the branch is confirmed rather than merely unexercised.
- Worst repeat-pickup duration error across the capture: `0.33s`.
- This closes live verification for the repeat-pickup duration bound. The Twitch branches remain unexercised; the maximum read gap was again `0.504s`.

Remaining open work:

- Live-verify the Twitch stale and absent branches. Waiting for a natural stall is impractical at the observed read cadence; this needs `POWERUPS_SNAPSHOT_TTL_SECONDS` and `POWERUPS_SNAPSHOT_GRACE_SECONDS` temporarily shrunk so the branches are reached deliberately.
- The multiplier display and `standard_duration_seconds` can still lag up to the cache TTL at a repeat pickup, for the same force-refresh reason. Effect durations no longer depend on it, so this is cosmetic. The proper fix is to include expiration times, not just effect ids, in `active_signature`.

#### 2. Game-Time Synchronized KPS Calculation (Refactor Fixes)

Status: `[Implemented]` — design settled against live measurement on 2026-07-26, shipped and re-measured live the same day (see Validation). One end-to-end check remains: that the app's on-screen `current_ui_kps` tracks the verified algorithm.

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

**There is no settling period, and the tick will not lock to the HUD.** Observed on screen 2026-07-26 as "sometimes synchronized with the in-game timer, sometimes not", which is two separate effects and neither is convergence — the only warm-up is the single second at the start of a run or reattach, during which nothing is published at all.

- **A small phase offset that drifts.** A crossing is noticed at the first poll *after* it, not at the crossing. Measured on the clean capture: 23–106 ms late, mean 0.048 s over the first half-minute against 0.085 s over the second — about 1.2 ms per second, so the offset walks the whole poll interval (0–500 ms) in roughly seven minutes and wraps. It drifts away from alignment exactly as readily as toward it. The *rate* is exact regardless: 1.000–1.016 s of wall clock between publications, no game second skipped in 59 publications.
- **Under real lag, whole seconds are skipped, and that is intended.** In the stall capture 10 of 45 publications covered two game seconds at once, so the readout updates every 2 s. The kills are not lost — the window widens to a 1.496 s median — which is the whole point against the old gate's 11.5-second freeze.

The drift is set by the poll grid, not by the formula, and cannot be removed here. `FAST_TRACKER_INTERVAL_MS` halves or fifths it directly; **after this change that is a cost/precision decision rather than a correctness one**, which is the decoupling argued for above.

###### Considered and rejected: chasing the boundary with a variable interval

Proposed 2026-07-26 — shrink the poll interval to 1–10 ms as the boundary approaches, catch `1.000` exactly, then widen again with the phase locked. Measured before answering (tight-loop poll of `run_timer`, 680k reads over 12 s):

| quantity | measured |
| --- | --- |
| cost of one `run_timer` read | 13 µs median, 33 µs p95 |
| times the value in memory actually changes | 71/s |
| wall gap between changes | 13.7 ms median, 18.4 ms p95, 26.2 ms max |
| game-time step per change | 12.7 ms median |

The field is written once per frame, so **the observable floor is half a frame, ~7 ms, not 1 ms** — at 1 ms polling the same value is re-read ~800 times per change. Under load the frame rate drops and the floor coarsens with it. Rejected for three reasons, in order of weight:

- **It cannot change the number.** Both ends of the window are `run_timer` values taken from the history, so noticing a crossing 20 ms or 400 ms late yields a bit-identical result. Only the repaint instant moves; the entire payoff is cosmetic alignment of the tick edge with the HUD.
- **A one-time lock does not hold.** Widening the interval again re-quantizes the detection lag to the new grid, leaving nothing behind. Holding the phase requires re-acquiring every second — sleep ~0.98 s, then close the last ~20 ms with fine reads. Cheap in CPU (~0.4 ms/s) but a different mechanism from the one proposed: a predictive scheduler, not a synchronization phase.
- **The scheduler is the real obstacle, not the cost.** The fast lane is one Qt timer on the GUI thread feeding five tasks, so a variable interval re-times the other four as a side effect; and Windows' default timer resolution is 15.6 ms, so a 1–10 ms `QTimer` will not fire reliably and a busy-wait on the GUI thread is not an option. It needs its own thread, with its own races against the shared read pass.

**If it is ever built, it belongs to the Event Timer item below**, whose `GameTimerSynchronizer` already specifies "predicts the next boundary only to improve read scheduling". There the payoff is real, because that feature displays the time itself rather than a derivative of it — and KPS would inherit the scheduling for free. Building it under KPS first means writing it twice.

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

##### As Shipped (2026-07-26)

- `track_ui_kps` ([combat.py:88](../../src/core/tracker/combat.py:88)) now publishes on integer-second crossings of `run_timer` and measures over the last ~1.0 game second of `recent_kills_history`. `_CombatState.ui_kps_baseline` is replaced by the integer cursor `ui_kps_second`; `UI_KPS_WINDOW_SECONDS = 1.0` and `UI_KPS_BASELINE_TOLERANCE_SECONDS = 0.05` are module constants. The module docstring was rewritten — the two KPS notions now differ only by window and emission rhythm.
- `_last_fast_kps_game_time_seconds` is deleted from `PlayerStatsRefreshTasks` (initializer, write site, and the ownership paragraph in the module docstring).
- New coverage: [test_ui_kps_game_time.py](../../src/tests/test_ui_kps_game_time.py), 10 cases at the pure-function level. Tamper-tested against the pre-change implementation: 8 of the 10 fail there. The two that do not — reset-clears-the-window and the zero floor — cover semantics both algorithms share and are kept for completeness, not counted as coverage of this change.
- One existing test moved with the behaviour: `test_overlay_state_includes_kps_metrics` fed samples 60 s apart and asserted `current == 50`, a figure the 0.9/1.2 s gate produced by keeping a stale value from second 2. Under a real window those samples give 5, identical to the averages, so the fixture gained a sample at `119.0` and now asserts `current == 60`.

##### Validation

Re-measured live on 2026-07-26, after implementation. `tools/probe_kps_sync.py`'s `window_1s` monitor no longer mirrors the shipped code — it *is* the shipped code, driven through `combat.track_kills` against a real `_CombatState`, so these rows exercise `src/core/tracker/combat.py` itself against live memory. Both captures at `interval=0.5` against an active fight; read spans stayed at 0–15 ms, far under `KPS_GROUP_SPAN_LIMIT_SECONDS`, so the coherence gate withheld nothing.

**Clean cadence, 60 s, 121 samples** (`run_timer` delta 0.474–0.526 s per poll):

| monitor | publishes | ticks lost | window used |
| --- | ---: | ---: | --- |
| current (0.9/1.2 gate) | 60 | 0 | — |
| shipped (`window_1s`) | 59 | 0 | 0.979–1.021 s |

The shipped algorithm's one fewer publication is the warm-up second, where the window is not yet filled and it deliberately publishes nothing.

**With emulated driver stalls (1 s at p=0.25 per tick), 60 s, 74 samples:**

| monitor | publishes | ticks lost | window used | worst display freeze | peak value |
| --- | ---: | ---: | --- | ---: | ---: |
| current (0.9/1.2 gate) | 18 | **21** | — | **11.5 game seconds** | — |
| crossing, baseline = publishing sample | 46 | 0 | 0.487–2.015 s | 2.0 s | 372 |
| shipped (`window_1s`) | 45 | 0 | **0.955**–2.020 s | 2.0 s | 270 |

This reproduces the pre-implementation prediction on all three counts: the current algorithm loses roughly a third of its ticks and freezes the readout for over eleven game seconds; the shipped one loses none; and the rejected baseline variant is again visible as a spike — 372 against 270 over the same fight, from dividing by a 0.487 s window. The shipped window never collapses below 0.955 s (the `TOLERANCE` floor of `1.0 - 0.05`), and its 1.496 s median under stalls is the designed smoothing: a late read widens the window rather than losing the kills.

Still owed: confirming end to end that the app's own `current_ui_kps` tracks these numbers on screen. The algorithm is verified against live memory; the plumbing between it and the four consumers is not.
- **Open measurement, worth doing before implementing:** the stalls above were *emulated*. Log `lost_overshoot` occurrences from the real Qt-driven fast lane over a ten-minute run. If the production driver loses ticks at a rate comparable to the emulation, this change has a measured payoff; if it loses as few as the probe's tight loop did (zero in 40 s), the item is a correctness improvement for a rare condition and should be prioritized accordingly.

Benefits:

- KPS remains strictly anchored to `run_timer` rather than to application wall-clock time;
- UI updates follow the rhythm of the game's own elapsed seconds, which is also the HUD's;
- missed or delayed fast-ticks no longer create empty output windows — measured 42 publications against 13 under stalls;
- the measurement window cannot collapse below ~1 game second, so a late read produces a smoothed value rather than a spike;
- pauses preserve the last valid KPS and do not create false activity;
- the scope is isolated from stage/map logic, so it can be implemented and characterized independently.

---

## Recently Handled Items (Archived 2026-07-24)

### Live Run Refactor Fixes

#### 1. In-Game Overlay Graveyard Difficulty & XP Gain Stat Caps (Refactor Fixes)

Status: `[Implemented]`

Goal:

- Extend stat capping logic in `_build_in_game_stats_rows` (In-Game Overlay Stats widget) to include the Graveyard map, enforcing XP Gain (10x) and Difficulty (571% for first 2 minutes) stat caps.

Problem Analysis:

- **Graveyard Explicitly Excluded:** `_build_in_game_stats_rows` contains `if not is_graveyard and raw_val is not None:`, which completely bypasses stat capping and cap highlight colors when playing on the Graveyard map.
- **Missing Difficulty Cap for Graveyard:** On Graveyard, the difficulty cap for the first 2 minutes (before 2m ghost spawn) should be 571% (5.71), identical to Tier 1 Stage 0.

Planned Solution:

- Remove `not is_graveyard` exemption in `_build_in_game_stats_rows`.
- Define Graveyard difficulty capping rules (cap at 5.71 / 571% for the first 2 minutes of the stage, matching Tier 1 Stage 0 rules) and ensure XP Gain 10x capping applies to Graveyard as well.

Shipped Behavior:

- The `not is_graveyard` guard is gone, so XP Gain now shows ` / 10x` and turns
  red on Graveyard exactly as it does elsewhere. Note that the *value* was
  already clamped to `10x` there -- `_format_stats_display_value` never consulted
  `is_graveyard` -- so what was missing was only the cap suffix and the colour.
- Difficulty on Graveyard follows the Tier 1 Stage 0 rule: **5.71 / 571%** before
  the boundary, **4.95 / 495%** after it, where the boundary is
  `stage_timer >= stage_duration + 120` -- the same formula the other maps use.
- **Graveyard must not read the tier table.** Its raw `stage_index` is not a
  tier: it stays at whatever stage pointer the map reuses (observed as `2`), so
  simply deleting the exemption as originally planned would have applied the
  Stage 3 caps (457% / 381%). Graveyard gets its own branch that ignores
  `stage_index` entirely.
- The Graveyard boundary uses the fixed `_GRAVEYARD_STAGE_DURATION_SECONDS`
  (960 s) rather than the snapshot's `stage_duration_seconds`, for the reason
  already documented in `build_event_timer_overlay_html`: on Graveyard that field
  is a live timeline marker, not the map's duration. The literal in the Event
  Timer now reads from the same constant so the two schedules cannot drift.
- One rule covers the whole map -- crypts, main map and boss room alike --
  because the projection has no phase marker to distinguish them yet.

Covered by three cases in `test_in_game_overlay_render.py`: the 1079 s/1080 s
boundary pair, a subtest sweeping `stage_index` 0/1/2 to prove the tier table is
bypassed, and the Graveyard XP Gain cap.

#### 2. Stage Summary Card Ledger (Compare Runs Optimization)

Status: `[Implemented]`

Goal:

- Stop rebuilding Stage Summary from scratch on every scrub frame. Fold each
  recording once into an ordered list of per-index **stage cards**, then let
  Compare Runs, Recordings and Live Stats read the card for the selected index
  instead of re-deriving it.

Problem Analysis:

- **The only prefix-dependent section is quadratic across a drag.**
  `_build_compare_run_stage_summary_rows` (`src/projections/formatting.py:370`)
  calls `build_stage_summary(snapshots[: index + 1])`, and
  `build_stage_summary` is a pure fold over that whole prefix. Cost grows with
  the selected index, so a drag across the timeline is O(n^2).
- **The same fold is paid by two other surfaces.**
  `src/ui/tabs/player_stats/recordings.py:454` re-folds the prefix on every
  Recordings scrub, and `src/ui/tabs/player_stats/live_stats.py:420` does the
  same for the live timeline.

Solution & Implementation:

- Implemented memoisation and ledger caching for Stage Summary calculations across Compare Runs, Recordings, and Live Stats.
- Stage Summary O(N) fold per frame optimized and archived as completed.

#### 3. OBS Overlay Stats Widget Short Stat Labels (Refactor Fixes)

Status: `[Implemented]`

Goal:

- Align stat display names in the OBS Overlay Stats widget with the abbreviated/short label formatting used in the In-Game Overlay Stats widget and Twitch `!chaos` command output.

Problem Analysis:

- **Label Format Inconsistency:** The In-Game Overlay Stats widget and Twitch bot output use compact stat abbreviations (e.g. `abbreviate_stat_label`), whereas the OBS Overlay Stats widget formats stat rows with full names, creating visual clutter in compact OBS browser source layouts.

Shipped Solution:

- `_snapshot_stats` (`src/projections/obs.py`) now emits a `display_label`
  alongside the existing `label`, exactly as the In-Game overlay rows do
  (`projections/in_game_html.py`). `label` stays the canonical full stat name,
  so the stat selector, saved overlay configs and any custom browser-source
  template that keys off it keep working; only the rendered text changes.
- `renderStats` in `src/media/overlay/overlay.js` renders
  `display_label || label` and measures the stats column width from the
  **short** label. That width calculation is where the compactness actually
  lands -- without it the column would stay sized for `Powerup Drop Chance`
  while displaying `PDC`.
- The editor preview stub (`?edit=True`) carries `display_label` too, so the
  preview matches what a live OBS source renders instead of showing full names.
- Covered by `test_overlay_state_stats_use_short_labels` in
  `src/tests/test_overlay_state.py`, which pins both the abbreviated
  `display_label` and the untouched canonical `label`.

Follow-up (same day): the short form is a **per-widget setting**, not a hard
rule. `short_stat_labels` (default `True`) lives on the stats widget config,
is normalized in `core/overlay_config.py`, and is exposed as the
`Short stat names` checkbox in the OBS tab's Widget Settings -> Advanced ->
Stats section. `_snapshot_stats` resolves `display_label` from it, so the
renderer never re-decides; the `?edit=True` demo rows read the same flag out
of `state.widgets.stats` so the editor previews the layout the live source
will actually render. Pinned by
`test_overlay_state_stats_keep_full_labels_when_opted_out` and
`test_overlay_settings_persist_stats_short_label_choice`; both were confirmed
to fail against tampered source.

#### 4. Items Vanishing From Compare Runs (Passive-Item Layout Cache)

Status: `[Implemented]`

Goal:

- Fix intermittent missing items in Compare Runs item lists caused by incomplete passive-item layout cache memoisation.

Problem Analysis:

- **49 gaps total** where a passive item was present, absent for several consecutive 10 s snapshots, then present again.
- **Root cause:** `_read_passive_item_dictionary` (`src/infra/memory/player_stats_client.py`) memoised the dictionary's slot layout and only invalidated it on a `_version` change (a .NET Add/Remove). A slot skipped without a `MemoryReadError` was memoised as clean, keeping dropped items invisible until the next Add/Remove.

Fix:

- An unnameable-but-live slot is treated like a torn entry (`broken_entries += 1`), skipping it for that read and preventing incomplete layout memoisation so it self-heals on the next read.
- Covered by test cases in `test_passive_item_layout_cache.py`.

#### 5. Future Runtime Data Collection Improvements & Core Lifecycle Probe

Status: `[Implemented]`

Goal:

- Preserve core run-history reads (10s full player snapshot & 500ms expected chest inputs) during an active run even when optional UI/overlay consumers are inactive.
- Implement a unified 1-second Core Lifecycle Probe to drive run state (`is_active_run()`, pause, resume, game over) across tasks.

Implementation Details:

- Extracted and implemented `RunLifecycle` service ([app/run_lifecycle.py](file:///f:/Python/MegabonkReroll/src/app/run_lifecycle.py)) with `CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS = 1.0` re-reading runtime activity state once per second and caching `RuntimeGameState`.
- `RunLifecycle.is_active_run()` covers both `IN_GAME` and `PAUSED_IN_GAME`.
- `refresh_tasks.py` uses `lifecycle.is_active_run()` as an always-on core demand predicate for `full_player_snapshot` (10s) and `expected_chest_inputs` (500ms).
- VOD recording auto-start, pause, resume, and completion handling ([app/vod_capture.py](file:///f:/Python/MegabonkReroll/src/app/vod_capture.py)) are driven from `RunLifecycle`.
- Note: Chaos Tome polling optimization remains tracked as a separate open item in `functional_updates.md`.

#### 6. Compare Runs Diff Cards Are a Rich-Text Layout Problem, Not a Compute One

Status: `[Implemented]`

Goal:

- Make a Compare Runs scrub frame cost ~20 ms instead of ~200 ms by changing how the diff cards are *rendered* (switching heavy cards to widget-based `MetricTableView` instead of re-parsing HTML `<table>`s in `QLabel`).

Shipped Behavior & Results:

- Replaced Weapons, Tomes, Chaos cards and the expanded Items per-item table with widget-rendered `MetricTableView` (`src/ui/metric_table.py`).
- Scrub frame rendering time dropped from ~173 ms down to ~32 ms (~5x speedup).
- Cells are created once and pooled; restyling happens only when cell delta direction changes.

#### 7. OBS Overlay "No Game" and Connection Status Audit (Refactor Fixes)

Status: `[Implemented]`

Goal:

- Audit and refine status handling (`no_game`, `waiting`, `live`, `reconnecting`, `stale`) in the OBS overlay server and web frontend (`overlay.js`).

Shipped Behavior & Results:

- `LiveRunTracker` gained `reconnect_grace_seconds` (10.0s) and a `reconnecting` status between `live` and `stale` to prevent false error states on routine game restarts.
- `overlay.js` holds the last good frame across non-`live` states and tolerates up to 6 failed polls without clearing the DOM.
- Status card styled with `position: absolute` so it never alters widget document flow.

---

## Recently Handled Items (Archived 2026-07-23)

### Live Run Refactor Fixes

#### 1. Compare Runs and Recordings Timeline Performance Optimization (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Added `src/ui/throttle.py` with two primitives: `UiUpdateThrottle` (leading-edge
  throttle with a trailing coalesced run, ~30 FPS window) and `batched_updates`
  (a context manager that suspends Qt repaints for a multi-widget update).
- Split all three timeline sliders into two tiers: the timeline captions are
  written immediately on every `valueChanged`, while the heavy render is
  coalesced to one run per throttle window and always renders the value the
  drag stopped on.
  - `CompareRunsTab.on_compare_run_slider_changed` (both side captions, since
    moving one slider time-syncs the other).
  - `RecordingsTab.on_vods_slider_changed`.
  - `RecordingTimelineView.handle_slider_value` (Live Stats recording strip).
- Added an LRU cache (128 entries) for the seven formatted Compare Runs diff
  sections, keyed by both recordings, both indexes, the enabled sections, the
  selected stat labels, and the item-details toggle. Scrubbing back over a
  previously rendered frame reformats nothing. Cleared when a side's recording
  is replaced or the two runs are swapped.
- Added `SnapshotTimeIndex`: snapshot compare-times are sorted once per loaded
  recording so time-sync is a bisect instead of a full scan per slider tick.
  It reproduces the linear scan's `(distance, index)` tie-breaking exactly.
- Added a dirty check on the Compare Runs diff cards, so an unchanged diff --
  common between consecutive game seconds -- does not re-write seven rich-text
  widgets.
- Wrapped the Compare Runs panel refresh and the Recordings snapshot render in
  `batched_updates`, so each does one Qt layout pass instead of one per widget.
- Queued frames are dropped, not merely superseded, when the selection they
  describe disappears: a Compare Runs load error, and loading or clearing a
  recording in the Recordings tab.

Tests:

- `src/tests/test_ui_throttle.py` -- the two primitives, over an injected clock
  and scheduler.
- `src/tests/test_timeline_scrub_performance.py` -- caption/render split on all
  three sliders, the diff cache and its two invalidation events, the dirty
  check, and `SnapshotTimeIndex` parity against the linear scan it replaces.
- Both files were tamper-checked: reverting each mechanism individually fails
  the case that covers it.

Follow-up: per-frame cost with every section enabled (measured, not estimated)

Throttling bounds how *often* a frame renders, not what one costs. With all
comparison sections checked, a frame still ran ~83 ms on a real 713-snapshot
recording -- a ceiling of ~12 FPS no matter how the events are coalesced.
Profiling put effectively all of it in one section:

| section | before | after |
| --- | --- | --- |
| `stage_summary` | 80.85 ms | 10.00 ms |
| the other six, combined | 2.60 ms | 1.08 ms |
| **full frame, all sections** | **~83.5 ms** | **11.08 ms** (~90 FPS) |

`_build_compare_run_stage_summary_rows` rebuilds `build_stage_summary(
snapshots[:index+1])` -- a fold over the whole run from its first snapshot --
twice per frame, once per recording. Inside it, a single frame asked for
~58,000 item-name normalisations of **58** distinct names, and re-parsed every
snapshot's item list on every pass even though snapshots are frozen.

Both were fixed by memoisation alone; no domain logic changed:

- `lru_cache` on `_fold_item_name_for_rarity`,
  `normalize_item_name_for_rarity` and `normalize_item_name_for_display`
  (83 -> 37 ms). The public entry points still accept non-strings, and a `str`
  subclass is converted rather than trusted as a cache key -- it can redefine
  `__hash__`/`__eq__`.
- `lru_cache` on `item_counts`, keyed by the item tuple (37 -> 11 ms).
  **It returns a fresh dict on every call**: `create_stage_item_gain_tracker`
  stores the result as `confirmed_counts` and then mutates it in place, so
  handing out the cached mapping would corrupt every later reader. Unhashable
  item lists fall back to the uncached path.

Both caches are bounded, because item names come from game memory and a
corrupted read would otherwise grow them without limit.

Covered by `src/tests/test_item_lookup_memoisation.py`, tamper-checked:
dropping the defensive copy fails five cases, two of which build a stage
summary end to end.

Known remaining limit: the stage summary is still `O(length of run)` per frame,
so a recording twice as long costs twice as much. Removing that needs either
debouncing the heavy sections during a drag or prefix checkpoints inside
`build_stage_summary`; both were scoped, priced and deliberately deferred.

#### 2. Tracked Items Refresh Latency Optimization (Refactor Fixes)

Status: `[Implemented / Requires In-Game Verification]`

Shipped:

- `PASSIVE_ITEMS_REFRESH_MS = 1_000` and the `passive_items` `RefreshTask`
  (`app/refresh_tasks.py`), resolved through the existing named `PASSIVE_ITEMS`
  source key so a pass where the full snapshot is also due walks the item
  dictionary once. Gated on `_should_refresh_full_player_snapshot`, the same
  predicate the full snapshot uses.
- `LiveRunTracker.update_items` (`core/tracker/live_run.py`), which runs
  `items.process_item_deltas` only. It does not append to the snapshot deque,
  advance the stage index, reset the stage-summary cache or mark features live.
- Transient-empty and run-boundary guards inside `update_items`; memory health
  and the reconnect streak are deliberately left to the full snapshot.
- Halved read cost for the walk itself: `_read_passive_item_dictionary`
  memoises the slot layout (value address + name per slot) and re-reads only the
  stabilised stack counts, validated against the dictionary pointer, entries
  pointer, count and `_version` -- the same quadruple `_get_cached_key_count`
  has used in production. ~4 reads per entry becomes ~2.
- Coverage: `src/tests/test_passive_items_fast_lane.py`,
  `src/tests/test_passive_item_layout_cache.py`. Each guard was tamper-tested.

Still owed: a live run confirming end-to-end latency and that no duplicate or
dropped pickup appears in the OBS overlay, Session Stats or the Twitch output.

Correction to the analysis below: the claim that `current_stage_index` advances
only inside `update()` is **wrong**. `update_fast_stage_timer` also advances it
(`core/tracker/live_run.py`), after a 2-sample confirmation and a stage-timer
reset hold, so fast-lane item events are stamped with a stage index that is
accurate to ~1--2 s. The accepted-inaccuracy caveat that rested on that claim
does not apply. One real gate remains: that fast advance happens inside the
`event_timer` task, whose demand predicate is `_should_refresh_fast_stage_timer`
-- with every stage-timer consumer disabled, the stage index falls back to the
10 s path.

Goal:

- Reduce high latency/delays when updating `Tracked items` in the OBS overlay, Session Stats UI, and Twitch command output after acquiring or leveling up passive items.

Problem Analysis:

- **The real latency is 10--20 s, not 10 s.** Two stages compound:
  - `tracked_items` state relies on `full_player_snapshot`, polled on a 10,000 ms (`PLAYER_STATS_REFRESH_MS`) interval;
  - an item gain is then *confirmed*, not trusted on first sight. `process_item_deltas` holds the raised count as a `_PendingItemIncrease` and credits it only on the next snapshot that agrees (`core/tracker/items.py`). That confirmation is correct -- the game rebuilds its item dictionary in place and a mid-write read can show a transient count -- but at a 10 s cadence it costs a second full interval.
- **One choke point, and it is not the UI.** All consumers read the same `LiveRunTracker` tracked counts through `tracked_item_rows` / `tracked_item_rows_for_rules`: Session Stats (`session_stats.py`), the OBS overlay (`runtime_snapshot().tracked_items`), and the Twitch commands. That field is written only by `process_item_deltas` inside `LiveRunTracker.update(snapshot)`, whose only caller is `refresh_now` on the 10 s task.
- **Transport is already fast; only the value is stale.** OBS overlay state is republished every 500 ms from `_refresh_combat_metrics_task` (when the `kps` or `stage_summary` widget is enabled). No UI plumbing needs to change.
- **Scope correction:** the In-Game Overlay has no tracked-items widget at all. Its widget set is `scanner`, `recording`, `kps`, `powerups`, `luck_rarity`, `stats`, `event_timer`. The affected surfaces are the OBS overlay, Session Stats, and Twitch.

Planned Solution -- read passive items on the fast lane:

- Register a new `RefreshTask` for passive items with its own cadence constant (1,000 ms proposed), not by reusing `FAST_TRACKER_INTERVAL_MS`. This follows the precedent of `RECORDING_LIFECYCLE_REFRESH_MS`, which is its own decision rather than an inherited interval.
- Resolve it through the existing named source key `PASSIVE_ITEMS` (`app/read_sources.py`). This is the point of step 28's composable reads: on every pass where the full snapshot is also due, both consumers share **one** physical read of the item dictionary. No read is duplicated.
- Call the existing `PlayerStatsMemory.read_passive_items_only(owner_stats, context)`; it is already a standalone entry point with `context` threaded through.
- Add a narrow `LiveRunTracker.update_items(...)` that calls `items.process_item_deltas` only. It must **not** call `update()`, which appends to the snapshot deque, advances `current_stage_index`, resets the stage-summary cache, and marks five features live. `update_items` joins the existing family of fast-lane entry points (`update_fast_run_timer`, `track_kills`, `update_powerups`, `track_expected_key_procs`, `update_chaos_tome`, ...).
- Keep the confirmation ladder. At a 1 s cadence it costs one second, and a shorter window between the two reads makes it stricter, not weaker.
- Nothing is removed from `refresh_now`: the full snapshot keeps reading and publishing items exactly as today, so recordings, VOD capture and Stage Summary inputs are unchanged. This adds a second consumer of an existing source; it does not split the existing path.

Required guards:

- Apply the same transient-empty-dictionary protection that `LiveSnapshotStore.merge_items` provides. Without it, one empty read drops `current_count` below the confirmed count and silently discards a pending gain.
- Gate the task on the lifecycle probe's active-run state and on the same demand predicate as the full snapshot (`player_stats_refresh_required`), so no gap appears in data that recordings consume.
- Do not credit items across a run boundary: new-match detection and `reset_for_new_match` currently live on the 10 s path, and the fast task must not attribute a new run's starting inventory to the previous run.
- Stage attribution granularity stays as-is for this change: `current_stage_index` advances only inside `update()`, so an item gained within ~10 s of a stage transition can be stamped with the outgoing stage index. This is accepted here and addressed by the stage-closing snapshot in the next item.

Expected result:

- Detection within 1 s plus one confirmation tick: roughly **1--2 s** end to end, against 10--20 s today.
- Added read cost is approximately 4 reads per inventory entry per tick (~120 reads/s at 30 items), because `_read_passive_item_dictionary` resolves names from `ITEM_ENUM_NAMES_BY_ID` by dictionary key and performs no string reads on the hot path. That is the same order as the fast-lane work already running (powerups, expected chests, Chaos Tome) and smaller than one cold damage-source dictionary walk.

Rejected alternatives:

- **Lowering `PLAYER_STATS_REFRESH_MS`.** The full snapshot reads player stats, weapons, tomes, banishes, damage sources (the cold RunStats dictionary walk), the disabled-item pool and map activity, then repaints Live Stats synchronously on the UI thread. Multiplying all of it to refresh one fact of fifteen is the wrong trade, and `disabled_items` is deliberately a once-per-run read rather than a cadence-driven one. Acceptable only as a temporary stopgap (e.g. 3,000 ms for 3--6 s latency) if a fix is needed before the task exists.
- **Building an inventory-signature/delta detector**, as an earlier draft of this entry proposed. Counted against the source, it does not pay for itself: a signature costs roughly 3 reads per entry (value pointer + count + stable stack count) versus roughly 4 for reading the items outright. A quarter saved buys a new address-cache layer with its own invalidation and its own failure mode. Read the items directly instead.

Validation Requirements:

- Verify that on a pass where both the fast task and the full snapshot are due, the item dictionary is read exactly once (assert on the shared `PASSIVE_ITEMS` key, not on wall-clock timing).
- Cover: pickup detection latency at the new cadence, a level-up (stack count change on an existing entry), a transiently empty dictionary, an `InvalidItemStackCountError`, and a run boundary.
- Tamper-test the new task: disabling it must fail a test. A harness that stubs the 10 s path will otherwise keep passing and prove nothing.

#### 3. Stage Summary Stage-Closing Snapshot (Refactor Fixes)

Status: `[Implemented / Requires In-Game Verification]`

The mechanism this entry proposed already existed, half-built. `update_fast_stage_timer`
detects a stage change on the fast lane with a 2-sample confirmation and a hold
until the stage-timer reset is observed, commits a boundary snapshot to
`_fast_stage_boundaries`, and `_stage_summary_timeline_unlocked` already merges
those boundaries into the list `build_stage_summary` folds over. Time and kills
were therefore already closed to ~1--2 s. Items were excluded by one line:
`_fast_stage_summary_snapshot_unlocked` set `items_available=False`, because
nothing on the fast lane could supply an inventory.

Shipped, as two changes rather than a new subsystem:

- The fast projection now carries the fast-lane inventory when it is fresher
  than `FAST_ITEMS_TTL_SECONDS` (3 s). Expiry withholds the inventory, which
  degrades to the previous behaviour rather than to a wrong one.
- `build_stage_summary` credits a closing snapshot's item gains to
  `previous_stage_index` (`core/run_summary.py`). This is the "Cheap Interim
  Fix" below, and it stops being a heuristic now that the boundary is a
  recorded fact: it reuses the exact predicate the bucket append and the kill
  baseline on the adjacent lines already use.

No new snapshot field and no explicit `stage_boundary="closing"` marker was
added, because the live fold does not need one.

Known gap, and the reason a marker may still be wanted: **recordings do not see
the boundary.** VOD snapshots are captured only on the 10 s path
(`capture(**capture_kwargs)` in `app/player_stats_refresh.py`), and
Recordings/Compare Runs rebuild their own Stage Summary from that list. So the
live Stage Summary is now accurate while the same run replayed from a recording
keeps the old misattribution. Closing that requires persisting the closing
observation into the recording, and the fold must tolerate its absence in
already-recorded runs.

The heuristics this entry proposed retiring -- `is_stage_transition_boundary_snapshot`
and `is_explicit_raw_stage_transition` -- were **kept**. They are what identifies
a closing snapshot in the fold, including for recorded runs that carry no fast
boundary at all.

Goal:

- Attribute items, kills and time to the stage they were actually earned on by recording an explicit *closing* observation at the moment a stage transition is detected, instead of inferring the boundary afterwards from timer heuristics.

Problem Analysis:

- **Item gains on a transition snapshot are credited to the wrong stage.** In `build_stage_summary` (`core/run_summary.py`) the per-snapshot loop advances `current_stage_index` *first*, then credits that snapshot's item gains to the already-advanced index. Everything picked up during the tail of the outgoing stage -- which becomes visible only on the first read taken after the transition -- lands on the incoming stage.
- **Time and kills already get boundary handling; items do not.** The same loop appends the transition snapshot to the *previous* stage's bucket when `is_stage_transition_boundary_snapshot` or `is_explicit_raw_stage_transition` holds, and records a per-stage kill baseline. The item path has no equivalent, which is the asymmetry to close.
- **Gains are credited on first sight.** `update_stage_item_gain_tracker`'s confirmation streak (`PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS`) applies only to a *falling* count. A rising count is credited immediately, so the very first post-transition snapshot moves the whole tail of the previous stage.
- **The detection signal is already 10x finer than the attribution.** `RuntimeGameState.current_stage_index` is published by the lifecycle probe every `CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS` (1 s) and already reaches `refresh_now`. Stage Summary nevertheless derives stage identity from the `stage_index` field of a 10 s snapshot. The data exists; the mechanism to freeze on it does not.
- **Double counting is not confirmed.** Only misattribution is provable from the code -- item gains are credited once. If a run shows a pickup counted on both stages, capture a trace before designing for it; the likelier source is the separate tracked-item rule path with its own `combo_run_counts`.

Proposed Mechanism:

- On a stage-index change observed by the 1 s lifecycle probe, emit a **closing observation** stamped as belonging to the *outgoing* stage, and begin the new stage from a fresh baseline.
- Carry the boundary as explicit data on the snapshot (for example `stage_boundary="closing"`) rather than leaving it to be re-derived. `build_stage_summary` is a pure fold over the snapshot list and holds no incremental state, so a closing observation is a snapshot inserted into that list with a marker -- not a new state layer and not a new component.
- Once the boundary is recorded fact, retire the heuristics that exist only because it was not: `is_stage_transition_boundary_snapshot` with its `PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS` window, and `is_explicit_raw_stage_transition`.

Sequencing -- this depends on item 1:

- The error is produced by the window during which a pickup is invisible, and that window is today the 10 s snapshot cadence. Moving passive items to the fast lane (item 1 above) shrinks it roughly tenfold on its own.
- After that, the closing observation only has to cover the last ~1 s before the transition -- a window in which, by in-game behaviour, nothing can be picked up (stage-entry animations). It can then be a **boundary marker rather than an urgent extra read**, which is materially simpler and safer.
- Recommended order: item 1 first, then this.

Cheap Interim Fix (independent of the mechanism):

- Credit item gains to `previous_stage_index` when the transition snapshot already satisfies `is_stage_transition_boundary_snapshot` -- the same predicate the bucket append on the adjacent lines uses. Two lines, no new concepts, and it rests on the same in-game fact this entry is built on. It closes the bulk of the cases immediately and does not remove the need for the explicit boundary.

Known Limitations and Adjacent Debt:

- **Graveyard is not covered.** Its internal transitions do not change the raw `stage_index`; see item 4 below. Record this as a known gap in scope rather than discovering it on a live run.
- **Two independent item-delta engines.** `process_item_deltas` (`core/tracker/items.py`, confirmation ladder on *increases*, feeds tracked-item rules) and `update_stage_item_gain_tracker` (`core/run_summary.py`, ladder on *decreases*, feeds Stage Summary rarities) consume the same input with different algorithms and different guarantees. This entry fixes the symptom in one of them. Whether to converge them is a separate decision, but until it is made, every fix of this shape has to be applied twice.

Validation Requirements:

- Capture a live trace of a Forest/Desert stage transition recording: the moment `stage_index` changes, the run timer, the stage timer, and the earliest moment an item can actually be acquired on the new stage. **The safe-window assumption ("nothing drops in the first 1--2 s of a stage") is what the whole mechanism rests on and must be measured, not assumed.**
- Cover an item acquired in the final second before a transition, an item acquired immediately after one, and a delayed or dropped read spanning the boundary.
- Verify Stage 1 -> 2, 2 -> 3, 3 -> Boss Room and the late-attach path, and confirm Graveyard behaviour is unchanged rather than silently wrong.

---

## Recently Handled Items (Archived 2026-07-22)

### Live Run Refactor Fixes

#### 1. Active Template Colors In Log Output (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Formatted active template names and score tiers in `[*] Active templates updated live: ...` and `[*] Active tiers updated live: ...` log lines with rich-text/HTML colors corresponding to their template badge and score tier colors.
- Retained colored log formatting across live checkbox updates and mode switches.

Key commits:

- `d3217e2` — Color live template update announcements.
- `c799eb3` — Color live score tier announcements.

#### 2. Default Height For Score Settings Dialog (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Increased the default height/dimensions of the `Score Settings` dialog so the bottom `Save` / `Cancel` button panel is immediately visible without scrolling.

Key commits:

- `cc11cc0` — fix: increase score settings dialog height.

#### 3. Enforce Scanner Start Guarding When Active Rules Are Empty (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Updated score tier checkbox state sync so unchecking all score tiers explicitly saves `active_tiers = []` in configuration.
- Prevented the scanner from starting when all tiers in `Scores Mode` or all templates in `Templates Mode` are unchecked, outputting an explicit error log line (`[-] Error: ...`).

Key commits:

- `59d9480` — Fix empty score tier selection.

#### 4. Restore Magnets Requirement Support in Templates Mode (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Restored target `Magnets` count conditions in template evaluation rules (`Templates Mode`).
- Reused memory read and evaluation paths active for `Magnets` in `Scores Mode`.
- Updated template editor dialog, config schema, evaluation condition matcher, and condensed UI/Twitch preset formatters to support magnet conditions.

#### 5. Synchronize OBS Overlay Edit Mode On Active Widget Toggles (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Automatically update active widget states in the OBS Overlay web editor when toggling checkboxes in BonkScanner UI without requiring users to manually re-enter edit mode.

### Stage Summary

#### 10. Rework Stage Summary Around Fast Runtime Samples

Status: `[Implemented]`

Implemented scope:

- Stage summary boundaries and kill totals are calculated from fast runtime values already read frequently by the application instead of relying solely on the full player snapshot collected every 10s.
- Prevented kills earned near a map transition from being assigned to the next stage due to late snapshot arrival.
- Standardized stage boundary calculation across UI, Twitch announcements, OBS/In-game overlays, and saved recordings.

---

## Recently Handled Items (Archived 2026-07-15)

### Recordings

#### 7. Fix Clean Short Active Run Edge Case

Status: `[Implemented]`

Implemented scope:

- `Clean Short` explicitly excludes the currently active recorder file.
- `PermissionError` and other `OSError` failures on individual files are skipped so the remaining short recordings are still processed.
- The UI reports the number of removed and skipped active/locked recordings.
- Regression coverage verifies that an active file and a locked file remain while other short files are deleted.

Code anchors:

- `src/vod_storage.py`
- `src/gui_player_stats.py`
- `src/tests/test_vod_storage.py`

### Live Runtime

#### 8. Harden The Live Powerup Read Pipeline

Status: `[Partial / Archived]`

Implemented scope:

- Added structured read health for timing, status effects, and `Powerup Multiplier`.
- Incomplete or unavailable powerup reads are rejected before replacing the shared tracker snapshot.
- The existing last-known-good TTL fallback remains active for transient failures.
- Added coverage for hard failures, partial effect lists, empty reads, multiplier failures, recovery, and shared consumer state.

Remaining caveat:

- The snapshot still expires after the compatibility TTL instead of being retained indefinitely until a valid replacement or explicit run reset.
- Runtime diagnostics and full run-reset semantics remain follow-up work.

Key commits:

- `f8b2fcb` — preserve powerup snapshots through transient read errors.
- `db2132d` — harden powerup memory reads and add health validation.
- `5da3844` — prevent auxiliary reads from hiding powerups.

### Recovery Tooling

#### 9. Automated IL2CPP Offset Validator and Handoff Reporter

Status: `[Implemented locally / Pending commit]`

Implemented scope:

- Added local `tools/offset_finder.py` utility.
- Parses IL2CPP `dump.cs` metadata and optional `il2cpp.h` / `script.json` TypeInfo sources.
- Compares configured expectations and reports `matched`, `shifted`, `missing`, `ambiguous`, and `unverified` entries.
- Generates a Markdown validation and handoff draft with manual follow-up sections.
- Remains diagnostic-only and does not patch production source files.

Archive note:

- The `tools/` directory is currently ignored by Git, so this utility is present in the workspace but is not yet included in a commit.

---

## Completed / Done Items (Archived 2026-07-12)

### Twitch Commands

#### 6. `!kps` (Kills Per Second) Tracker

Status: `[Implemented]`

Implemented scope:

- `PlayerStatsClient` caches and validates the `RunStats.stats["kills"]` dictionary entry for lightweight reads.
- `LiveRunTracker` calculates current KPS from a smoothed ~3-second window based on the in-game timer; resets, backwards time, and paused time do not create false progress.
- The Live Stats kills label, VOD snapshots, OBS state, and the configurable `!kps` command consume the shared tracker state.
- `!kps` reports a warming-up/unavailable response instead of a misleading zero before valid samples exist, and is included in `!bonkhelp`.

Archive note:

- Removed from the active list after implementation and automated coverage were completed.

### Runtime Refresh Architecture

#### 8. Split Live Refresh Into Slow And Fast Tracker Lanes

Status: `[Implemented]`

Implemented scope:

- The expensive `full_player_snapshot` runs on the slow player-stats cadence.
- Independent 500ms fast tasks now handle combat metrics/KPS, powerups, expected chest inputs, event timer state, and Chaos Tome tracking.
- Shared `RefreshTickContext` values avoid duplicate client and owner-stat resolution within a scheduler tick.
- `LiveRunTracker` remains the shared fast runtime state consumed by UI, overlays, Twitch, and VOD capture.

Archive note:

- The concrete lane design replaced the original planning/prototype entry.

### In-Game Overlay

#### 1. In-Game Stats Widget

Status: `[Implemented]`

Implemented scope:

- Configurable in-game `stats` widget with cap-aware formatting and colors.
- Forest/Desert use dynamic Difficulty caps by stage and elapsed time plus the fixed `XP Gain` 10x cap; capped values are red and uncapped values cyan.
- Graveyard uses the standard uncapped stat presentation.

#### 2. In-Game Event Timer Widget

Status: `[Implemented]`

Implemented scope:

- Configurable single-line warning and active-wave timer driven by the fast stage-timer lane.
- Covers Forest/Desert boss and wave timings with orange advance warnings and red active-wave state.
- Includes the later Graveyard event-timing extension, while retaining empty output when no relevant event is imminent.

Archive note:

- Both overlay widgets reuse the existing resolved map-family and runtime stage-time paths.

---

## Completed / Done Items (Archived 2026-07-03)

### In-Game Overlay

#### 1. Split `src/gui_in_game_overlay.py` Into Focused Modules

Status: `[Done]`

Goal:

- Reduce the maintenance cost of the in-game overlay code by separating UI window logic, settings UI, and HTML/render helpers into smaller focused modules.
- Keep the shipped overlay behavior unchanged while making future fixes and feature work less risky.

Implemented scope:

- `src/gui_in_game_overlay.py` now acts as the thin coordinator/mixin entry point.
- Overlay widgets were moved into `src/gui_in_game_overlay_window.py`:
  - `InGameOverlayWindow`
  - `DraggableOverlayWidget`
- The settings dialog was moved into `src/gui_in_game_overlay_settings.py`:
  - `InGameWidgetSettingsDialog`
- HTML/string formatting helpers were moved into `src/gui_in_game_overlay_render.py`.
- Existing config keys, signal wiring, and overlay refresh cadence were preserved.

Archive note:

- Removed from the active `functional_updates.md` list after the split was completed.

---

## Archived & Shelved Items (Archived 2026-06-23)

### Stage Summary Must Anchor To Raw Stage Index And Treat Boss As Virtual Stage

Status: `[Archived]`

Goal:

- Make `Stage Summary` deterministic when the app opens in the middle of a run.
- Use the raw memory `stage_index` as the only source of truth for normal map rows.
- Treat boss stage as a separate virtual `Stage 4`, not as a normal raw `stage_index` value.
- Stop `Stage Summary` from starting at row 1 just because the tracker attached late.

Required baseline mapping:

- Raw memory `stage_index` values must map directly to summary rows:
  - `0 -> Stage 1`
  - `1 -> Stage 2`
  - `2 -> Stage 3`
- This mapping is a hard rule, not an inference layer.
- Do not pre-convert the raw value into a human stage number before it reaches live snapshots or summary logic.

Required attach behavior:

- If the app opens during Stage 1, `Stage Summary` starts filling row 1.
- If the app opens during Stage 2, `Stage Summary` starts filling row 2 and leaves Stage 1 empty.
- If the app opens during Stage 3, `Stage Summary` starts filling row 3 and leaves Stages 1-2 empty.
- Late attach must not restart the table from Stage 1.

Boss-stage rules:

- `Stage 4` is not represented by a normal raw `stage_index`.
- Raw `stage_index=2` still means `Stage 3` by default.
- Boss stage must be promoted to virtual `Stage 4` only after an observed transition marker, not from the base raw index alone.
- Do not let a single isolated first snapshot in ghost phase automatically start the table on `Stage 4`.

Allowed boss transition markers:

- Existing timer-based transition markers may still be used.
- Add a dedicated collapse marker based only on raw map activities for:
  - `chests`
  - `pots`
- Valid collapse examples:
  - `chests: 22/46 -> 23/23`
  - `pots: 5/55 -> 5/5`
- These are good boss markers because the reported max collapses downward to the current observed value.

What must not count as boss detection:

- Honest full-clear values on the normal map must not trigger `Stage 4`, for example:
  - `chests: 46/46`
  - `pots: 55/55`
- The critical signal is not `current == max` by itself.
- The critical signal is that `max` shrank relative to the previously observed normal-map baseline.

Implementation constraints:

- Keep the logic split into two layers:
  - normal stage row selection from raw `stage_index`
  - virtual `Stage 4` promotion from explicit boss markers
- Do not merge these into one heuristic that can reinterpret raw `stage_index` based on ghost phase alone.
- Preserve raw `stage_index` all the way through:
  - memory read
  - live snapshot payload
  - live tracker state
  - stage summary builder
- Any human-readable stage number should be derived only at the final mapping point.

Regression coverage required:

- Opening the app on raw `stage_index=1` must fill Stage 2 and leave Stage 3 empty.
- Opening the app on raw `stage_index=2` must fill Stage 3 and leave Stage 4 empty unless a boss marker is observed later.
- Opening the app directly in ghost phase on a normal Stage 2 or Stage 3 map must not automatically start on `Stage 4`.
- A later observed collapse in `chests` or `pots` may promote the run from Stage 3 to Stage 4.
- Persist the “minimum total” marker into recorded/VOD snapshots if recorded summaries must match live summaries.

Archive note:

- Shelved out of the active `functional_updates.md` list.

---

## Completed / Done Items (Archived 2026-06-21)

### Mid-Run `!chests` Recovery And Honest Totals

Status: `[Done]`

Goal:

- Keep `!chests` and the live Chests card useful when the app starts in the middle of a run.
- Avoid inventing exact per-map chest counts for stages that were never observed by the tracker.
- Recover `Paid` and `Key Procs` whenever the cumulative run counters are still mathematically usable.
- Distinguish exact totals from lower-bound totals in the Twitch/GUI output.

Target behavior:

- If the tracker observed the run from the first map:
  - Keep the existing exact behavior.
  - Show exact per-map counts such as `T1:45/46 T2:46/46`.
  - Show exact overall totals such as `Total: 91/92`.
- If the tracker starts mid-run:
  - Show previously missed maps as unknown, for example `T1:--/46 T2:--/46 T3:20/46`.
  - Show the current observed map count exactly.
  - Show overall opened chests as a minimum using a `+` suffix, for example `Total: 51+/138`.
  - Continue showing `Paid` and `Key Procs` if `chestsPurchased` and `chestsBought` are internally consistent with the minimum possible total.
  - Show `Free Chests: --` because inherently free openings from missed maps cannot be reconstructed honestly.
  - Keep `Expected: --` if fast expected-proc tracking did not start from `chestsBought == 0`.

Memory inputs and scope rules:

- Current-map chest progress comes from `MapStat.CHESTS.current/max`.
- Cumulative run counters come from:
  - `RunStats.stats["chestsBought"]`
  - `MoneyUtility.chestsPurchased`
- The game does not expose a reliable always-present cumulative `chestsOpened` run stat in the tested build.
- Because of that, the tracker must treat exact prior-map openings as unknown when the app attaches mid-run.

Implementation rules:

- Detect a mid-run chest attach when the first observed playable snapshot lands on a later map/stage instead of the first playable map.
- Preserve `--` for any map that was not directly observed by the tracker.
- Compute `Total+` as the minimum total consistent with:
  - directly observed current-map openings, and
  - the invariant `chestsPurchased <= chestsBought <= totalOpened`.
- Do not backfill synthetic exact openings into `T1`, `T2`, or other missed maps just to make the invariant pass.

Baseline rules for unknown map totals:

- Use `46` as the default baseline for normal map families.
- If the currently observed map reports `chests_total >= 69`, treat the active map family as the high-total case and use `69` as the unknown-map baseline instead of `46`.
- If the currently observed map reports `chests_total < 46`, clamp unknown-map baseline totals back to `46` instead of propagating boss-room or collapsed values such as `15`.
- This rule exists because normal map families can temporarily report a collapsed chest max in boss-room-like states, while the tested high-total map family keeps reporting `69`.

Current gaps to finish (completed):

- Reconciled raw memory `stage_index` values.
- Re-applied the `Total+` path.
- Restored tests.

---

### Active Powerup Tracking For `!powerups` And Live Stats

Status: `[Done]`

Goal:

- Replace the old duration-only `!powerups` behavior with live active powerup tracking.
- Show active Rage, Shield, Stonks, and Clock/TimeFreeze effects with UI-stage pickup and expiration timestamps.
- Keep the old duration summary as the fallback when no supported powerup is active.
- Reuse the existing fast live tracker loop instead of adding a standalone polling subsystem.

Implemented behavior:

- `PlayerStatsClient` reads the supported effects from `PlayerStatusEffects.statusEffects`.
- `LiveRunTracker` stores a normalized active powerup snapshot and formats both Twitch and Live Stats summaries.
- `!powerups` output when active effects exist:
  - `Powerups: Rage 01:33 -> 00:11 (80s left) | Stonks 01:32 -> 00:10 (81s left) | Clock 01:32 -> 00:27 (64s left) (PM 5.43x)`
- `!powerups` output when no supported effect is active:
  - `Powerups: none active | Durations: standard 81.43s, clock 65.15s (PM 5.43x)`
- Live Stats uses the same tracker state in the existing `Powerups:` row, without adding a separate tab.

Polling and activation rules:

- Powerup tracking runs in the existing fast tracker timer (`FAST_TRACKER_INTERVAL_MS`, currently `500 ms`).
- `Powerup Multiplier` uses a short cached value with forced refresh when the
  active powerup set changes, instead of re-reading the full player stats block
  every fast tick.
- Powerup memory reads are only attempted when a consumer exists:
  - Live Stats tab is active, or
  - Twitch bot is active and the `powerups` command is enabled.
- The Twitch command does not read memory directly; it reads the latest `LiveRunTracker` powerup snapshot.

Confirmed memory and formula details:

- Supported status effect IDs:
  - `1` Rage
  - `2` Shield
  - `3` Stonks
  - `4` TimeFreeze / Clock
- Effect activity is based on `StatusEffect.expirationTime - MyTime.time > 0`.
- Current pickup time is reconstructed as `expirationTime - expectedDuration`, because refreshed effects may keep an old `addedTime`.
- Expected durations:
  - Rage, Shield, and Stonks: `15 * Powerup Multiplier`
  - Clock/TimeFreeze: `12 * Powerup Multiplier`
- UI stage timestamps use `MyTime.stageTimer` and `StageTimeline.stageTime`:
  - countdown: `stageTime - stageTimer`
  - overtime: `+(stageTimer - stageTime)`

Validation:

- Live memory validation confirmed Stage 1, Stage 2, Stage 3, countdown, and overtime formatting.
- Unit coverage was added for:
  - status effect dictionary reads,
  - active/fallback powerup summary formatting,
  - overtime formatting,
  - Twitch command routing through the tracker snapshot.

Known caveat:

- If stage time is manually changed through external cheats, the game UI can temporarily diverge from the normal `MyTime.stageTimer` formula. Normal gameplay matched the documented formula during live validation.

Documentation anchors:

- `docs/recovery/reports/2026-06-20-player-status-effects-and-buffs.md`
- `docs/recovery/reports/2026-06-20-ui-stage-timer-calculation.md`

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

- `src/twitch_bot.py`
- `src/live_run_tracker.py`
- `src/player_stats.py`
- `src/gui_dialogs.py`
- `src/gui_twitch.py`
- `src/tests/test_twitch_bot.py`
- `src/tests/test_live_run_tracker.py`
- `src/tests/test_player_stats.py`

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

- `src/hotkey_manager.py`
- `src/gui_run_control.py`
- `src/gui_dialogs.py`
- `src/config.py`
- `src/tests/test_hotkey_manager.py`
- `src/tests/test_gui_run_control.py`

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

- Implemented in `src/game_data.py` and `src/gui_player_stats.py`.
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
