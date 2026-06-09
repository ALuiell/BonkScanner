from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemMetadata:
    item_id: int
    enum_name: str
    ui_name: str | None
    scanner_name: str
    rarity: str | None


ITEMS: tuple[ItemMetadata, ...] = (
    ItemMetadata(0, "Key", "Key", "Key", "COMMON"),
    ItemMetadata(1, "Beer", "Beer", "Beer", "UNCOMMON"),
    ItemMetadata(2, "SpikyShield", "Spiky Shield", "Spiky Shield", "RARE"),
    ItemMetadata(3, "Bonker", "Big Bonk", "Bonker", "LEGENDARY"),
    ItemMetadata(4, "SlipperyRing", "Slippery Ring", "Slippery Ring", "COMMON"),
    ItemMetadata(5, "CowardsCloak", "Coward's cloak", "Cowards Cloak", "UNCOMMON"),
    ItemMetadata(6, "GymSauce", "Gym Sauce", "Gym Sauce", "COMMON"),
    ItemMetadata(7, "Battery", "Battery", "Battery", "COMMON"),
    ItemMetadata(8, "PhantomShroud", "Phantom Shroud", "Phantom Shroud", "UNCOMMON"),
    ItemMetadata(9, "ForbiddenJuice", "Forbidden Juice", "Forbidden Juice", "COMMON"),
    ItemMetadata(10, "DemonBlade", "Demonic Blade", "Demon Blade", "UNCOMMON"),
    ItemMetadata(11, "GrandmasSecretTonic", "Grandma's Secret Tonic", "Grandmas Secret Tonic", "RARE"),
    ItemMetadata(12, "GiantFork", "Giant Fork", "Giant Fork", "LEGENDARY"),
    ItemMetadata(13, "MoldyCheese", "Moldy Cheese", "Moldy Cheese", "COMMON"),
    ItemMetadata(14, "GoldenSneakers", "Golden Sneakers", "Golden Sneakers", "UNCOMMON"),
    ItemMetadata(15, "SpicyMeatball", "Spicy Meatball", "Spicy Meatball", "LEGENDARY"),
    ItemMetadata(16, "Chonkplate", "Chonkplate", "Chonkplate", "LEGENDARY"),
    ItemMetadata(17, "LightningOrb", "Lightning Orb", "Lightning Orb", "LEGENDARY"),
    ItemMetadata(18, "IceCube", "Ice Cube", "Ice Cube", "LEGENDARY"),
    ItemMetadata(19, "DemonicBlood", "Demonic Blood", "Demonic Blood", "UNCOMMON"),
    ItemMetadata(20, "DemonicSoul", "Demonic Soul", "Demonic Soul", "RARE"),
    ItemMetadata(21, "BeefyRing", "Beefy Ring", "Beefy Ring", "RARE"),
    ItemMetadata(22, "Dragonfire", "Dragonfire", "Dragonfire", "LEGENDARY"),
    ItemMetadata(23, "GoldenGlove", "Golden Glove", "Golden Glove", "COMMON"),
    ItemMetadata(24, "GoldenShield", "Golden Shield", "Golden Shield", "UNCOMMON"),
    ItemMetadata(25, "ZaWarudo", "Za Warudo", "Za Warudo", "LEGENDARY"),
    ItemMetadata(26, "OverpoweredLamp", "Overpowered Lamp", "Overpowered Lamp", "LEGENDARY"),
    ItemMetadata(27, "Feathers", "Feathers", "Feathers", "UNCOMMON"),
    ItemMetadata(28, "Ghost", "Ghost", "Ghost", "COMMON"),
    ItemMetadata(29, "SluttyCannon", "Slutty Cannon", "Slutty Cannon", "RARE"),
    ItemMetadata(30, "TurboSocks", "Turbo Socks", "Turbo Socks", "COMMON"),
    ItemMetadata(31, "ShatteredWisdom", "Shattered Knowledge", "Shattered Wisdom", "RARE"),
    ItemMetadata(32, "EchoShard", "Echo Shard", "Echo Shard", "UNCOMMON"),
    ItemMetadata(33, "SuckyMagnet", "Sucky Magnet", "Sucky Magnet", "LEGENDARY"),
    ItemMetadata(34, "Backpack", "Backpack", "Backpack", "UNCOMMON"),
    ItemMetadata(35, "Clover", "Clover", "Clover", "COMMON"),
    ItemMetadata(36, "Campfire", "Campfire", "Campfire", "UNCOMMON"),
    ItemMetadata(37, "Rollerblades", "Turbo Skates", "Rollerblades", "RARE"),
    ItemMetadata(38, "Skuleg", "Skuleg", "Skuleg", "COMMON"),
    ItemMetadata(39, "EagleClaw", "Eagle Claw", "Eagle Claw", "RARE"),
    ItemMetadata(40, "Scarf", "Scarf", "Scarf", "RARE"),
    ItemMetadata(41, "Anvil", "Anvil", "Anvil", "LEGENDARY"),
    ItemMetadata(42, "Oats", "Oats", "Oats", "COMMON"),
    ItemMetadata(43, "CursedDoll", "Cursed Doll", "Cursed Doll", "COMMON"),
    ItemMetadata(44, "EnergyCore", "Energy Core", "Energy Core", "LEGENDARY"),
    ItemMetadata(45, "ElectricPlug", "Electric Plug", "Electric Plug", "UNCOMMON"),
    ItemMetadata(46, "BobDead", "Bob (Dead)", "Bob Dead", "RARE"),
    ItemMetadata(47, "SoulHarvester", "Soul Harvester", "Soul Harvester", "LEGENDARY"),
    ItemMetadata(48, "Mirror", "Mirror", "Mirror", "RARE"),
    ItemMetadata(49, "JoesDagger", "Joe's Dagger", "Joes Dagger", "LEGENDARY"),
    ItemMetadata(50, "WeebHeadset", None, "Weeb Headset", None),
    ItemMetadata(51, "SpeedBoi", "Speed Boi", "Speed Boi", "LEGENDARY"),
    ItemMetadata(52, "Gasmask", "Gas Mask", "Gasmask", "RARE"),
    ItemMetadata(53, "ToxicBarrel", "Toxic Barrel", "Toxic Barrel", "RARE"),
    ItemMetadata(54, "HolyBook", "Holy Book", "Holy Book", "LEGENDARY"),
    ItemMetadata(55, "BrassKnuckles", "Brass Knuckles", "Brass Knuckles", "UNCOMMON"),
    ItemMetadata(56, "IdleJuice", "Idle Juice", "Idle Juice", "UNCOMMON"),
    ItemMetadata(57, "Kevin", "Kevin", "Kevin", "RARE"),
    ItemMetadata(58, "Borgar", "Borgar", "Borgar", "COMMON"),
    ItemMetadata(59, "Medkit", "Medkit", "Medkit", "COMMON"),
    ItemMetadata(60, "GamerGoggles", "Gamer Goggles", "Gamer Goggles", "RARE"),
    ItemMetadata(61, "UnstableTransfusion", "Unstable Transfusion", "Unstable Transfusion", "UNCOMMON"),
    ItemMetadata(62, "BloodyCleaver", "Bloody Cleaver", "Bloody Cleaver", "LEGENDARY"),
    ItemMetadata(63, "CreditCardRed", "Credit Card (Red)", "Credit Card Red", "UNCOMMON"),
    ItemMetadata(64, "CreditCardGreen", "Credit Card (Green)", "Credit Card Green", "RARE"),
    ItemMetadata(65, "BossBuster", "Boss Buster", "Boss Buster", "COMMON"),
    ItemMetadata(66, "LeechingCrystal", "Leeching Crystal", "Leeching Crystal", "UNCOMMON"),
    ItemMetadata(67, "TacticalGlasses", "Tactical Glasses", "Tactical Glasses", "COMMON"),
    ItemMetadata(68, "Cactus", "Cactus", "Cactus", "COMMON"),
    ItemMetadata(69, "CageKey", "Golden key", "Cage Key", None),
    ItemMetadata(70, "IceCrystal", "Ice Crystal", "Ice Crystal", "COMMON"),
    ItemMetadata(71, "TimeBracelet", "Time Bracelet", "Time Bracelet", "COMMON"),
    ItemMetadata(72, "GloveLightning", "Thunder Mitts", "Glove Lightning", "UNCOMMON"),
    ItemMetadata(73, "GlovePoison", "Moldy Gloves", "Glove Poison", "UNCOMMON"),
    ItemMetadata(74, "GloveBlood", "Slurp Gloves", "Glove Blood", "RARE"),
    ItemMetadata(75, "GloveCurse", "Cursed Grabbies", "Glove Curse", "RARE"),
    ItemMetadata(76, "GlovePower", "Power Gloves", "Glove Power", "LEGENDARY"),
    ItemMetadata(77, "Wrench", "Wrench", "Wrench", "COMMON"),
    ItemMetadata(78, "Beacon", "Beacon", "Beacon", "UNCOMMON"),
    ItemMetadata(79, "GoldenRing", "Golden Ring", "Golden Ring", "LEGENDARY"),
    ItemMetadata(80, "QuinsMask", "Quin's Mask", "Quins Mask", "RARE"),
    ItemMetadata(81, "CryptKey", "Crypt key", "Crypt Key", None),
    ItemMetadata(82, "OldMask", "Old Mask", "Old Mask", "COMMON"),
    ItemMetadata(83, "Snek", "Snek", "Snek", "LEGENDARY"),
    ItemMetadata(84, "Pot", "Pot (stainless steel)", "Pot", "LEGENDARY"),
    ItemMetadata(85, "BobsLantern", "Bob's Light", "Bobs Lantern", "RARE"),
    ItemMetadata(86, "Pumpkin", "Pumpkin", "Pumpkin", "UNCOMMON"),
    ItemMetadata(87, "WizardsHat", "Wizard's Hat", "Wizards Hat", "LEGENDARY"),
)

ITEM_ENUM_NAMES_BY_ID: dict[int, str] = {item.item_id: item.enum_name for item in ITEMS}
ITEM_METADATA_BY_ENUM_NAME: dict[str, ItemMetadata] = {item.enum_name: item for item in ITEMS}
ITEM_UI_NAME_BY_ENUM_NAME: dict[str, str] = {
    item.enum_name: item.ui_name
    for item in ITEMS
    if item.ui_name
}
ITEM_SCANNER_NAME_BY_ENUM_NAME: dict[str, str] = {
    item.enum_name: item.scanner_name
    for item in ITEMS
}


def _fold_item_name_for_rarity(item_name: str) -> str:
    return "".join(char.lower() for char in item_name if char.isalnum())


ITEM_RARITY_BY_NAME: dict[str, str] = {}
ITEM_DISPLAY_NAME_BY_CANONICAL_NAME: dict[str, str] = {}
for item in ITEMS:
    if not item.rarity:
        continue
    names = {item.scanner_name, item.enum_name}
    if item.ui_name:
        names.add(item.ui_name)
    for name in names:
        ITEM_RARITY_BY_NAME[name] = item.rarity
    ITEM_DISPLAY_NAME_BY_CANONICAL_NAME[item.scanner_name] = item.ui_name or item.scanner_name


ITEM_RARITY_NAME_ALIASES: dict[str, str] = {
    "Flappy Feathers": "Feathers",
    "No Implementation": "Golden Ring",
}

ITEM_RARITY_FOLDED_NAME_ALIASES: dict[str, str] = {
    "boblantern": "bobslantern",
    "bobslantern": "bobslantern",
    "bobslight": "bobslantern",
    "borgor": "borgar",
    "cowardscloak": "cowardscloak",
    "cursedgrabbies": "glovecurse",
    "demonicblade": "demonblade",
    "flappyfeathers": "feathers",
    "gasmask": "gasmask",
    "gasmask": "gasmask",
    "gloveblood": "gloveblood",
    "glovecursed": "glovecurse",
    "glovecurse": "glovecurse",
    "glovelightning": "glovelightning",
    "glovepoison": "glovepoison",
    "glovepower": "glovepower",
    "glovesblood": "gloveblood",
    "glovescursed": "glovecurse",
    "gloveslightning": "glovelightning",
    "glovespoison": "glovepoison",
    "glovespower": "glovepower",
    "moldygloves": "glovepoison",
    "noimplementation": "goldenring",
    "potsteel": "pot",
    "powergloves": "glovepower",
    "shatteredknowledge": "shatteredwisdom",
    "slurpgloves": "gloveblood",
    "suckyhoof": "suckymagnet",
    "theonering": "goldenring",
    "thundermitts": "glovelightning",
    "turboskates": "rollerblades",
}

ITEM_RARITY_NAME_BY_FOLDED_NAME: dict[str, str] = {}
for item in ITEMS:
    if not item.rarity:
        continue
    for name in (item.enum_name, item.ui_name or "", item.scanner_name):
        if name:
            ITEM_RARITY_NAME_BY_FOLDED_NAME[_fold_item_name_for_rarity(name)] = item.scanner_name
for folded, canonical_folded in ITEM_RARITY_FOLDED_NAME_ALIASES.items():
    canonical_name = ITEM_RARITY_NAME_BY_FOLDED_NAME.get(canonical_folded)
    if canonical_name:
        ITEM_RARITY_NAME_BY_FOLDED_NAME[folded] = canonical_name

ITEM_DISPLAY_NAME_ALIASES: dict[str, str] = {}
for item in ITEMS:
    display_name = item.ui_name or item.scanner_name
    for name in (item.enum_name, item.scanner_name, item.ui_name or ""):
        if name:
            ITEM_DISPLAY_NAME_ALIASES[name] = display_name
ITEM_DISPLAY_NAME_ALIASES.update(
    {
        "Bob Lantern": "Bob's Light",
        "Bob's Lantern": "Bob's Light",
        "Borgor": "Borgar",
        "Flappy Feathers": "Feathers",
        "Gloves Blood": "Slurp Gloves",
        "Gloves Cursed": "Cursed Grabbies",
        "Gloves Lightning": "Thunder Mitts",
        "Gloves Poison": "Moldy Gloves",
        "Gloves Power": "Power Gloves",
        "Golden Ring": "The One Ring",
        "GoldenRing": "The One Ring",
        "No Implementation": "The One Ring",
        "Pot Steel": "Pot (stainless steel)",
        "Sucky Hoof": "Sucky Magnet",
    }
)
ITEM_DISPLAY_NAME_BY_CANONICAL_NAME["Golden Ring"] = "The One Ring"

ITEM_DISPLAY_COLOR_BY_CANONICAL_NAME: dict[str, str] = {
    "Golden Ring": "#F97316",
}

ITEM_DISPLAY_NAME_BY_RAW_VALUE: dict[str, str] = {
    **ITEM_UI_NAME_BY_ENUM_NAME,
    "GoldenRing": "The One Ring",
    "NoImplementation": "The One Ring",
}


def normalize_item_name_for_rarity(item_name: str) -> str:
    normalized = " ".join(str(item_name).split())
    if normalized in ITEM_RARITY_NAME_ALIASES:
        return ITEM_RARITY_NAME_ALIASES[normalized]
    if normalized.startswith("Gloves "):
        normalized = f"Glove {normalized[len('Gloves '):]}"

    folded = _fold_item_name_for_rarity(normalized)
    folded = ITEM_RARITY_FOLDED_NAME_ALIASES.get(folded, folded)
    return ITEM_RARITY_NAME_BY_FOLDED_NAME.get(folded, normalized)


def normalize_item_name_for_display(item_name: str) -> str:
    normalized = " ".join(str(item_name).split())
    folded = _fold_item_name_for_rarity(normalized)
    canonical_name = ITEM_RARITY_NAME_BY_FOLDED_NAME.get(
        ITEM_RARITY_FOLDED_NAME_ALIASES.get(folded, folded)
    )
    if canonical_name in ITEM_DISPLAY_NAME_BY_CANONICAL_NAME:
        return ITEM_DISPLAY_NAME_BY_CANONICAL_NAME[canonical_name]
    return ITEM_DISPLAY_NAME_ALIASES.get(normalized, normalized)


def preferred_item_display_name(item_name: str) -> str:
    return normalize_item_name_for_display(item_name)


def item_display_color(item_name: str, fallback: str | None = None) -> str | None:
    canonical_name = normalize_item_name_for_rarity(item_name)
    return ITEM_DISPLAY_COLOR_BY_CANONICAL_NAME.get(canonical_name, fallback)


def available_item_display_names() -> tuple[str, ...]:
    names = {
        ITEM_DISPLAY_NAME_BY_CANONICAL_NAME.get(item.scanner_name, item.ui_name)
        for item in ITEMS
        if item.ui_name
    }
    return tuple(sorted(names, key=str.lower))
