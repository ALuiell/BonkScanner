# Live Player Level Memory Path

Date: 2026-05-20

## Goal

Document the reverse path used to read the live current-run player level shown
in the Megabonk HUD XP/level UI.

The target value is the player's current level during an active run, suitable
for BonkScanner `Live Stats`.

## Best Confirmed Path

Canonical gameplay source:

```text
GameAssembly.dll + 0x02F6A4B8
-> +0xB8
-> +0x0
-> +0x40
-> +0x28
-> +0x30
-> +0x14
```

Resolved semantic path:

```text
GameAssembly.dll + 0x02F6A4B8
-> PlayerStats type info
-> +0xB8
-> static fields
-> +0x0
-> static root
-> +0x40
-> PlayerStatsNew owner
-> +0x28
-> PlayerInventory
-> +0x30
-> PlayerXp
-> +0x14
-> level
```

In Cheat Engine pointer-entry order, offsets are entered top-to-bottom as:

```text
14
30
28
40
0
B8
```

For CE:

```text
Base address: GameAssembly.dll+02F6A4B8
Type: 4 Bytes
Pointer: enabled
Hexadecimal value display: disabled
Offsets top-to-bottom:
  14
  30
  28
  40
  0
  B8
```

## Value Type

- Type: `int`
- Semantic meaning: current player level in the active run

Related field on the same object:

- `PlayerXp.xp` at `+0x10`

## Reverse Evidence

The dump shows:

```text
PlayerInventory
```

with field:

```text
public PlayerXp playerXp; // 0x30
```

The dump also shows:

```text
Inventory__Items__Pickups.Xp_and_Levels.PlayerXp
```

with fields:

```text
public int xp; // 0x10
public int level; // 0x14
public static Action<int> A_LevelUp; // 0x8
public static Action<PlayerXp, int> A_XpAdded; // 0x10
```

HUD-side structural evidence:

```text
XpBarUI
```

with fields and methods:

```text
TextMeshProUGUI t_levelText; // 0x20
RawImage xpBar; // 0x28
Refresh(PlayerXp playerXp)
SetLevelText(int level)
OnXpIncrease(PlayerXp pXp, int amount)
OnLevelUp(int level)
```

This strongly suggests the visible HUD level text is driven by the same
`PlayerXp` object, not by a disconnected UI-only cache.

## Live Validation

Live CE bridge validation on 2026-05-20:

- attached process: `Megabonk.exe`
- candidate record:
  - address: `[[[[[[GameAssembly.dll+2F6A4B8]+B8]+0]+40]+28]+30]+14`
  - type: `4 Bytes`

Observed session:

1. User reported current player level = `1`
2. Live readback:
   - `player_xp.level = 1`
   - `player_xp.xp = 10`
3. User leveled up to `2`
4. Same path updated to:
   - `player_xp.level = 2`
   - `player_xp.xp = 23`

Observed live addresses during confirmation:

```text
PlayerStats class ptr     = 0x19BA2403920
PlayerStats static fields = 0x19DB07F10C0
static root               = 0x19DB4827900
PlayerStatsNew owner      = 0x19DB4264C00
PlayerInventory           = 0x19DB4899AA0
PlayerXp                  = 0x19DB49DCDB0
PlayerXp.level            = 0x19DB49DCDC4
```

The level transition `1 -> 2` on the same path is strong live confirmation.

## Why This Is The Right Source

- it is a gameplay object, not only a UI string
- the field name is explicitly `level`
- the owning object is explicitly `PlayerXp`
- the HUD XP bar class consumes `PlayerXp` and `SetLevelText(int level)`
- the value matched the visible level and incremented on level-up

## Integration Notes

Recommended implementation:

- reuse the same stable root already used for player stats
- read `PlayerInventory` from `PlayerStatsNew + 0x28`
- read `PlayerXp` from `PlayerInventory + 0x30`
- read `int` at `PlayerXp + 0x14`

Pseudo-logic:

```text
type_info = module_base + 0x02F6A4B8
class_ptr = *type_info
static_fields = *(class_ptr + 0xB8)
root = *(static_fields + 0x0)
owner_stats = *(root + 0x40)
player_inventory = *(owner_stats + 0x28)
player_xp = *(player_inventory + 0x30)
level = *(int*)(player_xp + 0x14)
```

Optional companion value:

```text
xp = *(int*)(player_xp + 0x10)
```

## Confidence

Confidence: high

Why high:

- live-validated at level `1`
- live-validated again after level-up to `2`
- dump field names line up exactly with the runtime structure
- HUD consumer class references `PlayerXp` directly

## Caveats

- this path is gameplay-backed and preferable to scraping HUD text
- pause / death / end-of-run behavior was not separately characterized here
- the path depends on the same `PlayerStatsNew` root as other live player
  reads, so if that root ever moves after a game update, level will move with
  it
