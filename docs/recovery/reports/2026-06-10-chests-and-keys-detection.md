# Reverse Engineering Report: Chests & Free Opening Mechanics

This document outlines the findings from the analysis of the `dump.cs` file (IL2CPP metadata) regarding chest opening mechanics, the key system, and methods for detecting free chest openings from memory.

---

## 1. Key Enums

### EChest (Chest Types)
Defines the base properties of a chest spawned on the map.
* **TypeDefIndex**: 5691
* **Value Offset**: `value__` (offset `0x0`)

| Constant | Value | Description |
| :--- | :--- | :--- |
| `Normal` | `0` | Standard chest that costs gold. |
| `Corrupt` | `1` | Corrupted chest. |
| `Free` | `2` | **Free chest** (spawned from Moai / Shrines / Moai Luck). |
| `FreeCrypt` | `3` | **Free Crypt chest**. |
| `Ghost` | `4` | Ghost chest. |

### EItem (Game Items)
Defines the identifiers of items in the inventory.
* **TypeDefIndex**: 5591

| Constant | Value | Description |
| :--- | :--- | :--- |
| `Key` | `0` | **Standard Key** (grants a chance for a free opening). |
| `CageKey` | `69` | Key used to unlock cages (e.g., to rescue monkeys). |
| `CryptKey` | `81` | Key used to unlock the crypt. |

---

## 2. Class Structures and Offsets

### MyPlayer (Player Component)
Used as the entry point to locate the player's inventory, gold, and other statistics.
* **TypeDefIndex**: 5793
* **Static Pointer**: `MyPlayer.Instance` (located at offset `0x8` of the static class in IL2CPP).

```csharp
public class MyPlayer : MonoBehaviour
{
    // Instance Fields
    public PlayerInventory inventory; // Offset: 0x90 (Pointer to PlayerInventory)
    public ECharacter character;      // Offset: 0x40
    private bool isInvincible;        // Offset: 0xCC
    private float baseDamage;          // Offset: 0x12C
}
```

### PlayerInventory (Player Inventory)
Holds the player's resources (including gold) and pointers to other inventory systems.
* **TypeDefIndex**: 4801

```csharp
public class PlayerInventory
{
    // Instance Fields
    public PlayerStatsNew playerStats;   // Offset: 0x10
    public ItemInventory itemInventory;   // Offset: 0x20 (Pointer to ItemInventory)
    public TomeInventory tomeInventory;   // Offset: 0x48
    
    private float <gold>k__BackingField;  // Offset: 0x68 (Current gold - float)
    private int <goldInt>k__BackingField; // Offset: 0x70 (Current gold - int)
    
    public int banishes;                  // Offset: 0x74
    public int refreshes;                 // Offset: 0x78
    public int skips;                     // Offset: 0x7C
    public int skipsUsed;                 // Offset: 0x88
    public int refreshesUsed;             // Offset: 0x8C
    public int banishesUsed;              // Offset: 0x90

    // Methods
    // RVA: 0x4DFF90 | VA: 0x1804DFF90 -- Modifies player's gold amount
    public void ChangeGold(int amount); 
}
```

### ItemInventory (Item Inventory Store)
Holds a dictionary of the player's active passive items.
* **TypeDefIndex**: 5598

```csharp
public class ItemInventory
{
    // Instance Fields
    public Dictionary<EItem, ItemBase> items; // Offset: 0x10

    // Methods
    // RVA: 0x4427E0 | VA: 0x1804427E0 -- Returns the stack amount of an item
    public int GetAmount(EItem eItem); 
}
```

### ItemKey (Key Logic)
Implements the probability of opening a chest for free when interacting.
* **TypeDefIndex**: 5654
* Inherits from: `ItemBase` (located in the `items` dictionary at key `EItem.Key` / `0`).

```csharp
public class ItemKey : ItemBase
{
    // Instance Fields
    private float chancePerStack; // Offset: 0x30 (Free open chance per stack, e.g. 0.1f)
    private float currentChance;  // Offset: 0x34 (Combined chance based on all stacks)

    // Methods
    // RVA: 0x38CFF0 | VA: 0x18038CFF0 -- Returns the current proc chance
    public float GetChance(); 
}
```

> [!NOTE]
> **Key Stacking Formula: Verified & Confirmed** ✅
> 
> The standard Key item uses a **hyperbolic stacking formula** to calculate `currentChance` from the number of key stacks ($n$, stored in `amount` at `0x18` of `ItemBase`):
> 
> $$\text{currentChance} = \frac{\text{chancePerStack} \times n}{\text{chancePerStack} \times n + 1.0}$$
> 
> With `chancePerStack = 0.10f` (10% chance per stack):
> - **1 key**: $\approx 9.09\%$ chance (diminished from 10% base value)
> - **10 keys**: $50.0\%$ chance
> - **50 keys**: $\approx 83.33\%$ chance
> - **100 keys**: $\approx 90.91\%$ chance
> - **99,990 keys**: $\approx 99.99\%$ chance
> 
> You can never reach exactly $100\%$ chance, but it asymptotically approaches $100\%$ with diminishing returns per stack.

---

### InteractableChest (Interactable Chest)
The chest object placed on the game map that the player interacts with.
* **TypeDefIndex**: 5688
* Inherits from: `BaseInteractable` -> `MonoBehaviour`

```csharp
public class InteractableChest : BaseInteractable
{
    // Instance Fields
    public EChest chestType;             // Offset: 0x58 (Chest type from EChest enum)
    private float rotation;              // Offset: 0x5C
    public Transform icon;               // Offset: 0x60
    private bool opening;                // Offset: 0x68 (Becomes true when the chest animation starts)
    private bool isHoveringAndCantAfford;// Offset: 0x69
    public bool isInCrypt;               // Offset: 0x6A
    public bool isShownInDebug;          // Offset: 0x6B

    // Static Events (Global triggers)
    public static Action A_ChestBought;  // Static Offset: 0x0
    public static Action A_ChestOpened;  // Static Offset: 0x8

    // Methods
    // RVA: 0x452FB0 | VA: 0x180452FB0 -- Main interaction entry point
    public override bool Interact(); 

    // RVA: 0x453990 | VA: 0x180453990 -- Internal opening routine
    private void OpenChestImplementation(); 

    // RVA: 0x452F50 | VA: 0x180452F50 -- Computes the gold cost of the chest
    private int GetPrice(); 

    // RVA: 0x452B00 | VA: 0x180452B00 -- Checks if player has enough gold to purchase
    private bool CanAfford(); 
}
```

### ChestOpening (Chest Opening Visualizer)
Used by the chest opening UI to play animations and swap meshes/materials if the chest is free.
* **TypeDefIndex**: 4676

```csharp
public class ChestOpening : MonoBehaviour
{
    // Instance Fields
    public SkinnedMeshRenderer chestRenderer; // Offset: 0x20
    private bool spinning;                    // Offset: 0x48
    private bool opened;                      // Offset: 0x49
    public Mesh meshNormal;                   // Offset: 0xB8
    public Mesh meshFree;                     // Offset: 0xC0 (Used if the chest is opened for free)
    public Material matNormal;                 // Offset: 0xD0
    public Material matFree;                   // Offset: 0xD8 (Used if the chest is opened for free)
    public Material matFreeCrypt;              // Offset: 0xE8

    // Methods
    // RVA: 0x351380 | VA: 0x180351380 -- Starts chest open animation with specific loot
    public void OpenChest(ItemData itemData); 

    // RVA: 0x351660 | VA: 0x180351660 -- Configures meshes and materials based on chest type
    public void SetChest(EChest chestType); 
}
```

---

## 3. Memory Analysis Algorithms for "Free" Opening Detection

### Option A: Static Chest Type Inspection (Inherent Free Chests)
If the chest is spawned on the map as naturally free (e.g. from Moai, Shrines, or Crypt):
1. Find the `InteractableChest` object in the scene.
2. Read the value at offset `0x58` (`chestType`).
3. If the value is **`2`** (`EChest.Free`) or **`3`** (`EChest.FreeCrypt`), the chest will not require gold or keys to open.

### Option B: Delta Gold Monitoring (Key Proc Detection)
When the player opens a `Normal` chest (where cost > 0), the game rolls the key's proc chance. Since `ItemKey.Init` and other callbacks are empty (RVA `0x3321E0`), this proc chance is evaluated inside `OpenChestImplementation()` or `Interact()`.

To detect a key proc in external memory reading:
1. Locate the player's inventory pointer:
   $$\text{PlayerInventoryPtr} = [[\text{MyPlayer.Instance}] + 0x90]$$
2. Prior to the interaction (when `InteractableChest.opening` at offset `0x68` is still `false`), read the current gold amount:
   $$\text{GoldBefore} = [\text{PlayerInventoryPtr} + 0x70] \quad (\text{int type})$$
3. Track when the chest starts opening (i.e. `opening` field becomes `true` or the static event `A_ChestOpened` fires).
4. After the opening animation starts, read the gold amount again:
   $$\text{GoldAfter} = [\text{PlayerInventoryPtr} + 0x70]$$
5. Compare the values:
   * If $\text{GoldBefore} > \text{GoldAfter}$, the gold was subtracted (standard purchase).
   * If $\text{GoldBefore} == \text{GoldAfter}$, the opening was **free** (either standard free chest or key proc).

### Option C: Reading Key Proc Probability
To display or check the current chance of getting a free chest opening:
1. Get the player's item inventory:
   $$\text{ItemInventoryPtr} = [[\text{MyPlayer.Instance}] + 0x90] + 0x20$$
2. Retrieve the `ItemKey` object from the items dictionary (offset `0x10` of `ItemInventory`) using key `0` (`EItem.Key`).
3. Read the float value at offset `0x34` (`currentChance`).
   * A value of e.g. `0.40f` indicates a 40% chance of a free open on the next chest purchase.

---

## 4. Chest Price Calculation Formula

### Base Chest Price Formula (No Modifiers)
The price of the next normal chest is computed using a combination of an exponential base term and a piecewise-linear flat increment term based on the number of chests already purchased:

$$\text{Price} = \text{Round}\left( \text{chestBasePrice} \times \text{chestPriceIncrease}^{N} + \text{AccumulatedIncrease} \right)$$

Where:
* **$\text{chestBasePrice}$** = `30` (static field at `0x28` of `MoneyUtility`)
* **$\text{chestPriceIncrease}$** = `1.22f` (static field at `0x44` of `MoneyUtility`)
* **$N$** = `chestsPurchased` (static field at `0x48` of `MoneyUtility`), representing the number of chests already purchased in the run.
* **$\text{AccumulatedIncrease}$** is a flat value calculated piecewise based on the number of chests purchased:
  * **For $N \le 10$:**  
    $\text{AccumulatedIncrease} = N \times 35$
  * **For $10 < N \le 20$:**  
    $\text{AccumulatedIncrease} = N \times 35 + (N - 10) \times 300$
  * **For $20 < N \le 30$:**  
    $\text{AccumulatedIncrease} = N \times 35 + (N - 10) \times 300 + (N - 20) \times 550$
  * **For $30 < N \le 40$:**  
    $\text{AccumulatedIncrease} = N \times 35 + (N - 10) \times 300 + (N - 20) \times 550 + (N - 30) \times 1200$
  * *Note: For thresholds $N > 40$ and $N > 50$, there is a copy-paste bug in the game's assembly where it continues to subtract `30` instead of `40` or `50` (i.e. `(N - 30) * 2400` and `(N - 30) * 4500` respectively).*

### Price with Cost-Increasing Items (Green Credit Card)
The only item in the game that increases the chest price is the **Green Credit Card** (`ItemCreditCardGreen`), which increases the chest price by **10%** per stack.

When cost-modifying items are present, the base formula is multiplied by `EStat.ChestPriceMultiplier` (Stat ID: `34`), which accumulates the modifiers:

$$\text{Price} = \text{Round}\left( \left( \text{chestBasePrice} \times \text{chestPriceIncrease}^{N} + \text{AccumulatedIncrease} \right) \times \left( 1.0 + 0.10 \times \text{CardCount} \right) \right)$$

Where:
* **$\text{CardCount}$** = number of `ItemCreditCardGreen` stacks in the player's inventory.
