# Chaos Tome Upgrade Pool And Scaling

Date: 2026-04-25

## Goal

Determine the static source-of-truth for `Chaos Tome` upgrades in Megabonk, including the full stat pool, the base value for each stat, and the rarity scaling path that produces the final modifier shown/applied for `Common`, `Rare`, `Epic`, and `Legendary`.

## Sources

- Current conversation handoff and live Cheat Engine MCP disassembly against the attached `Megabonk.exe` process
- [Dump/dump.cs](C:\Users\Skadi\Documents\Utilities\BonkScanner\Dump\dump.cs)
- [Dump/il2cpp.h](C:\Users\Skadi\Documents\Utilities\BonkScanner\Dump\il2cpp.h)
- [Dump/script.json](C:\Users\Skadi\Documents\Utilities\BonkScanner\Dump\script.json)

## Reverse Path

1. Start from `ETome.Chaos = 24` in `Dump/dump.cs`, then follow `TomeUtility.CheckSpecialTomes` at `GameAssembly.dll + 0x4304C0`.
2. Confirm the Chaos branch by the `cmp [rbx+0x50], 0x18` check and the jump into the Chaos-specific tail at `GameAssembly.dll + 0x430859`.
3. Confirm that the Chaos tail does not use `TomeData.statModifier` directly. It calls `EncounterUtility.GetRandomStatOffers(1, false, false)` at `GameAssembly.dll + 0x436720`.
4. Follow `useShrineStats = false` inside `GetRandomStatOffers` to `EncounterUtility.GetRandomStatsChaosAndGamble(1)` at `GameAssembly.dll + 0x436E60`.
5. Confirm the static stat pool source in `EncounterUtility..cctor` at `GameAssembly.dll + 0x437260`, where the second initialized list is written to `EncounterUtility_StaticFields.upgradableStatsChaosAndGamble` at `static_fields + 0x8`.
6. Follow numeric generation inside `GetRandomStatOffers` to `EncounterUtility.GetRandomStatValue(EStat, out EStatModifyType)` at `GameAssembly.dll + 0x436B10`.
7. Decode the `GetRandomStatValue` jump table to recover `EStat -> base value + modifyType`.
8. Confirm rarity scaling in `GetRandomStatOffers` via `RarityUtility.GetMultiplier` at `GameAssembly.dll + 0x42DA00`, then confirm the extra Chaos-only pass in `CheckSpecialTomes`: `* chaosTomeMultiplier (1.4)` and `StatUtility.GetRarityValue(..., rarity, 3)` at `GameAssembly.dll + 0x44DDD0`.

## Findings

| Item | Status | Evidence | Notes |
| --- | --- | --- | --- |
| `ETome.Chaos = 24` (`0x18`) | confirmed | `Dump/dump.cs` enum + Chaos branch compare in `CheckSpecialTomes` | Stable tome ID for branch detection |
| `EncounterUtility_StaticFields.upgradableStatsChaosAndGamble` is the stat pool for Chaos/Gamble | confirmed | `Dump/dump.cs`, `Dump/il2cpp.h`, `EncounterUtility..cctor` disassembly | First stable source-of-truth for the Chaos stat pool |
| The Chaos/Gamble list is the second list built in `EncounterUtility..cctor` and is written to `static_fields + 0x8` | confirmed | `GameAssembly.dll + 0x437260` disassembly, write at `+0x438320` | Distinct from shrine and balance lists |
| `CheckSpecialTomes` Chaos branch calls `EncounterUtility.GetRandomStatOffers(1, false, false)` | confirmed | `GameAssembly.dll + 0x4304C0` Chaos branch disassembly | Chaos does not take normal `TomeData.statModifier` path |
| `GetRandomStatOffers(..., useShrineStats=false)` uses `GetRandomStatsChaosAndGamble`, not the normal shrine stat selector | confirmed | `GetRandomStatOffers` disassembly + handoff | This is the stat-selection path used by Chaos |
| The first numeric source-of-truth is `EncounterUtility.GetRandomStatValue(EStat, out EStatModifyType)` | confirmed | `GameAssembly.dll + 0x436B10` jump-table decode | Returns a fixed base value and a fixed modify type per stat |
| `GetRandomStatValue` uses only `Addition (0)` and `Flat (2)` for the Chaos pool | confirmed | `GetRandomStatValue` case handlers | No multiplication-type Chaos stat was observed in the static pool |
| `RarityUtility.GetMultiplier` returns `Common=1.0`, `Uncommon=1.2`, `Rare=1.4`, `Epic=1.6`, `Legendary=2.0` | confirmed | `GameAssembly.dll + 0x42DA00` disassembly + constant reads | Chaos uses the same rarity multiplier function as other encounter offers |
| `GetRandomStatOffers` already rarity-scales the base stat before packaging the `StatModifier` | confirmed | `GameAssembly.dll + 0x436720`: call `GetRandomStatValue`, call `GetMultiplier`, `mulss`, rounding helper, store to `StatModifier.modification` | This is one rarity pass |
| `chaosTomeMultiplier = 1.4f` | confirmed | `TomeUtility..cctor` at `GameAssembly.dll + 0x430B90` | Chaos-only extra multiplier |
| `CheckSpecialTomes` applies `* chaosTomeMultiplier` and then `StatUtility.GetRarityValue(..., rarity, 3)` | confirmed | Chaos tail disassembly at `GameAssembly.dll + 0x430859`, `GetRarityValue` at `+0x44DDD0` | This is a second rarity pass with `decimals = 3` |
| For a fixed `(stat, rarity)` pair, the value is deterministic with no extra random min/max roll | confirmed | `GetRandomStatValue` returns one base constant per stat; both later scaling steps are deterministic | Randomness is stat choice and rarity choice, not value spread |
| `GetRandomStatsChaosAndGamble` appears to select without replacement from the static list | strong | Static list copy/remove style in disassembly + prior live confirmation | Good implementation assumption; exact helper internals were not re-expanded here |
| It is still open whether Chaos can ever surface `Uncommon` in gameplay/UI, even though the common multiplier table supports it | open | `GetMultiplier` supports it, but this pass did not decode `GetEncounterOfferRarity` weights | The table below focuses on `Common/Rare/Epic/Legendary` as requested |

## Stable Rules

| Target | Rule / Path | Stability | Risk |
| --- | --- | --- | --- |
| Chaos stat pool | `EncounterUtility.static_fields + 0x8` -> `upgradableStatsChaosAndGamble` | High | Module-relative class/static field path is stable for this build |
| Chaos stat selection | `CheckSpecialTomes(Chaos)` -> `GetRandomStatOffers(1, false, false)` -> `GetRandomStatsChaosAndGamble(1)` | High | Proven by direct branch and call flow |
| Base stat value | `GetRandomStatValue(EStat, out type)` | High | First numeric source-of-truth for per-stat base value |
| First rarity pass | `GetRandomStatOffers`: `base * GetMultiplier(rarity)` | High | Confirmed in static disassembly |
| Chaos multiplier | `chaosTomeMultiplier = 1.4f` | High | Single constant in `TomeUtility..cctor` |
| Second rarity pass | `CheckSpecialTomes`: `GetRarityValue(value, rarity, 3)` | High | Confirmed callsite with explicit `decimals = 3` |
| Final Chaos formula | `round3(round3(base * rarityMult) * 1.4 * rarityMult)` | High | Matches confirmed code path: rarity pass in `GetRandomStatOffers`, then Chaos tail `*1.4` and `GetRarityValue(..., 3)` |
| Randomness | Rarity roll + stat roll only | High | No per-rarity min/max spread found in static code |

## Chaos Stat Table

`Addition` values are shown as percentages. `Flat` values are raw internal stat values from the confirmed code path.

| EStat | Name | Modify Type | Base | Common | Rare | Epic | Legendary |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | `MaxHealth` | Flat | 15 | 21.0 | 41.16 | 53.76 | 84.0 |
| 1 | `HealthRegen` | Flat | 20 | 28.0 | 54.88 | 71.68 | 112.0 |
| 2 | `Shield` | Flat | 5 | 7.0 | 13.72 | 17.92 | 28.0 |
| 3 | `Thorns` | Flat | 5 | 7.0 | 13.72 | 17.92 | 28.0 |
| 4 | `Armor` | Flat | 0.05 | 0.07 | 0.137 | 0.179 | 0.28 |
| 5 | `Evasion` | Flat | 0.05 | 0.07 | 0.137 | 0.179 | 0.28 |
| 9 | `SizeMultiplier` | Addition | 8% | 11.2% | 22.0% | 28.7% | 44.8% |
| 10 | `DurationMultiplier` | Addition | 8% | 11.2% | 22.0% | 28.7% | 44.8% |
| 11 | `ProjectileSpeedMultiplier` | Addition | 10% | 14.0% | 27.4% | 35.8% | 56.0% |
| 12 | `DamageMultiplier` | Addition | 12% | 16.8% | 32.9% | 43.0% | 67.2% |
| 15 | `AttackSpeed` | Addition | 6% | 8.4% | 16.5% | 21.5% | 33.6% |
| 16 | `Projectiles` | Flat | 1 | 1.4 | 2.744 | 3.584 | 5.6 |
| 17 | `Lifesteal` | Flat | 0.06 | 0.084 | 0.165 | 0.215 | 0.336 |
| 18 | `CritChance` | Flat | 0.05 | 0.07 | 0.137 | 0.179 | 0.28 |
| 19 | `CritDamage` | Addition | 10% | 14.0% | 27.4% | 35.8% | 56.0% |
| 23 | `EliteDamageMultiplier` | Addition | 10% | 14.0% | 27.4% | 35.8% | 56.0% |
| 24 | `KnockbackMultiplier` | Addition | 10% | 14.0% | 27.4% | 35.8% | 56.0% |
| 25 | `MoveSpeedMultiplier` | Addition | 8% | 11.2% | 22.0% | 28.7% | 44.8% |
| 29 | `PickupRange` | Addition | 20% | 28.0% | 54.9% | 71.7% | 112.0% |
| 30 | `Luck` | Flat | 0.05 | 0.07 | 0.137 | 0.179 | 0.28 |
| 31 | `GoldIncreaseMultiplier` | Addition | 7.5% | 10.5% | 20.6% | 26.9% | 42.0% |
| 32 | `XpIncreaseMultiplier` | Addition | 7.5% | 10.5% | 20.6% | 26.9% | 42.0% |
| 38 | `Difficulty` | Flat | 0.08 | 0.112 | 0.22 | 0.287 | 0.448 |
| 39 | `EliteSpawnIncrease` | Addition | 15% | 21.0% | 41.2% | 53.8% | 84.0% |
| 40 | `PowerupBoostMultiplier` | Addition | 10% | 14.0% | 27.4% | 35.8% | 56.0% |
| 41 | `PowerupChance` | Addition | 5% | 7.0% | 13.7% | 17.9% | 28.0% |
| 46 | `ExtraJumps` | Flat | 1 | 1.4 | 2.744 | 3.584 | 5.6 |

## Implementation Handoff

| Data To Read | Start Point | Path / Offset Rule | Expected Output | Confidence | Notes |
| --- | --- | --- | --- | --- | --- |
| Chaos stat pool | `EncounterUtility` type static fields | `upgradableStatsChaosAndGamble` at `static_fields + 0x8` | Fixed list of eligible `EStat` values | confirmed | Best source if implementation wants the pool directly |
| Base numeric table | `GetRandomStatValue(EStat, out EStatModifyType)` at `GameAssembly.dll + 0x436B10` | Decode jump table at `+0x436BE0` / map at `+0x436C24` | `EStat -> {modifyType, baseValue}` | confirmed | This is the safest source-of-truth for static extraction |
| Final Chaos value | `base`, `rarity` | `round3(round3(base * rarityMult) * 1.4 * rarityMult)` | Final internal modifier for the offered Chaos stat | confirmed | Uses `GetMultiplier`, `chaosTomeMultiplier`, and `GetRarityValue(..., 3)` |
| Type formatting | `modifyType` from `GetRandomStatValue` | `0 = Addition`, `2 = Flat` | Whether to render as percent or raw number | confirmed | No multiplication-type Chaos stat found |
| Remaining rarity-roll research | `RarityUtility.GetEncounterOfferRarity(float luck)` | Decode rarity-weight path separately | Actual odds for each rarity tier | open | Not needed for the stat/value table itself |

## Open Questions

- Whether `Chaos Tome` can emit `Uncommon` in real gameplay, or whether the practical pool is only `Common/Rare/Epic/Legendary`.
- Whether any player-facing UI formatting applies additional clamping or prettifying for some `Flat` stats such as `Projectiles`, `ExtraJumps`, `Luck`, or `CritChance`.

## Next Useful Step

Decode `RarityUtility.GetEncounterOfferRarity(float luck)` and `CalculateRarityWeights(...)` so the Chaos report also includes exact rarity odds, not just the per-rarity value table.
