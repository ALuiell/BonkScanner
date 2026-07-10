# Stat Label Abbreviations

Date: 2026-07-07

## Purpose

BonkScanner uses a shared set of short stat labels for compact UI and chat
surfaces where full stat names take too much space.

This mapping is now centralized in:

- `src/stat_label_abbreviations.py`

Current consumers:

- Twitch `!stats`
- Twitch `!chaos` / `!chaostome` through `LiveRunTracker`
- Twitch command settings live template preview
- In-game overlay `stats` widget

Recommended future consumer:

- OBS overlay `stats` widget, if we want both overlay surfaces to use the same
  compact naming convention

## Mapping

| Full Label | Abbreviation |
| :--- | :--- |
| Max HP | HP |
| HP Regen | Regen |
| Overheal | Overheal |
| Shield | Shield |
| Armor | Armor |
| Evasion | Evasion |
| Lifesteal | Lifesteal |
| Thorns | Thorns |
| Damage | DMG |
| Crit Chance | Crit |
| Crit Damage | CritDMG |
| Attack Speed | AS |
| Projectile Count | Proj |
| Projectile Bounces | Bounces |
| Size | Size |
| Projectile Speed | ProjSpeed |
| Duration | Dur |
| Damage to Elites | EliteDMG |
| Knockback | KB |
| Movement Speed | MS |
| Extra Jumps | Jumps |
| Jump Height | JumpHeight |
| Luck | Luck |
| Difficulty | Diff |
| Pickup Range | Pickup |
| XP Gain | XP |
| Gold Gain | Gold |
| Elite Spawn Increase | ESI |
| Powerup Multiplier | PM |
| Powerup Drop Chance | PDC |

## Implementation Notes

- Keep config and selection UIs keyed by full stat labels.
- Only compact the display label at render/format time.
- New chat or overlay surfaces should import `abbreviate_stat_label()` instead
  of defining local copies.
