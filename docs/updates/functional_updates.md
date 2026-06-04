# Functional Updates

Date: 2026-06-04

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Open Updates

1. `[Partial]` Add Twitch bot `!powerups` command

   Implemented in the bot and covered by tests; still needs live Twitch/game
   verification. The command reports effective powerup duration using the current
   Powerup Multiplier stat (`PM`):

   - Rage, Shield, Coin, and Speed: `15 sec * PM`
   - Clock: `12 sec * PM`


