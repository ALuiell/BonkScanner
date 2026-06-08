# Player Stats Tab Memory Path

Date: 2026-05-11

## Goal

Document the reverse path used to find the live/effective player Stats table in
Megabonk. This is the table used by BonkScanner's `Player Stats` tab.

The target data is the in-game Stats panel values such as Max HP, Damage,
Attack Speed, Difficulty, XP Gain, Luck, Armor, and similar player stats.

## Confirmed Stable Pointer Path

The final/effective player stat values are reachable through this chain:

```text
GameAssembly.dll + 0x02F6A4B8
-> +0xB8
-> +0x0
-> +0x40
-> +0x10
-> +0x18
-> stat_offset
```

In Cheat Engine pointer-entry order, offsets are entered top-to-bottom as:

```text
stat_offset
18
10
40
0
B8
```

For Max HP:

```text
Base address: GameAssembly.dll+02F6A4B8
Type: Float
Pointer: enabled
Hexadecimal value display: disabled
Offsets top-to-bottom:
  2C
  18
  10
  40
  0
  B8
```

This path survived new-run testing and updated correctly when the live Max HP
address changed.

## Stat Offset Formula

Each stat is stored as a `float`.

```text
stat_offset = 0x2C + stat_id * 0x10
```

The low-level write instruction that confirmed the layout:

```asm
GameAssembly.dll+DCFBE1:
movss [rbx+rax*8+2C],xmm6
```

The preceding instructions double the stat id:

```asm
movsxd rax,edi
add rax,rax
```

So the effective stride is:

```text
stat_id * 0x10
```

## Confirmed Stat IDs And Offsets

| Stat | ID | Offset | Display |
| --- | ---: | ---: | --- |
| Max HP | 0 | `0x2C` | flat |
| HP Regen | 1 | `0x3C` | flat |
| Shield | 2 | `0x4C` | flat |
| Thorns | 3 | `0x5C` | flat |
| Armor | 4 | `0x6C` | percent |
| Evasion | 5 | `0x7C` | percent |
| Size | 9 | `0xBC` | multiplier |
| Duration | 10 | `0xCC` | multiplier |
| Projectile Speed | 11 | `0xDC` | multiplier |
| Damage | 12 | `0xEC` | multiplier |
| Attack Speed | 15 | `0x11C` | percent |
| Projectile Count | 16 | `0x12C` | flat |
| Lifesteal | 17 | `0x13C` | percent |
| Crit Chance | 18 | `0x14C` | percent |
| Crit Damage | 19 | `0x15C` | multiplier |
| Damage to Elites | 23 | `0x19C` | multiplier |
| Knockback | 24 | `0x1AC` | multiplier |
| Movement Speed | 25 | `0x1BC` | multiplier |
| Pickup Range | 29 | `0x1FC` | flat |
| Luck | 30 | `0x20C` | percent |
| Gold Gain | 31 | `0x21C` | multiplier |
| XP Gain | 32 | `0x22C` | multiplier |
| Difficulty | 38 | `0x28C` | percent |
| Elite Spawn Increase | 39 | `0x29C` | multiplier |
| Powerup Multiplier | 40 | `0x2AC` | multiplier |
| Powerup Drop Chance | 41 | `0x2BC` | multiplier |
| Extra Jumps | 46 | `0x30C` | flat |

Unknown / not yet confirmed:

```text
Overheal
Projectile Bounces
Jump Height
```

These should remain placeholders until their stat ids are confirmed in Cheat
Engine.

## Display Conversion Rules

The memory values are raw floats.

Percent-like stats are stored as fractions:

```text
0.15 = 15%
0.09 = 9%
```

Multiplier-like stats are stored as direct multipliers:

```text
1.0 = 1.0x
1.25 = 1.25x
2.1 = 2.1x
```

Flat stats are shown as plain numbers:

```text
198 = 198 Max HP
10 = 10 HP Regen
1 = 1 Projectile Count
```

## How The Path Was Found

1. Search Max HP as `Float` in Cheat Engine.
2. Filter with exact values after Max HP changes, such as `100 -> 101 -> 102`.
3. On the matching address, use:

```text
Find out what writes to this address
```

4. Confirm this write instruction:

```asm
movss [rbx+rax*8+2C],xmm6
```

5. Confirm registers for Max HP:

```text
RDI = 0
RAX = 0
RBX = current stats entries base
```

6. Confirm another stat, such as Size:

```text
RDI = 9
address = entries + 0x2C + 9 * 0x10
```

7. Confirm XP Gain:

```text
offset 0x22C -> stat_id 32
```

8. Use pointermaps across two runs to find the stable final/effective path.
The winning path was:

```text
GameAssembly.dll+02F6A4B8
B8, 0, 40, 10, 18, 2C
```

9. Start another new run and confirm the pointer updates to the new Max HP
address.

10. Swap the final offset from `0x2C` to `0x28C` and confirm Difficulty updates
correctly.

## Pointermap Workflow Used

Avoid running a raw Cheat Engine pointer scan without pointermaps. It can
produce billions of useless results.

Safe workflow:

1. Find current final Max HP address.
2. Generate pointermap for run 1.
3. Start a new run or restart the game.
4. Find the new final Max HP address.
5. Run pointer scan for the new address.
6. Enable:

```text
Compare results with other saved pointermap(s)
```

7. Select run 1 pointermap and provide the old Max HP address.
8. Use settings similar to:

```text
Maximum offset value: 2000
Max level: 6
Max different offsets per node: 3
Only module/static paths preferred
```

9. Prefer paths starting with:

```text
GameAssembly.dll+
```

10. Validate candidates by starting a third run and checking whether Max HP and
Difficulty update correctly.

## Implementation Notes

Current implementation files:

```text
player_stats.py
memory.py
gui.py
```

`memory.py` needs `read_float`.

`player_stats.py` reads:

```text
type_info = read_ptr(GameAssembly.dll + 0x02F6A4B8)
static_fields = read_ptr(type_info + 0xB8)
root = read_ptr(static_fields + 0x0)
owner_stats = read_ptr(root + 0x40)
stats_context = read_ptr(owner_stats + 0x10)
entries = read_ptr(stats_context + 0x18)
value = read_float(entries + stat_offset)
```

The GUI can refresh these values slowly. A 10-second refresh interval is enough
for the current BonkScanner `Player Stats` tab and keeps overhead negligible.

## Caveats

- This path was confirmed on the current tested build. A game update can change
  `GameAssembly.dll` type offsets.
- The path appears to read final/effective stats, not only raw/base stats.
- Some nearby paths can read base or pre-final values. For example, one tested
  path showed lower Max HP before item modifiers.
- If values are close but not exact, check whether the path is reading base
  stats instead of final/effective stats.
- Unknown stat ids should not be guessed in production code without CE
  confirmation.
