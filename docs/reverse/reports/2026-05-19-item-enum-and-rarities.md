# Item Enum And Rarity Catalog

Date: 2026-05-19

## Goal

Document the full known passive item enum list and the currently confirmed
`ItemData.rarity` value for each item in Megabonk.

This report is implementation-oriented. It is intended to support:

- item name decoding from `EItem`
- item rarity display in UI
- item rarity recording/export
- future filtering/grouping features by rarity

## Important Clarification About Rarity Names

The dumped game enum does **not** use `Uncommon`.

The confirmed `EItemRarity` enum is:

```text
0 Common
1 Rare
2 Epic
3 Legendary
4 Corrupted
5 Quest
```

So the game's core item rarity naming is:

- `Common`
- `Rare`
- `Epic`
- `Legendary`
- `Corrupted`
- `Quest`

If a user-facing UI wants a four-tier simplified display, the closest match is:

- `Common`
- `Rare`
- `Epic`
- `Legendary`

Not:

- `Common`
- `Uncommon`
- `Rare`
- `Legendary`

## Reverse Source

Static enum and field layout from dump:

- `F:\Python\CA_mpc_bridge\Dump\dump.cs`
- `F:\Python\CA_mpc_bridge\Dump\il2cpp.h`

Live rarity extraction source:

- `DataManager.Instance`
- `DataManager.itemData`
- `ItemData.rarity`

## Relevant Class Layout

`DataManager`:

```text
+0x60 unsortedItems List<ItemData>
+0xB8 itemData Dictionary<EItem, ItemData>
```

`ItemData`:

```text
+0x50 inItemPool bool
+0x54 eItem EItem
+0x58 icon
+0x60 rarity EItemRarity
+0x68 unlockRequirement
+0x70 maxAmount
+0x74 maxAmountPerRun
+0x78 itemTickPriority
+0x80 dummyItem
```

`EItemRarity`:

```text
0 Common
1 Rare
2 Epic
3 Legendary
4 Corrupted
5 Quest
```

## Live Extraction Path

Validated on 2026-05-19 from the live game process:

```text
GameAssembly.dll + 0x02F85790
-> DataManager_TypeInfo
-> dereference class pointer
-> +0xB8 static fields
-> +0x8 DataManager.Instance
-> +0xB8 DataManager.itemData Dictionary<EItem, ItemData>
```

From each dictionary entry:

```text
key -> EItem
value -> ItemData*
ItemData +0x60 -> rarity
```

## Full EItem Enum

The dumped enum contains `88` ids:

```text
0 Key
1 Beer
2 SpikyShield
3 Bonker
4 SlipperyRing
5 CowardsCloak
6 GymSauce
7 Battery
8 PhantomShroud
9 ForbiddenJuice
10 DemonBlade
11 GrandmasSecretTonic
12 GiantFork
13 MoldyCheese
14 GoldenSneakers
15 SpicyMeatball
16 Chonkplate
17 LightningOrb
18 IceCube
19 DemonicBlood
20 DemonicSoul
21 BeefyRing
22 Dragonfire
23 GoldenGlove
24 GoldenShield
25 ZaWarudo
26 OverpoweredLamp
27 Feathers
28 Ghost
29 SluttyCannon
30 TurboSocks
31 ShatteredWisdom
32 EchoShard
33 SuckyMagnet
34 Backpack
35 Clover
36 Campfire
37 Rollerblades
38 Skuleg
39 EagleClaw
40 Scarf
41 Anvil
42 Oats
43 CursedDoll
44 EnergyCore
45 ElectricPlug
46 BobDead
47 SoulHarvester
48 Mirror
49 JoesDagger
50 WeebHeadset
51 SpeedBoi
52 Gasmask
53 ToxicBarrel
54 HolyBook
55 BrassKnuckles
56 IdleJuice
57 Kevin
58 Borgar
59 Medkit
60 GamerGoggles
61 UnstableTransfusion
62 BloodyCleaver
63 CreditCardRed
64 CreditCardGreen
65 BossBuster
66 LeechingCrystal
67 TacticalGlasses
68 Cactus
69 CageKey
70 IceCrystal
71 TimeBracelet
72 GloveLightning
73 GlovePoison
74 GloveBlood
75 GloveCurse
76 GlovePower
77 Wrench
78 Beacon
79 GoldenRing
80 QuinsMask
81 CryptKey
82 OldMask
83 Snek
84 Pot
85 BobsLantern
86 Pumpkin
87 WizardsHat
```

## Confirmed Item Rarities

Live `DataManager.itemData` contained `87` item entries in the current build /
session.

The following item rarities were confirmed from `ItemData.rarity`.

### Common

```text
0 Key
4 SlipperyRing
6 GymSauce
7 Battery
9 ForbiddenJuice
13 MoldyCheese
23 GoldenGlove
28 Ghost
30 TurboSocks
35 Clover
38 Skuleg
42 Oats
43 CursedDoll
58 Borgar
59 Medkit
65 BossBuster
67 TacticalGlasses
68 Cactus
70 IceCrystal
71 TimeBracelet
77 Wrench
82 OldMask
```

### Rare

```text
1 Beer
5 CowardsCloak
8 PhantomShroud
10 DemonBlade
14 GoldenSneakers
19 DemonicBlood
24 GoldenShield
27 Feathers
32 EchoShard
34 Backpack
36 Campfire
45 ElectricPlug
55 BrassKnuckles
56 IdleJuice
61 UnstableTransfusion
63 CreditCardRed
66 LeechingCrystal
72 GloveLightning
73 GlovePoison
78 Beacon
86 Pumpkin
```

### Epic

```text
2 SpikyShield
11 GrandmasSecretTonic
20 DemonicSoul
21 BeefyRing
29 SluttyCannon
31 ShatteredWisdom
37 Rollerblades
39 EagleClaw
40 Scarf
46 BobDead
48 Mirror
52 Gasmask
53 ToxicBarrel
57 Kevin
60 GamerGoggles
64 CreditCardGreen
74 GloveBlood
75 GloveCurse
80 QuinsMask
85 BobsLantern
```

### Legendary

```text
3 Bonker
12 GiantFork
15 SpicyMeatball
16 Chonkplate
17 LightningOrb
18 IceCube
22 Dragonfire
25 ZaWarudo
26 OverpoweredLamp
33 SuckyMagnet
41 Anvil
44 EnergyCore
47 SoulHarvester
49 JoesDagger
51 SpeedBoi
54 HolyBook
62 BloodyCleaver
76 GlovePower
79 GoldenRing
83 Snek
84 Pot
87 WizardsHat
```

### Corrupted

```text
No `Corrupted` entries were present in the current live `DataManager.itemData`.
```

### Quest

```text
69 CageKey
81 CryptKey
```

## Missing Enum Id In Live ItemData

`EItem 50 = WeebHeadset` exists in the dumped enum, but it was **not present**
in the live `DataManager.itemData` dictionary or `unsortedItems` list during
validation.

Current implementation guidance:

- keep `WeebHeadset` in the enum/name map
- treat its rarity as unresolved for now
- do not silently invent a rarity

## Validation Summary

Live validation on 2026-05-19:

- `DataManager.itemData` dictionary count: `87`
- unique resolved `EItem` ids: `87`
- duplicate keys observed: `0`
- missing enum id from live item data: `50 WeebHeadset`

## Recommended Implementation Shape

For name decoding:

- use the dumped `EItem` enum as the source of truth for id-to-name mapping

For rarity decoding:

- use this report as the current source of truth
- if implementing a dynamic reader later, read:
  - `DataManager.itemData`
  - dictionary key `EItem`
  - `ItemData.rarity`

Suggested structure:

```text
ITEM_METADATA = {
  7: {"name": "Battery", "rarity": "Common"},
  25: {"name": "ZaWarudo", "rarity": "Legendary"},
  ...
}
```

For unresolved ids:

- allow `"rarity": null` or `"rarity": "Unknown"`
- especially for `50 WeebHeadset` until it is found in live data or assets

## Caveats

- This report confirms the current build's `ItemData.rarity` values.
- It does not prove that every enum id is always active in every game build.
- `Corrupted` exists in the enum but had no entries in the validated live
  catalog.
- `Quest` items are present and should not be merged into the normal four-tier
  rarity display without an intentional UX decision.

