# Part 10: Chest Counters and Free Openings Recovery Guide

## Overview
This component monitors the number of chests opened and purchased during a run, calculates key proc probabilities for free chest openings, and evaluates chest pricing math. It uses static trackers from `MoneyUtility` and compares gold delta differences to confirm free key procs in external memory.

- **Target Files**:
  - Code: `src/player_stats.py`
  - Unit Tests: `src/tests/test_player_stats.py`

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

### 3. Delta Gold Monitoring for Free Key Procs
When a `Normal` chest is opened, the game rolls the key's proc chance. In external memory, a key proc is identified using the following logic:
1. Prior to chest interaction, read player gold at `PlayerInventory + 0x70` (`goldInt`).
2. Wait for the interaction to trigger (i.e. `InteractableChest.opening` at offset `0x68` becomes `true`).
3. Read the gold amount again.
4. If `GoldBefore == GoldAfter`, the purchase did not consume gold, signifying a free key proc.

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
Offsets are defined in `PlayerStatsClient` in `src/player_stats.py`:
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
   ```
2. Open a chest using a key in-game and verify that the overlay tracks the free chest opening correctly without decreasing the gold counter.
