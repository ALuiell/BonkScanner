# Functional Updates

Date: 2026-08-20

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## Open Updates

### Twitch Commands

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

### Character Passive Bonus Tracking (Dice First Adapter)

Status: `[Implemented / 1,826-Test Regression Passed; Fox and Dice Live Acceptance Passed]`

Goal:

- Add one universal `Passives` detail tab under Live Stats, next to `Chaos` and
  `Shrines`, for bonuses and current effects produced by the selected
  character's level-scaling passive. Do not add a dedicated tab per character.
- Resolve the current character, passive type, and runtime passive object from
  game data, then delegate the calculation to a passive-specific adapter.
- Show the current character and passive once in the tab header, followed by a
  compact list of effect cards. A roll count is valid for Dice, but must
  not be invented for linear or conditional passives which do not roll.
- Track every permanent stat roll produced by Dice's `Gamba` passive as
  the first source-aware adapter and present its accumulated bonuses in the
  same compact per-stat format as Chaos Tome and Charge Shrines.
- Keep the implementation external and read-only. No hook, injected DLL, or
  game-memory write is needed.

Confirmed universal runtime discovery (live game, 2026-08-23):

- The universal identity path exists and does not require guessing from final
  stats. `CharacterData` contains `eCharacter` at `+0x50` and `PassiveData` at
  `+0x88`; `PassiveData` contains `ePassive` at `+0x28`. The active
  `PlayerInventory` exposes the selected `CharacterData` at `+0x18` and the
  instantiated `PassiveAbility` at `+0x58`.
- Every runtime passive inherits `PassiveAbility`, whose shared
  `statModifiers` dictionary is at `+0x10`. This is useful when a passive
  publishes a stat modifier, but it is not a universal calculation by itself:
  several passives also depend on live counters, movement, enemies, gold,
  shields, or other event state.
- A read-only walk of the running `DataManager.unsortedCharacterData` list
  returned exactly 21 character records. Every record contained a valid
  `ECharacter`, `EPassive`, and initialized dummy runtime class. The current
  build's authoritative catalog is:

| Character | Passive enum | Runtime class | Initial tracking strategy |
| --- | --- | --- | --- |
| Amog | `Plague` | `PassiveAbilityPlague` | Event stacks + level scaling |
| Athena | `LockIn` | `PassiveAbilityLockIn` | Level bonus + live shield state |
| Bandit | `Flowstate` | `PassiveAbilityFlowstate` | Static linear formula verified; live pending |
| Birdo | `Float` | `PassiveAbilityFloating` | Live conditional bonus |
| Bush | `Bullseye` | `PassiveAbilityBullseye` | Level bonus + mark events |
| Calcium | `SpeedDemon` | `PassiveAbilitySpeedDemon` | Level bonus + movement/hit state |
| SirChadwell | `Curse` | `PassiveAbilityCurse` | Static linear formula verified; live pending |
| Cl4nk | `CritHappens` | `PassiveAbilityCritHappens` | Static linear formula verified; live pending |
| Dice | `Gamba` | `PassiveAbilityGamba` | Permanent roll ledger |
| Fox | `RngBlessing` | `PassiveAbilityRngBlessing` | Verified linear level bonus |
| SirOofie | `Reinforced` | `PassiveAbilityReinforced` | Static linear formula verified; live pending |
| Megachad | `Flex` | `PassiveAbilityFlex` | Level bonus + live stacks/cooldown |
| Monke | `WallClimb` | `PassiveAbilityWallClimb` | Verified linear level bonus |
| Ninja | `Shadowstep` | `PassiveAbilityShadowstep` | Level bonus + evade event state |
| Noelle | `Enduring` | `PassiveAbilityEnduring` | Level bonus + frozen-enemy state |
| Ogre | `Warrior` | `PassiveAbilityWarrior` | Static linear formula verified; live pending |
| Roberto | `Hoarder` | `PassiveAbilityHoarder` | Live timer/progress counters |
| Robinette | `Stonks` | `PassiveAbilityStonks` | Level bonus + current-gold scaling |
| Spaceman | `Quantum` | `PassiveAbilityQuantumXp` | Static linear formula verified; live pending |
| TonyMcZoom | `Zap` | `PassiveAbilityZooma` | Level bonus + movement charge |
| Vlad | `Vampire` | `PassiveAbilityVampire` | Static linear formula verified; live pending |

- The catalog walk is a research/validation route. Production identity should
  follow the active player's `CharacterData` and runtime object, validate the
  enum pair and IL2CPP class, and fail closed on an unknown combination.
- `passive level multiplier * character level` is allowed only for a verified
  linear adapter. It is not a universal fallback. `Gamba` rolls a decaying
  random stat; `Enduring`, `Float`, `SpeedDemon`, `Stonks`, `LockIn`, `Flex`,
  `Plague`, `Hoarder`, and `Zooma` depend on additional runtime state. Showing a
  fabricated linear total for any of them would be worse than an explicit
  `unsupported`/identity-only snapshot.
- The implementation must use the name `character_passive` at code and storage
  boundaries so it cannot be confused with the existing passive-items feature.

Universal adapter and snapshot contract:

1. Add a generic identity reader which returns validated character ID/name,
   passive ID/name, runtime class, passive object pointer, and character level.
   The reader owns build-sensitive offsets; UI and core snapshots must not.
2. Add an immutable `CharacterPassiveSnapshot` containing identity, level,
   adapter/coverage status, and a tuple of `CharacterPassiveEffectSnapshot`
   entries. Each effect needs a stable key, label, raw value, display format,
   semantic kind, and optional count/cap/progress metadata.
3. Use explicit effect kinds such as `permanent_level`, `current_conditional`,
   `progress`, and `counter`. This lets the tab distinguish, for example,
   `Luck +12%` from `Current damage +35%` or `Stacks 4/10` without pretending
   those values have the same lifecycle.
4. Register one adapter per validated passive class. Adapters may use one of
   four strategies: verified linear formula, source-aware permanent ledger,
   dynamic runtime fields, or event/progress counters. Hybrid passives may
   publish several effect entries from more than one strategy.
5. Never derive a passive contribution by subtracting from the player's final
   combined stat. Items, tomes, shrines, Chaos Tome, and other systems share
   those totals, so source attribution would be unverifiable.
6. Unknown classes, invalid pointers, unavailable runtime dependencies, and
   not-yet-implemented adapters publish identity plus an explicit
   `unsupported`/`unavailable` state and no guessed bonus.

Approved MVP scope:

- Always resolve and publish the current character identity for all 21 known
  characters, even when the passive calculation is unsupported.
- Implement bonus calculation only for Dice / `Gamba` and the linear
  candidate group after each formula is verified: `RngBlessing`, `Reinforced`,
  `Flowstate`, `CritHappens`, `Curse`, `WallClimb`, `Warrior`, `Quantum`, and
  `Vampire`.
- Leave hybrid, conditional, movement, combat-event, and progress passives out
  of the first implementation. Their tab still shows character/passive identity
  followed by a clear `Tracking not supported for this passive` fallback.
- The fallback is a supported product state, not a read error. Reserve
  `unavailable` for a failed/invalid memory read and `unknown` for an enum/class
  combination the current build does not recognize.
- Adding another passive later requires only a new verified adapter; it must not
  change the snapshot or Live Stats tab contract.
- The canonical user-facing name for `ECharacter.Dicehead` is `Dice`. Use
  `Dice` in Live Stats, Recordings, Compare Runs, Twitch, OBS, and overlays;
  keep `Dicehead`, `Gamba`, and `PassiveAbilityGamba` only as internal game/code
  identifiers. Do not display `Dice Head` or `Dicehead` to the user.

Verified Fox / `RngBlessing` linear adapter (dump + live game, 2026-08-23):

- `PassiveAbilityRngBlessing` contains only `luckPerLevel` at `+0x18`.
  Its constructor writes the exact `float32` value
  `0.014999999664723873` (`0.015f`). `Tick` is a no-op.
- `OnLevelup(int level)` creates one `StatModifier` with
  `stat = EStat.Luck (30)`, `modifyType = EStatModifyType.Flat (2)`, and:

  ```text
  fox_luck_bonus(level) = float32(float32(level) * 0.015f)
  ```

  It then calls the shared `PassiveAbility.SetStat`. There is no loop, random
  roll, decay, or cap in the native method. Relevant current-build RVAs are
  `Init = 0x0047C910`, `OnLevelup = 0x0047CA60`, and
  constructor `0x0047CAF0`.
- A clean live baseline resolved Fox (`ECharacter.Fox = 0`), internal level
  `0`, runtime class `PassiveAbilityRngBlessing`, no passive Luck modifier, and
  combined Luck `0.15000000596046448`.
- A read-only `100ms` capture followed rapid level batches through level `173`.
  Representative exact runtime modifiers were level 3 `0.044999998062849045`,
  level 35 `0.5249999761581421`, level 71 `1.0649999380111694`, level 127
  `1.9049999713897705`, and level 173 `2.5950000286102295`. Every value matched
  the native `float32(level * luckPerLevel)` path.
- The capture observed the writer window directly: player level could advance
  before `SetStat` replaced the passive modifier, and the final combined Luck
  could update on the following sample. The adapter should therefore publish
  the passive dictionary's own modifier as the authoritative currently applied
  value and use `level * luckPerLevel` as its validation invariant. If level and
  modifier briefly disagree, retain/mark the applied modifier as updating
  rather than publishing the ahead-of-writer formula.
- At levels 172-173, unrelated small Luck bonuses changed combined Luck without
  changing the Fox modifier. This proves the passive contribution must not be
  derived from the player's combined Luck total.
- Fox adapter coverage is now `identity verified`, `formula verified`,
  `runtime field verified`, `rapid level transition verified`, and
  `ready for implementation`.

Verified static formulas for the remaining linear MVP adapters (current dump):

- All eight remaining classes use the same native `OnLevelup(int level)`
  template as Fox: convert the integer level to `float32`, multiply by the
  class's `perLevel` field, create one `EStatModifyType.Flat (2)` modifier, and
  replace the class-owned stat through `PassiveAbility.SetStat`. Their `Tick`
  methods are no-ops and none of these paths contains a cap, decay, random roll,
  or per-level catch-up loop.

| Character | Passive | Stat | `perLevel` float32 | `OnLevelup` RVA |
| --- | --- | --- | ---: | ---: |
| SirOofie | `Reinforced` | Armor (`4`) | `0.009999999776482582` | `0x0047C580` |
| Bandit | `Flowstate` | Attack Speed (`15`) | `0.009999999776482582` | `0x00479470` |
| Cl4nk | `CritHappens` | Crit Chance (`18`) | `0.009999999776482582` | `0x00476070` |
| SirChadwell | `Curse` | Difficulty (`38`) | `0.009999999776482582` | `0x00476570` |
| Monke | `WallClimb` | Max HP (`0`) | `2.0` | `0x0047F490` |
| Ogre | `Warrior` | Damage (`12`) | `0.014999999664723873` | `0x0047F980` |
| Spaceman | `Quantum` | XP Gain (`32`) | `0.009999999776482582` | `0x0047C0A0` |
| Vlad | `Vampire` | Lifesteal (`17`) | `0.009999999776482582` | `0x0047EFA0` |

For every row:

```text
linear_passive_bonus(level) = float32(float32(level) * perLevel)
```

- Static formula coverage is complete for the full linear MVP group. Live
  validation should next prioritize Monke / `WallClimb`, because `Max HP +2`
  per level exercises an absolute-number display format rather than another
  percentage card. The remaining same-shape classes then need shorter identity
  and runtime-field spot checks, not a repeat of the full Fox stress capture.

Verified Monke / `WallClimb` live adapter (2026-08-23):

- A clean baseline resolved Monke (`ECharacter.Monke = 11`), internal level
  `0`, runtime class `PassiveAbilityWallClimb`, `hpPerLevel = 2.0`, and no
  class-owned Max HP modifier.
- A read-only `100ms` rapid-level capture reached level `262`. Representative
  exact runtime modifiers were level 3 `6.0`, level 48 `96.0`, level 103
  `206.0`, level 195 `390.0`, and level 262 `524.0`. Every sample settled to
  exactly `float32(level * 2.0)` with no cap or rounding ambiguity.
- The same writer ordering as Fox was visible at levels 48, 87, and 195: the
  player level advanced while the previous class-owned modifier was still
  present, then `SetStat` replaced it on the following sample. This confirms the
  applied runtime modifier is the universal authoritative output for both
  percentage and absolute-value linear adapters.
- Monke adapter coverage is now `identity verified`, `formula verified`,
  `runtime field verified`, `rapid level transition verified`, and
  `ready for implementation`.

Confirmed Dice / `Gamba` adapter findings:

- Dice is internally `ECharacter.Dicehead = 18`; its passive is
  `EPassive.Gamba = 15` and the runtime implementation class is
  `PassiveAbilityGamba`.
- `PassiveAbilityGamba.Init` subscribes `OnLevelup(int level)` to
  `PlayerXp.A_LevelUp`; `Cleanup` removes the same delegate and `Tick` is a
  no-op. The passive therefore rolls only from the level-up event.
- `OnLevelup` catches up all missed levels. While `currentLevel < level`, it
  creates exactly one random stat offer, applies it permanently, then increments
  `currentLevel`. A jump of `+K` levels consequently produces `K` modifier
  objects, not one aggregated roll.
- The offer call is exactly
  `EncounterUtility.GetRandomStatOffers(1, forceLegendary: false,
  useShrineStats: false)`. The `false` pool selector uses the same 27-stat
  `upgradableStatsChaosAndGamble` list as Chaos Tome. Live reading of the
  current build confirmed the ordered IDs as:

  ```text
  0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 15, 16, 17, 18, 19,
  23, 24, 25, 29, 30, 31, 32, 39, 40, 41, 38, 46
  ```

- Jump Height (`EStat 26`) is in the 28-stat Charge Shrine pool but is not in
  the Dice / Chaos Tome pool.
- Stat selection is random. The offer's rarity is a second random result from
  `Rarity.GetEncounterOfferRarity(GetStat(EStat.Luck))`, so current Luck affects
  Dice rarity distribution in the same way it affects an ordinary random
  encounter stat offer.
- There is only one rarity pass: Common `1.0`, Uncommon `1.2`, Rare `1.4`,
  Epic `1.6`, or Legendary `2.0`. Unlike Chaos Tome, Dice has no outer
  upgrade rarity and therefore has five rarity candidates per stat/level, not
  the Chaos Tome's two-rarity combination set.
- `StatInventory.ChangeStat(modifier, permanent: true, timeout: 0,
  addToShrineLog: false)` appends the offer's `StatModifier` object to
  `StatInventory.permanentChanges`. Disassembly and live memory both show one
  persistent modifier object per Dice roll. The existing claim that these
  rolls are necessarily combined into one object is not a safe tracking
  assumption.

Exact level-dependent formula:

Let `n` be `PassiveAbilityGamba.currentLevel` before the roll. It is zero-based:
the first character level uses `n = 0`, the second uses `n = 1`, and so on.

```text
inner(n) = round3(base(stat) * rarity_multiplier(n))

decay(n) = clamp(
    0.75 / (1 + pow(n / 50, 1.5)),
    0.06,
    1.0
)

dice_value(n) = float32(round3(inner(n) * Common[1.0]) * decay(n))
```

- The second `round3(... * Common[1.0])` is present in the native path through
  `StatUtility.GetRarityValue(value, ERarity.Common, 3)`, although the incoming
  offer has already been rounded to three decimals.
- The game does **not** round again after multiplying by `decay(n)`; the stored
  `StatModifier.modification` is the raw `float32` product.
- Constructor constants are `upgradeMultiplier = 0.75`,
  `minMultiplier = 0.06`, and `maxMultiplier = 1.0`.
- The upper clamp is unreachable for normal non-negative levels because the
  unclamped value starts at `0.75` and decreases. The lower clamp first becomes
  active at `n = 255`, after which every roll uses `0.06`.

Reference decay values from the current native implementation:

| Zero-based roll index `n` | Decay multiplier |
| ---: | ---: |
| 0 | `0.750000000` |
| 1 | `0.747884631` |
| 10 | `0.688425362` |
| 25 | `0.554097056` |
| 50 | `0.375000000` |
| 100 | `0.195902914` |
| 200 | `0.083333336` |
| 254 | `0.060242228` |
| 255+ | `0.059999999` (`float32` representation of `0.06`) |

The base stat values and modification types are the same as the canonical
Chaos/Gamble table in
[chaos_tome_mechanics.md](../mechanics/chaos_tome_mechanics.md#3-base-stats--modify-types-table).
Implementation must reuse one canonical rule table rather than copying a second
27-stat mapping into a Dice-specific UI module.

Required memory chain and current-build offsets:

```text
owner_stats
  -> +0x28 PlayerInventory
       -> +0x18 CharacterData
            -> +0x50 eCharacter                 (18 = Dicehead)
       -> +0x30 PlayerXp
            -> +0x14 level                      (validation cross-check)
       -> +0x50 StatInventory
            -> +0x10 permanentChanges           (Dictionary<EStat, List<StatModifier>>)
       -> +0x58 PassiveAbility                   (require PassiveAbilityGamba)
            -> +0x18 upgradeMultiplier          (0.75)
            -> +0x1C minMultiplier              (0.06)
            -> +0x20 maxMultiplier              (1.0)
            -> +0x24 currentLevel               (authoritative roll count)
```

- `PassiveAbilityGamba_TypeInfo` is currently at
  `GameAssembly.dll + 0x02F6A9F0`. The production reader may validate either
  the passive object's class pointer against this initialized TypeInfo or its
  IL2CPP class name against `PassiveAbilityGamba`; it must also require
  `CharacterData.eCharacter == 18`.
- Relevant current-build method RVAs are `PassiveAbilityGamba.OnLevelup` at
  `0x004797D0`, `PassiveAbilityGamba..ctor` at `0x00479A90`,
  `EncounterUtility.GetRandomStatOffers` at `0x00436720`,
  `EncounterUtility.GetRandomStatsChaosAndGamble` at `0x00436E60`,
  `StatInventory.ChangeStat` at `0x0044CA80`, and
  `StatUtility.GetRarityValue` at `0x0044DDD0`.
- All TypeInfo addresses and object offsets are build-sensitive and must fail
  closed when the class, character, field ranges, or pointer chain is invalid.

Live validation evidence (2026-08-23):

- The running game resolved `character_id = 18`, a passive object whose class
  name and class pointer both matched `PassiveAbilityGamba`, player level `1`,
  and passive `currentLevel = 1`.
- The live object repeated the constructor constants exactly: `0.75`,
  `0.05999999865889549`, and `1.0`.
- Among nine permanent modifier objects already present, the one Dice-budgeted
  candidate was Evasion (`EStat 5`) with raw value `0.05250000208616257`.
  This is the exact first-roll Rare fingerprint:
  `round3(0.05 * 1.4) * 0.75 = 0.0525` in `float32`.
- The other permanent modifier objects did not match the only available Dice
  roll. This confirms both that Dice output lives in the shared dictionary and
  that the dictionary contains unrelated sources which must not be attributed
  merely because the character is Dice.
- A second live run was captured continuously from a clean
  `player level = 0` / `currentLevel = 0` baseline through level `145` with a
  read-only `100ms` poll. Every observed state kept the player level and Gamba
  `currentLevel` equal, including catch-up batches such as `49 -> 57`.
- The final dictionary contained `168` distinct permanent modifier objects. A
  one-to-one solve over zero-based indices `0 .. 144` matched exactly `145/145`
  objects to the level-specific Dice formula and left exactly `23` objects
  unclaimed by Dice. No Dice budget slot was missing and no outside modifier
  had to be consumed to complete the assignment.
- All 27 stats in `upgradableStatsChaosAndGamble` appeared in the 145-roll
  sample. The solved rarity distribution was 90 Common, 26 Uncommon, 19 Rare,
  8 Epic, and 2 Legendary, totalling 145. Captured values retained the expected
  unrounded post-decay `float32` tails through level 145.
- Against the portable Python `float32` reference used for the offline solve,
  116 captured values were bit-identical, 26 differed by one ULP, and 3 differed
  by two ULPs; the largest absolute difference was
  `0.00000095367431640625`. This is the practical `powf` implementation boundary:
  production should either reproduce the game's native float path or use a
  narrow two-ULP allowance, not Chaos Tome's broad decimal epsilon.
- Pointer chronology resolved a real cross-level numeric collision. The
  first-roll Common Crit Damage object is exactly `0.07500000298023224`, which
  is also a mathematically valid Legendary Crit Damage fingerprint at `n = 50`.
  It was already reserved for `n = 0`; the new `n = 50` object was Common Gold
  Gain `0.02812500111758709`. A final-snapshot numeric scan therefore has two
  local candidates at `n = 50`, while continuous pointer tracking and the
  global one-object/one-roll constraint recover the unique assignment.
- A controlled mixed batch moved Gamba from level `12` to `16` while two new
  Chaos Tome roll slots also became available. Seven modifier objects appeared
  in the same sample: four matched Dice indices `12 .. 15` exactly, while the
  remaining three were valid Chaos-sized candidates for only two Chaos slots
  (`Elite Damage +14%`, `Elite Spawn +25.2%`, and `Powerup Chance +7%`). Memory
  retains no source tag that can distinguish which one came from another
  source, so the two Chaos rolls must remain ambiguous rather than letting a
  numeric-first tracker guess ownership. The earlier Chaos Lifesteal
  `0.10100000351667404` was likewise excluded from Dice unambiguously.

High-volume Dice/Chaos stress capture (2026-08-23):

- A new clean run began at internal `player level = 0`, Gamba
  `currentLevel = 0`, and Chaos Tome level `1`. Its four initial permanent
  objects were the three neutral `EStat 49` modifiers plus the first Chaos roll,
  Luck `0.08399999886751175` (`+8.4%`).
- Dice and Chaos were then advanced together in rapid batches. At the clean
  stress endpoint, player level and Gamba `currentLevel` were both `1631`,
  Chaos Tome level was `333`, and `permanentChanges` contained exactly `1967`
  distinct objects:

  ```text
  3 neutral start objects + 1,631 Dice rolls + 333 Chaos rolls = 1,967
  ```

  There was no unexplained object, missing Dice roll, or missing Chaos roll.
- A later stable analysis snapshot at Gamba `1642` contained `1980` objects and
  partitioned exactly into 255 level-dependent Dice rolls, 1387 clamped Dice
  rolls (`n >= 255`), 333 Chaos rolls, the three neutral start objects, and two
  unrelated modifiers (Luck `0.0037499999161809683` and Difficulty
  `0.05000000074505806`). Both Dice and Chaos covered all 27 pool stats.
- The 1642-roll Dice rarity solve produced 1074 Common, 278 Uncommon, 196 Rare,
  72 Epic, and 22 Legendary rolls. Against the portable reference, 1587 values
  were bit-identical, 45 were one ULP away, and 10 were two ULPs away; none
  required a wider allowance.
- The clamp boundary was present exactly as reversed. Roll `n = 254` used
  decay `0.06024222821` (captured Uncommon Duration
  `0.00578325381503`), while the following 1387 objects used only the five
  per-stat fingerprints produced by the fixed float32 floor
  `0.05999999865889549`.
- The fast poll caught both halves of the native writer ordering. In one burst,
  `player level` reached `10` while Gamba was still `3`; about `109ms` later,
  Gamba reached `10` and exactly seven new Dice objects were present. Later, a
  new floor-valued Shield object appeared while both counters still read
  `1643`, and Gamba advanced to `1644` on the next sample with no second object.
  This directly validates retaining an unbudgeted modifier across ticks and
  reading modifier objects before the final counter, as required below.
- The first 255 level-specific indices formed a complete one-to-one assignment.
  Of those indices, 248 had one local numeric candidate and seven had two due
  to cross-level fingerprint collisions; pointer chronology plus the global
  one-object/one-roll constraint resolved every collision. All 1387 post-clamp
  Dice objects and all 333 Chaos objects then separated by their disjoint
  fingerprint scales, despite arriving in the same rapid sequence.

Level-145 live fixture (Dice-only solve):

- These are sums of the 145 captured Dice modifier objects, not deltas inferred
  from the player's already-combined final stats. They provide an end-to-end
  fixture for the future snapshot/UI accumulator.

| Stat | Rolls | Raw accumulated Dice value |
| --- | ---: | ---: |
| Max HP | 3 | `12.2254157066` |
| HP Regen | 8 | `58.8169736862` |
| Shield | 2 | `3.08497345448` |
| Thorns | 8 | `9.68536573648` |
| Armor | 4 | `0.103293827735` |
| Evasion | 4 | `0.105954933912` |
| Size | 5 | `0.214483439922` |
| Duration | 9 | `0.304645757191` |
| Projectile Speed | 1 | `0.0158963501453` |
| Damage | 6 | `0.229343121871` |
| Attack Speed | 5 | `0.154972646385` |
| Projectile Count | 3 | `1.04026868939` |
| Lifesteal | 10 | `0.211919269525` |
| Crit Chance | 5 | `0.0761393131688` |
| Crit Damage | 6 | `0.187488538213` |
| Damage to Elites | 6 | `0.257870799862` |
| Knockback | 9 | `0.253520447761` |
| Movement Speed | 6 | `0.152652001008` |
| Pickup Range | 7 | `0.594476684928` |
| Luck | 4 | `0.0720577221364` |
| Gold Gain | 6 | `0.150783888064` |
| XP Gain | 3 | `0.127174647525` |
| Difficulty | 5 | `0.15914941486` |
| Elite Spawn Increase | 4 | `0.267007641494` |
| Powerup Multiplier | 6 | `0.307348627597` |
| Powerup Drop Chance | 3 | `0.0556520828977` |
| Extra Jumps | 7 | `2.18529595435` |

Required Dice / `Gamba` adapter design:

1. Add the `Gamba` adapter behind the generic character-passive identity read.
   It snapshots permanent modifiers and reads
   `PassiveAbilityGamba.currentLevel` as the authoritative roll budget. Keep
   this adapter on the existing `500ms` permanent-modifier/Chaos lane; modifier
   objects persist, so a faster poll is not required to preserve rolls.
2. Extend the raw permanent-modifier boundary (or add a shared source-aware
   reading) to retain `object_ptr`, `stat_id`, `modify_type`, and the unrounded
   `float32 value`. The current `PlayerStatModifierSnapshot` deliberately drops
   pointer/type details and is insufficient for exact cross-source attribution.
3. Snapshot modifier entries before the final `currentLevel` read, matching the
   log-first/budget-second ordering used for Charge Shrines. Still retain
   unbudgeted candidates across ticks: `OnLevelup` writes the modifier before it
   increments `currentLevel`, so a read can land inside that narrow writer
   window.
4. Maintain `last_current_level`, seen modifier pointers, pending candidates,
   per-stat totals, per-stat roll counts, and an ambiguity count. A level rise
   from `L` to `L + K` opens exactly `K` budget slots for zero-based indices
   `L .. L + K - 1`.
5. Match each new modifier only against the five exact level-specific
   fingerprints for its own stat and expected modification type. Reproduce the
   native `float32` operation order in tests. Do not reuse Chaos Tome's broad
   `0.002` epsilon blindly; small Dice values can sit within that tolerance of
   another source. Start from exact/ULP-aware matching or the tighter
   shrine-style tolerance and widen it only from captured live fixtures.
6. When several levels land between samples, solve the batch against all open
   level indices. Separate modifier pointers preserve each raw roll even when
   several rolls chose the same stat. If multiple assignments explain the same
   batch, retain the raw per-stat totals/roll counts only when those facts are
   invariant and mark rarity/index details ambiguous.
7. Reset on run identity change, character/passive change, passive pointer
   replacement, or `currentLevel` rollback. A failed/unknown identity or counter
   read creates no Dice budget and must not consume a permanent modifier.

Cross-source attribution requirements:

- Do not allow Dice, Chaos Tome, and Charge Shrine trackers to
  independently claim the same modifier object. Prefer one shared attribution
  coordinator/ledger keyed by stable `StatModifier` object pointer.
- Charge Shrine entries can be reserved exactly because
  `ShrineLogs.shownLog` exposes the same modifier pointer that was placed in
  `permanentChanges`.
- Chaos Tome remains budgeted by its tome-level delta. If Chaos and Dice levels
  change in the same sample, solve both budgets against the shared candidate
  set before committing either source.
- Numeric matching alone is insufficient. For example, Dice roll `n = 0` with
  Epic rarity is exactly the same magnitude as an Uncommon no-Wrench Shrine
  reward (`0.75 * 1.6 == 1.2`), and an early low-base Dice fingerprint can also
  fall inside the existing Chaos tolerance (for `base = 0.05`, Dice `n = 7`
  Legendary is about `0.071267` versus the Chaos `0.070` fingerprint).
- Unknown or multiply valid ownership must be reported as ambiguous/partial,
  never assigned to whichever tracker happens to run first.

Late attach and coverage semantics:

- `currentLevel` gives the exact number of Dice rolls that should exist, and
  each roll remains a separate modifier object. A late-attach solver can
  therefore test the historical indices `0 .. currentLevel - 1` against the
  permanent list and often recover the complete history.
- Permanent modifiers carry no source tag, so unrelated modifiers can still
  create multiple valid historical assignments. Publish `complete` only for a
  unique full assignment; otherwise publish the unambiguous subset with
  `partial` coverage and an ambiguity count. Do not silently choose one history.
- Continuous tracking from the beginning of the run is the authoritative path;
  late reconstruction is best-effort and must be labelled as such in VOD data.

Planned Live Stats and output contract:

- Add one nested `Passives` tab beside `Chaos` and `Shrines`. It displays only
  the current character; it is not a character selector and does not create 21
  persistent sub-tabs.
- Use a header such as `Fox · RNG Blessing · Lv120`, then render one compact
  card per reported effect. Example: Fox renders `Luck +X%`; Dice renders
  each accumulated rolled stat and may add `xN rolls`; a hybrid passive may
  render both `Level bonus` and `Current conditional bonus` cards.
- Reuse the visual language and empty/loading/error behavior of the existing
  Shrine/Chaos stat cards, but not their source-specific roll model. Average
  roll quality, rarity, and roll count must appear only when the adapter can
  actually prove them.
- Add the snapshot to `RuntimeStateSnapshot` as `character_passive` and let
  `LiveRunTracker` own the last valid immutable state. `StatCardsView` receives
  and renders that snapshot; the UI must not import memory-reader or adapter
  code.
- Make refresh demand-aware. Static linear adapters may refresh with ordinary
  Live Stats state; dynamic adapters declare the faster cadence they require.
  Only `Gamba` joins the shared permanent-modifier attribution lane. Do not
  force every passive through `permanentChanges` merely to share a scheduler.
- Persist the same generic snapshot in VOD format 9 and render it in Recordings
  and the universal Compare Runs `Passives` tab. The comparison includes the
  recorded identity, level, tracking coverage, proven roll count, and permanent
  numeric effects. Future transient effects remain excluded unless storage
  gains a meaningful aggregate such as peak or uptime.
- Expose Dice through the compact Twitch command `!dice` when Dice is active.
  It uses the same abbreviated, pipe-separated accumulated stat format as
  `!chaos` and `!shrines`; another character produces an explicit inactive
  response rather than being formatted as Dice. The command consumes the
  shared snapshot rather than running another detector.
- Dice rarity counts remain diagnostic metadata. They are not required in the
  first compact card/command and must remain unknown when assignment is
  ambiguous.

Recording identity and default naming:

- Persist `character_id` and canonical `character_name` as explicit recording
  metadata, in addition to carrying the generic character-passive snapshot in
  recorded frames. Consumers must never recover character identity by parsing
  the user-editable recording title.
- Bump the VOD format when these metadata fields are introduced. Older
  recordings remain valid with `character_id`/`character_name` absent and keep
  their existing titles.
- Change the generated title from `Run YYYY-MM-DD HH:MM:SS` to
  `{Character} YYYY-MM-DD HH:MM:SS`, for example
  `Dice 2026-08-23 18:40:12`. Keep the existing `Run ...` title only when
  validated character identity is not available at recording start.
- Preserve explicit/custom names unchanged. This rule applies only when the
  caller did not provide a name, and it must not rename existing recordings.
- The app capture layer passes validated `character_id`/`character_name` into
  the recorder. `VodRecorder.start(...)` uses the same `created_at` value for
  both metadata and the generated `{Character} date` title, so auto/manual
  paths cannot produce a one-second timestamp mismatch.
- Manual start, armed/waiting start, automatic start, and automatic run split
  must all use the same title builder. If the character is not cached for a
  manual start, perform the normal identity read before opening the file or use
  the safe `Run ...` fallback; do not open and rewrite the JSONL metadata later.
- No additional permanent character label is required in the first Recordings
  detail view. The generated name already appears in the library, selected-run
  plaque, search results, and Compare Runs selectors. Separate metadata keeps a
  future character badge/filter possible without making that UI mandatory now.

Required sequential research before implementing all 21 adapters:

1. For each runtime class, disassemble and document constructor defaults plus
   `Init`, `OnLevelup`, `Tick`, and subscribed event handlers. Identify the
   authoritative output field and whether the passive replaces, adds, caps, or
   temporarily changes a modifier.
2. Static formula analysis is complete for the full linear group, and the Fox
   percentage plus Monke absolute-value representative cases are live-verified.
   Use shorter post-implementation spot checks for the other same-shape
   percentage adapters.
3. Then characterize hybrid/dynamic passives in controlled groups: current
   stat conditions (`Enduring`, `Float`, `Stonks`, `LockIn`), movement/combat
   state (`SpeedDemon`, `Shadowstep`, `Zooma`, `Bullseye`), and event/progress
   state (`Flex`, `Plague`, `Hoarder`). Do not promise a cumulative number when
   the passive naturally describes a current state or progress counter.
4. Validate at least one low and one high character level for every linear
   formula, plus state transitions for every dynamic adapter. Compare the
   adapter result with the passive object's own modifier dictionary or other
   authoritative runtime field, not the combined player stat.
5. Record an adapter coverage matrix in this section as research completes:
   identity only, formula verified, runtime fields verified, live transition
   verified, and ready for implementation.

Recommended delivery order:

1. Generic identity reader, immutable snapshot types, tracker boundary, and
   the empty/loading/unsupported `Passives` tab.
2. Verified linear adapters plus the already characterized `Gamba` adapter.
   This gives useful coverage quickly without claiming all characters work.
3. Hybrid/dynamic adapters, each enabled only after its own live transition
   test passes.
4. VOD/Recordings, the Compare Runs `Passives` tab, and Twitch `!dice` after
   the Live Stats snapshot contract is stable. OBS and in-game overlay
   consumers remain optional follow-up work and need no second memory detector.

Implemented boundary (2026-08-23):

- `PlayerStatsClient.get_character_passive_reading` validates active
  `ECharacter`/`EPassive`/runtime class and publishes identity for all 21 known
  characters. The nine verified linear adapters read their class-owned
  modifier; formula output is validation only, with the native writer window
  shown as `updating`.
- Dice uses an object-pointer ledger, its authoritative `currentLevel` budget,
  level-specific two-ULP fingerprints, exact Shrine reservations, and a shared
  Dice/Chaos polling lane. Cross-source numeric collisions remain partial and
  cannot be awarded by task order.
- `RuntimeStateSnapshot.character_passive` feeds the same `Passives` renderer
  in Live Stats and Recordings. Unsupported passives keep character/passive
  identity and show `Tracking not supported for this passive` without a
  fabricated bonus.
- VOD format 9 stores character metadata plus the immutable passive snapshot
  per frame. Format 8 and older recordings load with both absent. Generated
  names use `{Character} YYYY-MM-DD HH:MM:SS`; explicit names win unchanged and
  the fallback remains `Run ...` when validated identity is unavailable.
- Compare Runs exposes a universal `Passives` detail tab backed only by the
  recorded `character_passive` snapshot. It compares identity, passive level,
  tracking coverage, proven Dice roll counts, and accumulated numeric effects;
  format 8 and older snapshots use an explicit `No character passive data`
  state rather than fabricated zeroes.
- Twitch `!dice` is configurable in the command grid and template editor,
  appears in `!bonkhelp`, and keeps the permanent-source refresh lane active
  while the bot and command are enabled. Its default response is
  `Dice Lv{level}: {dice}`, with abbreviated stat totals separated by ` | `.
- Automated regression completed with `1,826` tests passing. Post-
  implementation live reads resolved Fox as `supported/complete`; continuous
  Dice/Chaos stress tracking reached Dice `2032/2032` and Chaos `99/99`.
  A late-attach reconstruction correctly remained `partial` at `2031/2032`
  because one exact cross-source collision was not uniquely attributable.
  Final UI smoke testing loaded real Dice and Megachad recordings into Compare
  Runs, rendered their saved coverage states, and exposed the enabled `!dice`
  tile in Twitch Bot without sending an external chat message.

Required tests and in-game acceptance:

- All 21 catalog identities, enum/class mismatch, unknown future character,
  null passive object, character swap, new-run reset, and transient read
  failure. Unsupported adapters must keep identity visible without publishing a
  guessed effect.
- Fox Luck and Monke Max HP low/high/rapid-level validation are complete. After
  implementation, spot-check each remaining enabled adapter's identity/runtime
  field before release.
- Dynamic adapter transitions must prove inactive, active, cap/boundary, and
  reset behavior. Permanent, conditional, progress, and counter effects must
  retain distinct kinds through tracker, VOD serialization, and UI rendering.

Dice / `Gamba` adapter-specific acceptance:

- Formula fixtures for all five rarities at `n = 0`, representative decay
  levels, the `n = 254 -> 255` clamp boundary, and exact `float32` operation
  order with no final round-to-three step.
- First-level attach (`currentLevel = 1`), ordinary one-level increments,
  multiple levels between polls, repeated same-stat rolls, and a delayed
  modifier/counter write split across two samples.
- Dice with no Chaos Tome/Shrine activity, then controlled overlaps with a
  Chaos Tome level and a Charge Shrine reward in the same polling window.
- Character change, new-run reset, passive pointer replacement, counter
  rollback, invalid class/character identity, transient modifier read failure,
  and application attach after several Dice levels.
- Prove that every accepted Dice roll consumes one and only one
  `currentLevel` budget slot and one unique modifier pointer, and that the same
  pointer cannot appear in a Chaos or Shrine result.

Required documentation correction:

- Section 5.1 of
  [chaos_tome_mechanics.md](../mechanics/chaos_tome_mechanics.md#51-why-dice-head-does-not-cause-false-positives)
  currently describes a continuous `random(minMultiplier, maxMultiplier)`
  formula and claims a near-zero chance of matching Chaos fingerprints. The
  current dump disproves that model: the two fields are clamp bounds and Dice
  fingerprints are discrete for a given level/stat/rarity. Correct that section
  when implementing the shared attribution logic; the Chaos roll budget remains
  useful, but the old continuous-noise explanation must not be retained.

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
