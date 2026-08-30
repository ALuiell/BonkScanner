# Part 10: Chest Counters and Free Openings Recovery Guide

## Overview
This component monitors total, normal, paid, Key-proc, and inherently free chest
openings, calculates Expected Key procs, and evaluates chest pricing math. The
production classifier combines per-stage map totals,
`RunStats.stats["chestsBought"]`, and `MoneyUtility.chestsPurchased`. Gold-delta
monitoring is retained below only as historical fallback/diagnostic evidence.

- **Target Files**:
  - Code: `src/infra/memory/player_stats_client.py`
  - Tracking: `src/core/tracker/chests.py`
  - Unit Tests: `src/tests/test_player_stats.py`, `src/tests/test_live_run_tracker.py`

---

## Memory Chain Diagrams

### 1. Chests Purchased (MoneyUtility)
```
GameAssembly.dll + MONEY_UTILITY_TYPE_INFO_OFFSET (0x02F5E0B0)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x48 (MONEY_UTILITY_CHESTS_PURCHASED_OFFSET) -> int (chestsPurchased)
```

### 2. Key Proc Probability (ItemKey)
First, retrieve the `ItemKey` object from the passive items dictionary (see Part 3) using key `0` (`EItem.Key`).
```
ItemKey Object Pointer
  -> +0x30 -> float (chancePerStack, e.g. 0.10)
  -> +0x34 -> float (currentChance, combined proc chance)
```

### 3. Normal Chest Count (`RunStats`)

```text
GameAssembly.dll + RUN_STATS_TYPE_INFO_OFFSET (0x02F7A170)
  -> class pointer
    -> +0xB8 -> static fields
      -> +0x00 -> RunStats.stats dictionary
        -> string key "chestsBought" -> cumulative normal openings
```

`chestsBought` includes paid normal openings and successful Key procs. It does
not include chests whose spawn type is inherently free. Total openings come
from the sum of the maximum observed `MapStat.CHESTS.current` value for each
unique stage pointer.

---

## Formulas and Mechanics

### 1. Key Stacking Formula
The standard Key item (ID: `0`) uses a hyperbolic formula to calculate the combined free opening proc chance (`currentChance`) based on the key stack count ($n$, stored in `amount` at offset `0x18` of the item base object):

$$\text{currentChance} = \frac{\text{chancePerStack} \times n}{\text{chancePerStack} \times n + 1.0}$$

With `chancePerStack = 0.10` (10% chance per stack):
- 1 key $\approx 9.09\%$ chance
- 10 keys $= 50\%$ chance
- 50 keys $\approx 83.33\%$ chance

### 2. Chest Price Calculation Formula
The price of the next normal chest is computed dynamically using an exponential base and a piecewise flat increment:

$$\text{Price} = \text{Round}\left( 30 \times 1.22^{N} + \text{AccumulatedIncrease} \right)$$

Where $N$ is `chestsPurchased` and `AccumulatedIncrease` is:
- **For $N \le 10$:** $N \times 35$
- **For $10 < N \le 20$:** $N \times 35 + (N - 10) \times 300$
- **For $20 < N \le 30$:** $N \times 35 + (N - 10) \times 300 + (N - 20) \times 550$
- **For $30 < N \le 40$:** $N \times 35 + (N - 10) \times 300 + (N - 20) \times 550 + (N - 30) \times 1200$

If Green Credit Cards (`ItemCreditCardGreen`) are present, this price is multiplied by:
$$\text{PriceMultiplier} = 1.0 + 0.10 \times \text{CardCount}$$

### 3. Production Counter Classification

For one coherent accepted snapshot:

```text
paid_normal     = chestsPurchased
key_procs       = chestsBought - chestsPurchased
inherently_free = total_opened - chestsBought
```

Require `0 <= chestsPurchased <= chestsBought <= total_opened`. If the values
temporarily disagree during a stage transition, keep the previous valid
breakdown instead of publishing negative or partial counters.

Expected Key procs are accumulated by the fast `expected_chest_inputs` task
from paired `chestsBought` and current Key-stack reads. When `chestsBought`
increases, the current post-open stack is used because a Key dropped by that
chest can proc on the same opening.

### 4. Historical Gold-Delta Fallback

When a `Normal` chest is opened, the game rolls the Key proc chance. Earlier
external-memory work tried to identify a proc with this logic:
1. Prior to chest interaction, read player gold at `PlayerInventory + 0x70` (`goldInt`).
2. Wait for the interaction to trigger (i.e. `InteractableChest.opening` at offset `0x68` becomes `true`).
3. Read the gold amount again.
4. If `GoldBefore == GoldAfter`, the purchase did not consume gold, signifying a free key proc.

Do not use this as the primary production classifier: unrelated gold income,
Merchant spending, and sampling order can offset or hide the purchase delta.

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes in `dump.cs`:
- **`MoneyUtility`**: Find the static fields class. Locate `chestsPurchased` (offset `0x48`).
- **`ItemKey`**: Find fields like `chancePerStack` (offset `0x30`) and `currentChance` (offset `0x34`).
- **`EChest`**:
  - `Normal` = 0
  - `Free` = 2 (Moai / Shrines)
  - `FreeCrypt` = 3

### 2. Cheat Engine Live Verification
- **Verify Chest Purchasing**:
  - Purchase a chest in-game and scan for change in the 4-byte value representing `chestsPurchased`.
  - Trace pointer back to `MoneyUtility` static class.
- **Verify Key Proc Probability**:
  - Add keys to your inventory and verify that the floating-point value at `ItemKey + 0x34` updates matching the hyperbolic stacking formula.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/infra/memory/player_stats_client.py`:
```python
class PlayerStatsClient:
    MONEY_UTILITY_TYPE_INFO_OFFSET = 0x02F5E0B0
    MONEY_UTILITY_CHESTS_PURCHASED_OFFSET = 0x48
```

---

## Verification Steps
1. Run tests:
   ```powershell
   .\run_tests.bat -k "chest" src.tests.test_player_stats
   .\run_tests.bat -k "chest" src.tests.test_live_run_tracker
   ```
2. In a fresh run, validate one paid normal chest, one successful Key proc, and
   one inherently free chest. Confirm the invariant and the separate paid,
   Key-proc, and free counters; gold movement is supporting evidence only.
