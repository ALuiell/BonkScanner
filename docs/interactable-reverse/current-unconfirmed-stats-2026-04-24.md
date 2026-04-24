# Current Unconfirmed Or Caveated Interactable Stats

Date: 2026-04-24

This document lists what is still unconfirmed, caveated, or intentionally out
of scope for the current interactable hook plan.

## Short Answer

For the current BonkScanner target stat set, there are no remaining blockers
for hook implementation.

However, several pieces should still be called out clearly:

- `Pots` is strong through `RandomObjectSpawner`, but not as cleanly documented
  as the `SpawnShrines` selector rules.
- `Chests` is strong through `SpawnChests`, but mixed v7 transform rows also
  saw shrine-like categories near that path, so implementation should keep
  shrine-like stats on the `SpawnShrines` rule.
- `Microwaves` is confirmed for exact class-specific `Start` counting, but not
  confirmed for strict pre-`Start` counting.
- `Bald Heads` is real, but it is not a current target stat.

## Current Target Stats

| Stat | Current status | Remaining caveat |
| --- | --- | --- |
| `Boss Curses` | confirmed | None for hooks. Use `SpawnShrines + MapData.shrines[4]`. |
| `Challenges` | confirmed | None for hooks. Use `SpawnShrines + MapData.shrines[0]`. |
| `Magnet Shrines` | confirmed | None for hooks. Use `SpawnShrines + MapData.shrines[1]`. |
| `Moais` | confirmed | None for hooks. Use `SpawnShrines + MapData.shrines[2]`. |
| `Shady Guy` | confirmed | None for hooks. Use `SpawnShrines + MapData.shrines[3]`. |
| `Charge Shrines` | confirmed | None for hooks. Use singleton `RandomObjectSpawner` bucket `[RCX+0x48]`. |
| `Greed Shrines` | confirmed | None for hooks. Use singleton `RandomObjectSpawner` bucket `[RCX+0x50]`. |
| `Pots` | strong | Good enough for implementation unless a proof-only capture is desired. |
| `Chests` | strong | Good enough for implementation; keep shrine-like categories out of this rule. |
| `Microwaves` | confirmed for exact hook | Strict pre-`Start` counting is not solved. |

## Microwaves Caveat

`Microwaves` is closed for exact hook implementation via:

- `InteractableMicrowave.Start` at `GameAssembly.dll + 0x4CC6A0`
- `RCX` as `InteractableMicrowave*`
- count unique `RCX` component pointers

What is not confirmed:

- an exact strict pre-`Start` source rule
- whether `RandomObjectSpawner` amount/instantiate count can be converted
  directly into exact microwave count

Reason:

- a bridge probe saw an amount `1` `RandomObjectSpawner` bucket followed by two
  `InteractableMicrowave.Start` components
- that suggests prefab/internal child component multiplicity

Conclusion:

- use the class-specific `Start` hook for current implementation
- run a separate reverse pass only if product requirements demand strict
  pre-`Start` microwave counting

## Pots Caveat

`Pots` is strong through `RandomObjectSpawner` bucket/prefab context.

Evidence:

- early buckets are stable and structured
- v6 passive bridge confirmed pot prefab/category links
- v7 linked `RandomObjectSpawner.trans2 -> Pots` heavily

Remaining caveat:

- observed prefab addresses are session-specific
- the current `Pots` rule is not as cleanly table-driven as `SpawnShrines`

Implementation guidance:

- do not hardcode observed prefab pointers
- use current-run `RandomObjectSpawner` bucket/prefab context and instantiate
  success
- keep late debug validation available while testing the hook

## Chests Caveat

`Chests` is strong through:

- `SpawnInteractables.SpawnChests`
- instantiate return `GameAssembly.dll + 0x49D3DA`
- `RAX` as instantiated `GameObject*`

Remaining caveat:

- v7 transform source links also saw some `Magnet Shrines` and `Moais` near
  `SpawnChests`
- those should not be counted through the chest rule

Implementation guidance:

- count chest instantiate returns as `Chests`
- count shrine-like categories through `SpawnShrines + RBX selector`
- keep categories source-specific to avoid cross-source contamination

## Bald Heads / InteractableShrineBalance

`Bald Heads` is real but out of current scope.

Confirmed facts:

- `Bald Heads` is a real debug string
- it belongs to `InteractableShrineBalance.debugName`
- `InteractableShrineBalance.GetDebugName` =
  `GameAssembly.dll + 0x4CDCC0`
- `InteractableShrineBalance.ShowInDebug` =
  `GameAssembly.dll + 0x383DB0`

Observed behavior:

- it appeared once as a late debug row in v7
- it did not participate in the 14-row `SpawnShrines` ordinal selector mapping
- it is not one of the current BonkScanner target stats

Product decision needed before implementation:

- ignore it as debug-only/noise
- expose it as a future stat
- audit it separately as a rare extra object

Current recommendation:

- do not add `Bald Heads` to the main stat set

## SpawnOther Status

`SpawnOther` is not a current implementation source for any confirmed target
stat.

Correct facts:

- `SpawnOther` entry: `GameAssembly.dll + 0x49D4F0`
- real `SpawnOther` instantiate return: `GameAssembly.dll + 0x49D7F6`
- `GameAssembly.dll + 0x49DBE5` is `SpawnRails`

Current recommendation:

- do not use `SpawnOther` for `Shady Guy`, `Microwaves`, or `Bald Heads`
  unless a future targeted probe proves a source-specific link

## What Would Need More Confirmation Only If Requirements Change

Run more reverse work only if one of these becomes a requirement:

- strict pre-`Start` exact counting for `Microwaves`
- adding `Bald Heads` / `InteractableShrineBalance` to the user-facing stat set
- replacing the `Pots` strong source rule with a proof-quality table as clean
  as the `SpawnShrines` selector table
- proving whether real `SpawnOther.instret` at `0x49D7F6` matters for any
  future interactable stat
