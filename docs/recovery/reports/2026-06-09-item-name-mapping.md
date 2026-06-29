# Item Catalog, Names, Rarities, And UI Mapping

Date: 2026-06-09

## Goal

Keep one implementation reference for Megabonk passive items: live memory paths,
`EItem` IDs, enum/internal names, exact English game UI names, BonkScanner's
current compatibility names, rarity/color tiers, and legacy runtime aliases.

This is the canonical item reference for the current docs.

## Current Result

Status: `[Done]`

Item identity should be stored and compared by `EItem` ID or enum name. Display
should be resolved through the game localization table when exact UI text is
needed.

Recommended identity-to-display path:

```text
ItemData pointer
-> ItemData + 0x54 -> EItem ID
-> player_stats.ITEM_ENUM_NAMES_BY_ID[id]
-> localization key mapping from this document
-> selected language string table value
```

For English UI names, this report used the game's Unity Localization string
tables:

```text
Megabonk_Data/StreamingAssets/aa/StandaloneWindows64/
  localization-assets-shared_assets_all.bundle
  localization-string-tables-english(en)_assets_all.bundle
```

Relevant item table collections:

- `ItemsGray`
- `ItemsBlue`
- `ItemsPink`
- `ItemsYellow`
- `ItemsQuest`

## Memory Sources

Static item catalog root, validated live:

```text
GameAssembly.dll + 0x02F85790
-> DataManager_TypeInfo
-> class_ptr
-> +0xB8 static fields
-> static_fields + 0x8 -> DataManager.Instance
```

Primary catalog dictionary for rarity metadata:

```text
DataManager.Instance
-> +0xB8 itemData Dictionary<EItem, ItemData>
```

Static catalog list used by disabled-item detection:

```text
DataManager.Instance
-> +0x60 unsortedItems List<ItemData>
```

Important `ItemData` fields:

```text
+0x50 inItemPool bool
+0x54 eItem EItem
+0x58 icon
+0x60 rarity
+0x68 unlockRequirement
+0x70 maxAmount
+0x74 maxAmountPerRun
+0x78 itemTickPriority
+0x80 dummyItem
```

Container layouts used by readers:

```text
List<T>
+0x10 _items array
+0x18 _size int32
array data starts at array_ptr + 0x20

Dictionary<TKey, TValue>
+0x18 entries array
+0x20 count int32
entry size 0x18
entry key at entry + 0x8
entry value at entry + 0x10
```

## Rarity And Colors

Use the same user-facing rarity model as the game UI:

```text
Common
Uncommon
Rare
Legendary
Quest
```

Current app color mapping:

| Rarity | Current app tier | Current app color token | Meaning |
| --- | --- | --- | --- |
| `Common` | `COMMON` | `GREEN` | Common items are green. |
| `Uncommon` | `UNCOMMON` | `BLUE` | Uncommon items are blue. |
| `Rare` | `RARE` | `MAGENTA` | Rare items are purple/magenta. |
| `Legendary` | `LEGENDARY` | `YELLOW` | Legendary items are yellow. |
| `Quest` | `special` | `DEFAULT` unless intentionally added | Quest keys should not be flattened into normal item tiers without a UX decision. |

Code source:

```text
src/item_metadata.py
-> ITEMS
-> ITEM_ENUM_NAMES_BY_ID
-> normalize_item_name_for_display()
-> normalize_item_name_for_rarity()

src/gui_styles.py
-> ITEM_RARITY_BY_NAME compatibility export
-> ITEM_RARITY_COLOR_MAP
-> COLOR_MAP
```

## Naming Layers

There are three practical naming layers:

1. **Memory enum identity**: stable internal identity, for example
   `BobsLantern`, `GloveBlood`, `Rollerblades`.
2. **Current BonkScanner compatibility name**: names kept for legacy matching in
   existing recordings, tracked-item config, and aliases, for example
   `Bobs Lantern`, `Glove Blood`, `Rollerblades`.
3. **Game UI localization name**: exact current English UI string, for example
   `Bob's Light`, `Slurp Gloves`, `Turbo Skates`.

For user-facing surfaces, prefer the localization name. Keep the BonkScanner
compatibility name only as an alias/fallback for stored data and older config.

One intentional app display override exists: `GoldenRing` / `Golden Ring` /
`No Implementation` is shown by BonkScanner as `The One Ring` with a special
orange-red item color (`#F97316`). This is not the game's localization string;
keep `Golden Ring` as the canonical matching name.

## Important Name Differences

Some localization keys intentionally differ from enum names:

- `BobsLantern -> BobsLantern_NAME -> Bob's Light`
- `Bonker -> Bonker_NAME -> Big Bonk`
- `DemonBlade -> DemonBlade_NAME -> Demonic Blade`
- `Rollerblades -> Rollerblades_NAME -> Turbo Skates`
- `ShatteredWisdom -> ShatteredKnowledge_NAME -> Shattered Knowledge`
- `GloveLightning -> ThunderMitts_NAME -> Thunder Mitts`
- `GlovePoison -> MoldyGloves_NAME -> Moldy Gloves`
- `GloveBlood -> SlurpGloves_NAME -> Slurp Gloves`
- `GloveCurse -> CursedGrabbies_NAME -> Cursed Grabbies`
- `GlovePower -> PowerGloves_NAME -> Power Gloves`

`Sucky Hoof` was not found in the current English item localization. The correct
English UI name for `SuckyMagnet` is `Sucky Magnet`. Keep `Sucky Hoof` only as a
legacy alias for old recordings/config/tests if needed.

## Full Item Table

| ID | Memory enum name | Localization key | Game UI name (English) | Current BonkScanner name | Rarity | App tier |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `Key` | `Key_NAME` | Key | Key | Common | COMMON |
| 1 | `Beer` | `Beer_NAME` | Beer | Beer | Uncommon | UNCOMMON |
| 2 | `SpikyShield` | `SpikyShield_NAME` | Spiky Shield | Spiky Shield | Rare | RARE |
| 3 | `Bonker` | `Bonker_NAME` | Big Bonk | Bonker | Legendary | LEGENDARY |
| 4 | `SlipperyRing` | `SlipperRing_NAME` | Slippery Ring | Slippery Ring | Common | COMMON |
| 5 | `CowardsCloak` | `CowardsCloak_NAME` | Coward's cloak | Cowards Cloak | Uncommon | UNCOMMON |
| 6 | `GymSauce` | `GymSauce_NAME` | Gym Sauce | Gym Sauce | Common | COMMON |
| 7 | `Battery` | `Battery_NAME` | Battery | Battery | Common | COMMON |
| 8 | `PhantomShroud` | `PhantomShroud_NAME` | Phantom Shroud | Phantom Shroud | Uncommon | UNCOMMON |
| 9 | `ForbiddenJuice` | `ForbiddenJuice_NAME` | Forbidden Juice | Forbidden Juice | Common | COMMON |
| 10 | `DemonBlade` | `DemonBlade_NAME` | Demonic Blade | Demon Blade | Uncommon | UNCOMMON |
| 11 | `GrandmasSecretTonic` | `Grandma_NAME` | Grandma's Secret Tonic | Grandmas Secret Tonic | Rare | RARE |
| 12 | `GiantFork` | `GiantFork_NAME` | Giant Fork | Giant Fork | Legendary | LEGENDARY |
| 13 | `MoldyCheese` | `MoldyCheese_NAME` | Moldy Cheese | Moldy Cheese | Common | COMMON |
| 14 | `GoldenSneakers` | `GoldenSneakers_NAME` | Golden Sneakers | Golden Sneakers | Uncommon | UNCOMMON |
| 15 | `SpicyMeatball` | `SpicyMeatball_NAME` | Spicy Meatball | Spicy Meatball | Legendary | LEGENDARY |
| 16 | `Chonkplate` | `Chonkplate_NAME` | Chonkplate | Chonkplate | Legendary | LEGENDARY |
| 17 | `LightningOrb` | `LightningOrb_NAME` | Lightning Orb | Lightning Orb | Legendary | LEGENDARY |
| 18 | `IceCube` | `IceCube_NAME` | Ice Cube | Ice Cube | Legendary | LEGENDARY |
| 19 | `DemonicBlood` | `DemonicBlood_NAME` | Demonic Blood | Demonic Blood | Uncommon | UNCOMMON |
| 20 | `DemonicSoul` | `DemonicSoul_NAME` | Demonic Soul | Demonic Soul | Rare | RARE |
| 21 | `BeefyRing` | `BeefyRing_NAME` | Beefy Ring | Beefy Ring | Rare | RARE |
| 22 | `Dragonfire` | `Dragonfire_NAME` | Dragonfire | Dragonfire | Legendary | LEGENDARY |
| 23 | `GoldenGlove` | `GoldenGlove_NAME` | Golden Glove | Golden Glove | Common | COMMON |
| 24 | `GoldenShield` | `GoldenShield_NAME` | Golden Shield | Golden Shield | Uncommon | UNCOMMON |
| 25 | `ZaWarudo` | `ZaWarudo_NAME` | Za Warudo | Za Warudo | Legendary | LEGENDARY |
| 26 | `OverpoweredLamp` | `OverpoweredLamp_NAME` | Overpowered Lamp | Overpowered Lamp | Legendary | LEGENDARY |
| 27 | `Feathers` | `Feathers_NAME` | Feathers | Feathers | Uncommon | UNCOMMON |
| 28 | `Ghost` | `Ghost_NAME` | Ghost | Ghost | Common | COMMON |
| 29 | `SluttyCannon` | `SluttyCannon_NAME` | Slutty Cannon | Slutty Cannon | Rare | RARE |
| 30 | `TurboSocks` | `TurboSocks_NAME` | Turbo Socks | Turbo Socks | Common | COMMON |
| 31 | `ShatteredWisdom` | `ShatteredKnowledge_NAME` | Shattered Knowledge | Shattered Wisdom | Rare | RARE |
| 32 | `EchoShard` | `EchoShard_NAME` | Echo Shard | Echo Shard | Uncommon | UNCOMMON |
| 33 | `SuckyMagnet` | `SuckyMagnet_NAME` | Sucky Magnet | Sucky Magnet | Legendary | LEGENDARY |
| 34 | `Backpack` | `Backpack_NAME` | Backpack | Backpack | Uncommon | UNCOMMON |
| 35 | `Clover` | `Clover_NAME` | Clover | Clover | Common | COMMON |
| 36 | `Campfire` | `Campfire_NAME` | Campfire | Campfire | Uncommon | UNCOMMON |
| 37 | `Rollerblades` | `Rollerblades_NAME` | Turbo Skates | Rollerblades | Rare | RARE |
| 38 | `Skuleg` | `Skuleg_NAME` | Skuleg | Skuleg | Common | COMMON |
| 39 | `EagleClaw` | `EagleClaw_NAME` | Eagle Claw | Eagle Claw | Rare | RARE |
| 40 | `Scarf` | `Scarf_NAME` | Scarf | Scarf | Rare | RARE |
| 41 | `Anvil` | `Anvil_NAME` | Anvil | Anvil | Legendary | LEGENDARY |
| 42 | `Oats` | `Oats_NAME` | Oats | Oats | Common | COMMON |
| 43 | `CursedDoll` | `CursedDoll_NAME` | Cursed Doll | Cursed Doll | Common | COMMON |
| 44 | `EnergyCore` | `EnergyCore_NAME` | Energy Core | Energy Core | Legendary | LEGENDARY |
| 45 | `ElectricPlug` | `ElectricPlug_NAME` | Electric Plug | Electric Plug | Uncommon | UNCOMMON |
| 46 | `BobDead` | `BobDead_NAME` | Bob (Dead) | Bob Dead | Rare | RARE |
| 47 | `SoulHarvester` | `SouldHarvester_NAME` | Soul Harvester | Soul Harvester | Legendary | LEGENDARY |
| 48 | `Mirror` | `Mirror_NAME` | Mirror | Mirror | Rare | RARE |
| 49 | `JoesDagger` | `JoesDagger_NAME` | Joe's Dagger | Joes Dagger | Legendary | LEGENDARY |
| 50 | `WeebHeadset` | - | - | Weeb Headset | unresolved | - |
| 51 | `SpeedBoi` | `SpeedBoi_NAME` | Speed Boi | Speed Boi | Legendary | LEGENDARY |
| 52 | `Gasmask` | `GasMask_NAME` | Gas Mask | Gasmask | Rare | RARE |
| 53 | `ToxicBarrel` | `ToxicBarrel_NAME` | Toxic Barrel | Toxic Barrel | Rare | RARE |
| 54 | `HolyBook` | `HolyBook_NAME` | Holy Book | Holy Book | Legendary | LEGENDARY |
| 55 | `BrassKnuckles` | `BrassKnuckles_NAME` | Brass Knuckles | Brass Knuckles | Uncommon | UNCOMMON |
| 56 | `IdleJuice` | `IdleJuice_NAME` | Idle Juice | Idle Juice | Uncommon | UNCOMMON |
| 57 | `Kevin` | `Kevin_NAME` | Kevin | Kevin | Rare | RARE |
| 58 | `Borgar` | `Borgar_NAME` | Borgar | Borgar | Common | COMMON |
| 59 | `Medkit` | `Medkit_NAME` | Medkit | Medkit | Common | COMMON |
| 60 | `GamerGoggles` | `GamerGoggles_NAME` | Gamer Goggles | Gamer Goggles | Rare | RARE |
| 61 | `UnstableTransfusion` | `UnstableTransfusion_NAME` | Unstable Transfusion | Unstable Transfusion | Uncommon | UNCOMMON |
| 62 | `BloodyCleaver` | `BloodyCleaver_NAME` | Bloody Cleaver | Bloody Cleaver | Legendary | LEGENDARY |
| 63 | `CreditCardRed` | `CreditCardRed_NAME` | Credit Card (Red) | Credit Card Red | Uncommon | UNCOMMON |
| 64 | `CreditCardGreen` | `CreditCardGreen_NAME` | Credit Card (Green) | Credit Card Green | Rare | RARE |
| 65 | `BossBuster` | `BossBuster_NAME` | Boss Buster | Boss Buster | Common | COMMON |
| 66 | `LeechingCrystal` | `LeechingCrystal_NAME` | Leeching Crystal | Leeching Crystal | Uncommon | UNCOMMON |
| 67 | `TacticalGlasses` | `TacticalGlasses_NAME` | Tactical Glasses | Tactical Glasses | Common | COMMON |
| 68 | `Cactus` | `Cactus_NAME` | Cactus | Cactus | Common | COMMON |
| 69 | `CageKey` | `CAGE_KEY_NAME` | Golden key | Cage Key | Quest | special |
| 70 | `IceCrystal` | `IceCrystal_NAME` | Ice Crystal | Ice Crystal | Common | COMMON |
| 71 | `TimeBracelet` | `TimeBracelet_NAME` | Time Bracelet | Time Bracelet | Common | COMMON |
| 72 | `GloveLightning` | `ThunderMitts_NAME` | Thunder Mitts | Glove Lightning | Uncommon | UNCOMMON |
| 73 | `GlovePoison` | `MoldyGloves_NAME` | Moldy Gloves | Glove Poison | Uncommon | UNCOMMON |
| 74 | `GloveBlood` | `SlurpGloves_NAME` | Slurp Gloves | Glove Blood | Rare | RARE |
| 75 | `GloveCurse` | `CursedGrabbies_NAME` | Cursed Grabbies | Glove Curse | Rare | RARE |
| 76 | `GlovePower` | `PowerGloves_NAME` | Power Gloves | Glove Power | Legendary | LEGENDARY |
| 77 | `Wrench` | `Wrench_NAME` | Wrench | Wrench | Common | COMMON |
| 78 | `Beacon` | `Beacon_NAME` | Beacon | Beacon | Uncommon | UNCOMMON |
| 79 | `GoldenRing` | `GoldenRing_NAME` | Golden Ring | Golden Ring | Legendary | LEGENDARY |
| 80 | `QuinsMask` | `QuinsMask_NAME` | Quin's Mask | Quins Mask | Rare | RARE |
| 81 | `CryptKey` | `CRYPT_KEY` | Crypt key | Crypt Key | Quest | special |
| 82 | `OldMask` | `OldMask_NAME` | Old Mask | Old Mask | Common | COMMON |
| 83 | `Snek` | `Snek_NAME` | Snek | Snek | Legendary | LEGENDARY |
| 84 | `Pot` | `Pot_NAME` | Pot (stainless steel) | Pot | Legendary | LEGENDARY |
| 85 | `BobsLantern` | `BobsLantern_NAME` | Bob's Light | Bobs Lantern | Rare | RARE |
| 86 | `Pumpkin` | `Pumpkin_NAME` | Pumpkin | Pumpkin | Uncommon | UNCOMMON |
| 87 | `WizardsHat` | `WizardsHat_NAME` | Wizard's Hat | Wizards Hat | Legendary | LEGENDARY |

## Rarity Groups

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

### Uncommon

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

### Rare

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

### Quest

```text
69 CageKey
81 CryptKey
```

## Special Cases

- `WeebHeadset` exists in the known `EItem` enum as ID `50`, but was absent
  from the live `DataManager.itemData` dictionary and `unsortedItems` list
  during validation. Keep it in enum maps, but do not invent a rarity.
- `GoldenRing` is a legendary item but may appear missing from the active item
  pool because `GoldenRing.inItemPool` is excluded by game design for standard
  drops.
- Quest keys use localization entries:
  - `CageKey -> CAGE_KEY_NAME -> Golden key`
  - `CryptKey -> CRYPT_KEY -> Crypt key`

## Legacy Runtime Aliases

Older passive inventory reads identified items through runtime class metadata
names. Keep these aliases for compatibility with old recordings/configs, but do
not treat them as current game UI strings unless confirmed by localization.

| Legacy runtime/class-derived name | Catalog identity | Current English UI name | Guidance |
| --- | --- | --- | --- |
| `Borgor` | `Borgar` | Borgar | Legacy spelling alias. |
| `Bob Lantern` | `BobsLantern` | Bob's Light | Legacy display alias; current game UI is `Bob's Light`. |
| `Flappy Feathers` | `Feathers` | Feathers | Legacy display alias. |
| `Gloves Blood` | `GloveBlood` | Slurp Gloves | Legacy alias for rarity/config matching. |
| `Gloves Cursed` | `GloveCurse` | Cursed Grabbies | Legacy alias for rarity/config matching. |
| `Gloves Lightning` | `GloveLightning` | Thunder Mitts | Legacy alias for rarity/config matching. |
| `Gloves Poison` | `GlovePoison` | Moldy Gloves | Legacy alias for rarity/config matching. |
| `Gloves Power` | `GlovePower` | Power Gloves | Legacy alias for rarity/config matching. |
| `No Implementation` | `GoldenRing` | The One Ring | Runtime class name is misleading; app display override for canonical `Golden Ring`. |
| `Pot Steel` | `Pot` | Pot (stainless steel) | Legacy alias; current game UI is `Pot (stainless steel)`. |
| `Sucky Hoof` | `SuckyMagnet` | Sucky Magnet | Legacy alias only; not found in current English item localization. |

Suggested matching rule:

```text
display/raw name
-> normalize whitespace
-> apply display aliases
-> fold by removing spaces, punctuation, and apostrophes
-> apply folded legacy aliases
-> resolve to catalog identity / rarity
```

## Implementation Notes

- Store item identity as `EItem` ID or enum name wherever possible.
- Display new user-facing item names from localization.
- Keep BonkScanner's current names as compatibility aliases until existing
  recordings, configs, and tests are migrated.
- Rarity/color lookup should resolve through catalog identity, not through
  localized display text.
- Disabled-items UI should prefer `Game UI name (English)` when targeting
  English output.
- If future language support is needed, use the same localization key and load
  the corresponding language string table bundle.
