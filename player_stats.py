from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite, pi, sqrt
import time
from typing import Protocol

from memory import MemoryReadError, ProcessMemory


class MemoryReader(Protocol):
    def module_offset(self, module_name: str, offset: int) -> int:
        ...

    def read_ptr(self, address: int) -> int:
        ...

    def read_float(self, address: int) -> float:
        ...

    def read_i32(self, address: int) -> int:
        ...

    def read_ascii_string(self, address: int, max_length: int = 128) -> str | None:
        ...

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        ...


class PlayerStatFormat(Enum):
    FLAT = "flat"
    PERCENT = "percent"
    MULTIPLIER = "multiplier"


class WeaponStatFormat(Enum):
    FLAT = "flat"
    PERCENT = "percent"
    MULTIPLIER = "multiplier"


@dataclass(frozen=True)
class TomeSnapshot:
    tome_id: int
    name: str
    level: int
    stat_id: int | None
    stat_label: str
    value: float | None
    value_format: PlayerStatFormat

    @property
    def display_value(self) -> str:
        return format_player_stat_value(self.value, self.value_format)


@dataclass(frozen=True)
class PlayerStatSpec:
    label: str
    stat_id: int | None
    value_format: PlayerStatFormat

    @property
    def offset(self) -> int | None:
        if self.stat_id is None:
            return None
        return PlayerStatsClient.STAT_VALUE_BASE_OFFSET + (self.stat_id * PlayerStatsClient.STAT_SLOT_SIZE)


PLAYER_STAT_GROUPS: tuple[tuple[PlayerStatSpec, ...], ...] = (
    (
        PlayerStatSpec("Max HP", 0, PlayerStatFormat.FLAT),
        PlayerStatSpec("HP Regen", 1, PlayerStatFormat.FLAT),
        PlayerStatSpec("Overheal", None, PlayerStatFormat.FLAT),
        PlayerStatSpec("Shield", 2, PlayerStatFormat.FLAT),
        PlayerStatSpec("Armor", 4, PlayerStatFormat.PERCENT),
        PlayerStatSpec("Evasion", 5, PlayerStatFormat.PERCENT),
        PlayerStatSpec("Lifesteal", 17, PlayerStatFormat.PERCENT),
        PlayerStatSpec("Thorns", 3, PlayerStatFormat.FLAT),
    ),
    (
        PlayerStatSpec("Damage", 12, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Crit Chance", 18, PlayerStatFormat.PERCENT),
        PlayerStatSpec("Crit Damage", 19, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Attack Speed", 15, PlayerStatFormat.PERCENT),
        PlayerStatSpec("Projectile Count", 16, PlayerStatFormat.FLAT),
        PlayerStatSpec("Projectile Bounces", None, PlayerStatFormat.FLAT),
    ),
    (
        PlayerStatSpec("Size", 9, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Projectile Speed", 11, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Duration", 10, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Damage to Elites", 23, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Knockback", 24, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Movement Speed", 25, PlayerStatFormat.MULTIPLIER),
    ),
    (
        PlayerStatSpec("Extra Jumps", 46, PlayerStatFormat.FLAT),
        PlayerStatSpec("Jump Height", None, PlayerStatFormat.FLAT),
        PlayerStatSpec("Luck", 30, PlayerStatFormat.PERCENT),
        PlayerStatSpec("Difficulty", 38, PlayerStatFormat.PERCENT),
    ),
    (
        PlayerStatSpec("Pickup Range", 29, PlayerStatFormat.FLAT),
        PlayerStatSpec("XP Gain", 32, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Gold Gain", 31, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Elite Spawn Increase", 39, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Powerup Multiplier", 40, PlayerStatFormat.MULTIPLIER),
        PlayerStatSpec("Powerup Drop Chance", 41, PlayerStatFormat.MULTIPLIER),
    ),
)

@dataclass(frozen=True)
class PlayerStatValue:
    spec: PlayerStatSpec
    value: float | None

    @property
    def display_value(self) -> str:
        return format_player_stat_value(self.value, self.spec.value_format)


@dataclass(frozen=True)
class WeaponStatSpec:
    label: str
    value_format: WeaponStatFormat


WEAPON_NAMES_BY_ID: dict[int, str] = {
    0: "Fire Staff",
    1: "Bone",
    2: "Sword",
    3: "Revolver",
    4: "Aura",
    5: "Axe",
    6: "Bow",
    7: "Aegis",
    8: "Test",
    9: "Lightning Staff",
    10: "Flamewalker",
    11: "Rockets",
    12: "Bananarang",
    13: "Tornado",
    14: "Dexecutioner",
    15: "Sniper",
    16: "Frostwalker",
    17: "Space Noodle",
    18: "Dragons Breath",
    19: "Chunkers",
    20: "Mine",
    21: "Poison Flask",
    22: "Black Hole",
    23: "Katana",
    24: "Blood Magic",
    25: "Bluetooth Dagger",
    26: "Dice",
    27: "Hero Sword",
    28: "Corrupt Sword",
    29: "Shotgun",
    30: "Scythe",
}

WEAPON_STAT_SPECS: dict[int, WeaponStatSpec] = {
    9: WeaponStatSpec("Size", WeaponStatFormat.MULTIPLIER),
    10: WeaponStatSpec("Duration", WeaponStatFormat.MULTIPLIER),
    11: WeaponStatSpec("Speed", WeaponStatFormat.MULTIPLIER),
    12: WeaponStatSpec("Damage", WeaponStatFormat.FLAT),
    15: WeaponStatSpec("Attack Speed", WeaponStatFormat.MULTIPLIER),
    16: WeaponStatSpec("Projectiles", WeaponStatFormat.FLAT),
    18: WeaponStatSpec("Crit Chance", WeaponStatFormat.PERCENT),
    19: WeaponStatSpec("Crit Damage", WeaponStatFormat.MULTIPLIER),
    24: WeaponStatSpec("Knockback", WeaponStatFormat.MULTIPLIER),
    45: WeaponStatSpec("Projectile Bounces", WeaponStatFormat.FLAT),
}

TOME_NAMES_BY_ID: dict[int, str] = {
    0: "Damage",
    1: "Agility",
    2: "Cooldown",
    3: "Quantity",
    4: "Knockback",
    5: "Armor",
    6: "Health",
    7: "Regeneration",
    8: "Size",
    9: "Projectile Speed",
    10: "Duration",
    11: "Evasion",
    12: "Attraction",
    13: "Luck",
    14: "XP",
    15: "Golden",
    16: "Precision",
    17: "Shield",
    18: "Blood",
    19: "Thorns",
    20: "Bounce",
    21: "Cursed",
    22: "Silver",
    23: "Balance",
    24: "Chaos",
    25: "Gambler",
    26: "Hoarder",
}

ITEM_ENUM_NAMES_BY_ID: dict[int, str] = {
    0: "Key",
    1: "Beer",
    2: "SpikyShield",
    3: "Bonker",
    4: "SlipperyRing",
    5: "CowardsCloak",
    6: "GymSauce",
    7: "Battery",
    8: "PhantomShroud",
    9: "ForbiddenJuice",
    10: "DemonBlade",
    11: "GrandmasSecretTonic",
    12: "GiantFork",
    13: "MoldyCheese",
    14: "GoldenSneakers",
    15: "SpicyMeatball",
    16: "Chonkplate",
    17: "LightningOrb",
    18: "IceCube",
    19: "DemonicBlood",
    20: "DemonicSoul",
    21: "BeefyRing",
    22: "Dragonfire",
    23: "GoldenGlove",
    24: "GoldenShield",
    25: "ZaWarudo",
    26: "OverpoweredLamp",
    27: "Feathers",
    28: "Ghost",
    29: "SluttyCannon",
    30: "TurboSocks",
    31: "ShatteredWisdom",
    32: "EchoShard",
    33: "SuckyMagnet",
    34: "Backpack",
    35: "Clover",
    36: "Campfire",
    37: "Rollerblades",
    38: "Skuleg",
    39: "EagleClaw",
    40: "Scarf",
    41: "Anvil",
    42: "Oats",
    43: "CursedDoll",
    44: "EnergyCore",
    45: "ElectricPlug",
    46: "BobDead",
    47: "SoulHarvester",
    48: "Mirror",
    49: "JoesDagger",
    50: "WeebHeadset",
    51: "SpeedBoi",
    52: "Gasmask",
    53: "ToxicBarrel",
    54: "HolyBook",
    55: "BrassKnuckles",
    56: "IdleJuice",
    57: "Kevin",
    58: "Borgar",
    59: "Medkit",
    60: "GamerGoggles",
    61: "UnstableTransfusion",
    62: "BloodyCleaver",
    63: "CreditCardRed",
    64: "CreditCardGreen",
    65: "BossBuster",
    66: "LeechingCrystal",
    67: "TacticalGlasses",
    68: "Cactus",
    69: "CageKey",
    70: "IceCrystal",
    71: "TimeBracelet",
    72: "GloveLightning",
    73: "GlovePoison",
    74: "GloveBlood",
    75: "GloveCurse",
    76: "GlovePower",
    77: "Wrench",
    78: "Beacon",
    79: "GoldenRing",
    80: "QuinsMask",
    81: "CryptKey",
    82: "OldMask",
    83: "Snek",
    84: "Pot",
    85: "BobsLantern",
    86: "Pumpkin",
    87: "WizardsHat",
}

ITEM_DISPLAY_NAME_BY_RAW_VALUE = {
    "NoImplementation": "Golden Ring",
}


@dataclass(frozen=True)
class WeaponStatValue:
    stat_id: int
    label: str
    value: float | None
    value_format: WeaponStatFormat

    @property
    def display_value(self) -> str:
        return format_weapon_stat_value(self.value, self.value_format)


@dataclass(frozen=True)
class WeaponSnapshot:
    weapon_id: int
    name: str
    level: int
    upgrade_stat_ids: tuple[int, ...]
    upgraded_stats: dict[int, WeaponStatValue]
    full_stats: dict[int, WeaponStatValue]


def calculate_chests_per_minute(
    elite_spawn_increase: float,
    powerup_drop_chance: float,
    *,
    kills_per_second: float = 200.0,
) -> float:
    if not all(
        isfinite(value)
        for value in (elite_spawn_increase, powerup_drop_chance, kills_per_second)
    ):
        return 0.0

    if elite_spawn_increase <= 0.0 or powerup_drop_chance <= 0.0 or kills_per_second <= 0.0:
        return 0.0

    elite_chance = min(elite_spawn_increase * 0.006, 1.0)
    elite_drop_multiplier = 1.0 + elite_chance
    chest_chance_per_kill = 0.001 * powerup_drop_chance * elite_drop_multiplier
    max_chest_rate_per_second = kills_per_second * chest_chance_per_kill
    if max_chest_rate_per_second <= 0.0:
        return 0.0

    average_seconds_per_chest = sqrt((pi * 420.0) / (2.0 * max_chest_rate_per_second))
    if average_seconds_per_chest <= 0.0:
        return 0.0
    return 60.0 / average_seconds_per_chest


@dataclass(frozen=True)
class PlayerStatsSnapshot:
    elapsed_seconds: int
    captured_at: float
    stats: dict[str, PlayerStatValue]
    items: tuple[str, ...] = ()
    weapons: tuple[WeaponSnapshot, ...] = ()
    tomes: tuple[TomeSnapshot, ...] = ()
    banishes: tuple[str, ...] = ()
    game_time_seconds: float | None = None
    mob_kills: int | None = None
    player_level: int | None = None

    @property
    def time_label(self) -> str:
        minutes, seconds = divmod(max(self.elapsed_seconds, 0), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


class PlayerStatsTimeline:
    def __init__(
        self,
        *,
        interval_seconds: int = 60,
        clock=time.monotonic,
    ) -> None:
        self.interval_seconds = max(1, int(interval_seconds))
        self.clock = clock
        self.snapshots: list[PlayerStatsSnapshot] = []
        self.is_recording = False
        self.start_time: float | None = None
        self.last_snapshot_time: float | None = None

    def start(self) -> None:
        now = self.clock()
        self.snapshots.clear()
        self.is_recording = True
        self.start_time = now
        self.last_snapshot_time = None

    def stop(self) -> None:
        self.is_recording = False

    def elapsed_seconds(self) -> int:
        if self.start_time is None:
            return 0
        return max(0, int(self.clock() - self.start_time))

    def elapsed_label(self) -> str:
        minutes, seconds = divmod(self.elapsed_seconds(), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def should_capture(self) -> bool:
        if not self.is_recording:
            return False
        if self.last_snapshot_time is None:
            return True
        return self.clock() - self.last_snapshot_time >= self.interval_seconds

    def capture(
        self,
        stats: dict[str, PlayerStatValue],
        items: tuple[str, ...] = (),
        weapons: tuple[WeaponSnapshot, ...] = (),
        tomes: tuple[TomeSnapshot, ...] = (),
        banishes: tuple[str, ...] = (),
    ) -> PlayerStatsSnapshot:
        now = self.clock()
        start_time = self.start_time if self.start_time is not None else now
        snapshot = PlayerStatsSnapshot(
            elapsed_seconds=int(now - start_time),
            captured_at=now,
            stats=dict(stats),
            items=tuple(items),
            weapons=tuple(weapons),
            tomes=tuple(tomes),
            banishes=tuple(banishes),
        )
        self.snapshots.append(snapshot)
        self.last_snapshot_time = now
        return snapshot

    def get_snapshot(self, index: int) -> PlayerStatsSnapshot | None:
        if not self.snapshots:
            return None
        index = min(max(index, 0), len(self.snapshots) - 1)
        return self.snapshots[index]


class PlayerStatsClient:
    TYPE_INFO_OFFSET = 0x02F6A4B8
    RUN_TIMER_TYPE_INFO_OFFSET = 0x02F62398
    RUN_STATS_TYPE_INFO_OFFSET = 0x02F7A170
    RUN_UNLOCKABLES_TYPE_INFO_OFFSET = 0x02F7A210
    POTATO_TYPE_INFO_OFFSET = 0x02F6FC78
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    STATIC_ROOT_OFFSET = 0x0
    OWNER_STATS_OFFSET = 0x40
    STATS_CONTEXT_OFFSET = 0x10
    STATS_ENTRIES_OFFSET = 0x18
    STAGE_TIMER_OFFSET = 0x1C
    RUN_TIMER_OFFSET = 0x20
    PLAYER_INVENTORY_OFFSET = 0x28
    WEAPON_INVENTORY_OFFSET = 0x28
    TOME_INVENTORY_OFFSET = 0x48
    WEAPONS_DICT_OFFSET = 0x18
    TOME_LEVELS_DICT_OFFSET = 0x18
    TOME_UPGRADES_DICT_OFFSET = 0x28
    WEAPON_DATA_OFFSET = 0x18
    WEAPON_LEVEL_OFFSET = 0x20
    WEAPON_STATS_DICT_OFFSET = 0x28
    WEAPON_ID_OFFSET = 0x50
    PLAYER_XP_OFFSET = 0x30
    PLAYER_XP_LEVEL_OFFSET = 0x14
    WEAPON_UPGRADE_DATA_OFFSET = 0xD8
    UPGRADE_MODIFIERS_OFFSET = 0x18
    STAT_VALUE_BASE_OFFSET = 0x2C
    STAT_SLOT_SIZE = 0x10
    ITEM_INVENTORY_OFFSET = 0x20
    ITEM_INVENTORY_ITEMS_DICT_OFFSET = 0x10
    INVENTORY_CONTAINER_OFFSET = 0xA0
    PASSIVE_ITEM_DICT_OFFSET = 0x50
    DICT_ENTRIES_OFFSET = 0x18
    DICT_COUNT_OFFSET = 0x20
    DICT_ENTRY_START_OFFSET = 0x20
    DICT_ENTRY_SIZE = 0x18
    DICT_ENTRY_HASH_CODE_OFFSET = 0x0
    DICT_ENTRY_KEY_OFFSET = 0x8
    DICT_ENTRY_VALUE_OFFSET = 0x10
    MAX_PASSIVE_ITEM_DICT_ENTRIES = 512
    MAX_WEAPON_DICT_ENTRIES = 64
    MAX_WEAPON_STATS_ENTRIES = 128
    MAX_UPGRADE_MODIFIERS = 64
    ITEM_CLASS_META_OFFSET = 0x0
    ITEM_STACK_COUNT_OFFSET = 0x18
    CLASS_META_NAME_PTR_OFFSET = 0x10
    LIST_ITEMS_OFFSET = 0x10
    LIST_SIZE_OFFSET = 0x18
    ARRAY_LENGTH_OFFSET = 0x18
    ARRAY_DATA_OFFSET = 0x20
    OBJECT_POINTER_SIZE = 0x8
    OBJECT_KLASS_OFFSET = 0x0
    KLASS_NAME_PTR_OFFSET = 0x10
    WEAPON_DICT_ENTRY_SIZE = 0x18
    WEAPON_DICT_ENTRY_KEY_OFFSET = 0x8
    WEAPON_DICT_ENTRY_VALUE_OFFSET = 0x10
    STAT_DICT_ENTRY_SIZE = 0x10
    STAT_DICT_ENTRY_KEY_OFFSET = 0x8
    STAT_DICT_ENTRY_VALUE_OFFSET = 0x0C
    STAT_MODIFIER_STAT_OFFSET = 0x10
    STAT_MODIFIER_VALUE_OFFSET = 0x18
    RUN_STATS_DICT_OFFSET = 0x0
    RUN_STATS_ENTRY_VALUE_OFFSET = 0x10
    MAX_RUN_STATS_ENTRIES = 256
    HASHSET_SLOTS_OFFSET = 0x18
    HASHSET_COUNT_OFFSET = 0x20
    HASHSET_LAST_INDEX_OFFSET = 0x24
    HASHSET_SLOT_START_OFFSET = 0x20
    HASHSET_SLOT_SIZE = 0x10
    HASHSET_SLOT_HASH_CODE_OFFSET = 0x0
    HASHSET_SLOT_VALUE_OFFSET = 0x8
    ITEM_DATA_ENUM_OFFSET = 0x54
    TOME_DATA_ENUM_OFFSET = 0x50
    RUN_UNLOCKABLES_BANISHED_ITEMS_OFFSET = 0x0
    RUN_UNLOCKABLES_BANISHED_UPGRADABLES_OFFSET = 0x8
    MAX_BANISHED_UNLOCKABLES = 128

    def __init__(
        self,
        process_name: str | None = None,
        *,
        module_name: str = "GameAssembly.dll",
        memory: MemoryReader | None = None,
    ) -> None:
        if memory is None and not process_name:
            raise ValueError("process_name is required when memory backend is not provided.")

        self.module_name = module_name
        self._owns_memory = memory is None
        self.memory: MemoryReader = memory or ProcessMemory(process_name)

    def close(self) -> None:
        if self._owns_memory and hasattr(self.memory, "close"):
            self.memory.close()

    def __enter__(self) -> "PlayerStatsClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_player_stats(self, owner_stats: int | None = None) -> dict[str, PlayerStatValue]:
        entries = self._resolve_stats_entries(owner_stats)
        stats: dict[str, PlayerStatValue] = {}

        for group in PLAYER_STAT_GROUPS:
            for spec in group:
                value = None
                if spec.offset is not None:
                    try:
                        value = self.memory.read_float(entries + spec.offset)
                    except MemoryReadError:
                        value = None
                stats[spec.label] = PlayerStatValue(spec=spec, value=value)

        return stats

    def get_passive_items(self, owner_stats: int | None = None) -> tuple[str, ...]:
        owner_stats = owner_stats or self._resolve_owner_stats()
        inventory_container = self.memory.read_ptr(owner_stats + self.INVENTORY_CONTAINER_OFFSET)
        passive_item_dict = self.memory.read_ptr(inventory_container + self.PASSIVE_ITEM_DICT_OFFSET) if inventory_container else 0
        if passive_item_dict:
            items = self._read_passive_item_dictionary(passive_item_dict)
            if items:
                return items

        player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
        item_inventory = self.memory.read_ptr(player_inventory + self.ITEM_INVENTORY_OFFSET) if player_inventory else 0
        passive_item_dict = (
            self.memory.read_ptr(item_inventory + self.ITEM_INVENTORY_ITEMS_DICT_OFFSET)
            if item_inventory
            else 0
        )
        if not passive_item_dict:
            return ()

        return self._read_passive_item_dictionary(passive_item_dict)

    def _read_passive_item_dictionary(self, passive_item_dict: int) -> tuple[str, ...]:
        entries = self.memory.read_ptr(passive_item_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return ()

        count = self.memory.read_i32(passive_item_dict + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return ()
        if count > self.MAX_PASSIVE_ITEM_DICT_ENTRIES:
            raise MemoryReadError(f"Passive item dictionary count is invalid: {count}")

        items: list[str] = []
        broken_entries = 0
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            try:
                item_value = self.memory.read_ptr(entry + self.DICT_ENTRY_VALUE_OFFSET)
                if not item_value:
                    continue

                class_meta = self.memory.read_ptr(item_value + self.ITEM_CLASS_META_OFFSET)
                name_ptr = self.memory.read_ptr(class_meta + self.CLASS_META_NAME_PTR_OFFSET) if class_meta else 0
                raw_name = self.memory.read_ascii_string(name_ptr) if name_ptr else None
                item_name = self._format_item_name(raw_name)
                if not item_name:
                    continue

                try:
                    stack_count = self.memory.read_i32(item_value + self.ITEM_STACK_COUNT_OFFSET)
                except MemoryReadError:
                    stack_count = 1
            except MemoryReadError:
                broken_entries += 1
                continue

            items.append(f"{item_name} x{max(1, stack_count)}")

        if count > 0 and not items and broken_entries:
            raise MemoryReadError("Passive item dictionary entries could not be decoded.")

        return tuple(items)

    def get_live_weapons(self, owner_stats: int | None = None) -> tuple[WeaponSnapshot, ...]:
        owner_stats = owner_stats or self._resolve_owner_stats()
        player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
        if not player_inventory:
            return ()

        weapon_inventory = self.memory.read_ptr(player_inventory + self.WEAPON_INVENTORY_OFFSET)
        if not weapon_inventory:
            return ()

        weapons_dict = self.memory.read_ptr(weapon_inventory + self.WEAPONS_DICT_OFFSET)
        if not weapons_dict:
            return ()

        entries = self.memory.read_ptr(weapons_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return ()

        count = self.memory.read_i32(weapons_dict + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return ()
        if count > self.MAX_WEAPON_DICT_ENTRIES:
            raise MemoryReadError(f"Weapon dictionary count is invalid: {count}")

        weapons: list[WeaponSnapshot] = []
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.WEAPON_DICT_ENTRY_SIZE)
            try:
                hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
                if hash_code < 0:
                    continue

                weapon_id = self.memory.read_i32(entry + self.WEAPON_DICT_ENTRY_KEY_OFFSET)
                weapon_base = self.memory.read_ptr(entry + self.WEAPON_DICT_ENTRY_VALUE_OFFSET)
                if not weapon_base:
                    continue

                snapshot = self._read_weapon_snapshot(weapon_id, weapon_base)
            except MemoryReadError:
                continue

            if snapshot is not None:
                weapons.append(snapshot)

        weapons.sort(key=lambda weapon: weapon.weapon_id)
        return tuple(weapons)

    def get_live_tomes(self, owner_stats: int | None = None) -> tuple[TomeSnapshot, ...]:
        owner_stats = owner_stats or self._resolve_owner_stats()
        try:
            player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
        except MemoryReadError:
            return ()
        if not player_inventory:
            return ()

        try:
            tome_inventory = self.memory.read_ptr(player_inventory + self.TOME_INVENTORY_OFFSET)
        except MemoryReadError:
            return ()
        if not tome_inventory:
            return ()

        tome_levels = self._read_tome_levels_dict(
            self.memory.read_ptr(tome_inventory + self.TOME_LEVELS_DICT_OFFSET)
        )
        tome_upgrades = self._read_tome_upgrades_dict(
            self.memory.read_ptr(tome_inventory + self.TOME_UPGRADES_DICT_OFFSET)
        )
        tome_ids = sorted(set(tome_levels) | set(tome_upgrades))
        snapshots: list[TomeSnapshot] = []
        for tome_id in tome_ids:
            upgrade = tome_upgrades.get(tome_id)
            if upgrade is None:
                stat_id = None
                stat_label = "No live upgrade decoded"
                value = None
                value_format = PlayerStatFormat.FLAT
            else:
                stat_id, stat_label, value, value_format = upgrade
            snapshots.append(
                TomeSnapshot(
                    tome_id=tome_id,
                    name=TOME_NAMES_BY_ID.get(tome_id, f"Tome {tome_id}"),
                    level=max(tome_levels.get(tome_id, 0), 0),
                    stat_id=stat_id,
                    stat_label=stat_label,
                    value=value,
                    value_format=value_format,
                )
            )
        return tuple(snapshots)

    def get_live_banishes(self) -> tuple[str, ...]:
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.RUN_UNLOCKABLES_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            return ()

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            return ()

        item_set = self.memory.read_ptr(static_fields + self.RUN_UNLOCKABLES_BANISHED_ITEMS_OFFSET)
        upgradable_set = self.memory.read_ptr(
            static_fields + self.RUN_UNLOCKABLES_BANISHED_UPGRADABLES_OFFSET
        )
        item_banishes = self._read_banished_items_set(item_set)
        upgradable_banishes = self._read_banished_upgradables_set(upgradable_set)
        return tuple(item_banishes + upgradable_banishes)

    def get_run_timer(self) -> float:
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.RUN_TIMER_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            raise MemoryReadError("Run timer type info is not initialized.")

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            raise MemoryReadError("Run timer static fields are not initialized.")

        return self.memory.read_float(static_fields + self.RUN_TIMER_OFFSET)

    def get_stage_timer(self) -> float:
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.RUN_TIMER_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            raise MemoryReadError("Stage timer type info is not initialized.")

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            raise MemoryReadError("Stage timer static fields are not initialized.")

        return self.memory.read_float(static_fields + self.STAGE_TIMER_OFFSET)

    def get_killed_mobs(self) -> int:
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.RUN_STATS_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            raise MemoryReadError("RunStats type info is not initialized.")

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            raise MemoryReadError("RunStats static fields are not initialized.")

        stats_dict = self.memory.read_ptr(static_fields + self.RUN_STATS_DICT_OFFSET)
        if not stats_dict:
            raise MemoryReadError("RunStats.stats dictionary is not initialized.")

        entries = self.memory.read_ptr(stats_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            raise MemoryReadError("RunStats.stats entries are not initialized.")

        count = self.memory.read_i32(stats_dict + self.DICT_COUNT_OFFSET)

        if count <= 0:
            return 0
        if count > self.MAX_RUN_STATS_ENTRIES:
            raise MemoryReadError(f"RunStats dictionary count is invalid: {count}")

        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            key_ptr = self.memory.read_ptr(entry + self.DICT_ENTRY_KEY_OFFSET)
            if not key_ptr:
                continue
            key = self.memory.read_mono_string(key_ptr)
            if key != "kills":
                continue
            return max(0, int(self.memory.read_float(entry + self.RUN_STATS_ENTRY_VALUE_OFFSET)))

        raise MemoryReadError("RunStats.stats does not contain a 'kills' entry.")

    def get_player_level(self, owner_stats: int | None = None) -> int:
        owner_stats = owner_stats or self._resolve_owner_stats()
        player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
        if not player_inventory:
            raise MemoryReadError("Player inventory is not initialized.")

        player_xp = self.memory.read_ptr(player_inventory + self.PLAYER_XP_OFFSET)
        if not player_xp:
            raise MemoryReadError("Player XP is not initialized.")

        return max(0, self.memory.read_i32(player_xp + self.PLAYER_XP_LEVEL_OFFSET))

    def resolve_owner_stats(self) -> int:
        return self._resolve_owner_stats()

    def _resolve_stats_entries(self, owner_stats: int | None = None) -> int:
        owner_stats = owner_stats or self._resolve_owner_stats()
        stats_context = self.memory.read_ptr(owner_stats + self.STATS_CONTEXT_OFFSET)
        entries = self.memory.read_ptr(stats_context + self.STATS_ENTRIES_OFFSET)
        if not entries:
            raise MemoryReadError("Player stats entries are not initialized.")

        return entries

    def _resolve_owner_stats(self) -> int:
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            raise MemoryReadError("Player stats type info is not initialized.")

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        root = self.memory.read_ptr(static_fields + self.STATIC_ROOT_OFFSET)
        owner_stats = self.memory.read_ptr(root + self.OWNER_STATS_OFFSET)
        if not owner_stats:
            raise MemoryReadError("Player stats owner is not initialized.")

        return owner_stats

    @staticmethod
    def _format_item_name(raw_name: str | None) -> str | None:
        if not raw_name:
            return None

        value = raw_name[4:] if raw_name.startswith("Item") and len(raw_name) > 4 else raw_name
        if value in ITEM_DISPLAY_NAME_BY_RAW_VALUE:
            return ITEM_DISPLAY_NAME_BY_RAW_VALUE[value]

        parts: list[str] = []
        current = ""
        for char in value:
            if char.isupper() and current and not current[-1].isupper():
                parts.append(current)
                current = char
            else:
                current += char
        if current:
            parts.append(current)

        return " ".join(parts) if parts else value

    def _read_weapon_snapshot(self, weapon_id: int, weapon_base: int) -> WeaponSnapshot | None:
        level = self.memory.read_i32(weapon_base + self.WEAPON_LEVEL_OFFSET)
        weapon_data = self.memory.read_ptr(weapon_base + self.WEAPON_DATA_OFFSET)
        weapon_stats_dict = self.memory.read_ptr(weapon_base + self.WEAPON_STATS_DICT_OFFSET)
        if not weapon_data or not weapon_stats_dict:
            return None

        try:
            resolved_weapon_id = self.memory.read_i32(weapon_data + self.WEAPON_ID_OFFSET)
            if resolved_weapon_id >= 0:
                weapon_id = resolved_weapon_id
        except MemoryReadError:
            pass

        full_stats = self._read_weapon_stats_dict(weapon_stats_dict)
        upgrade_data = self.memory.read_ptr(weapon_data + self.WEAPON_UPGRADE_DATA_OFFSET)
        upgrade_modifiers = self.memory.read_ptr(upgrade_data + self.UPGRADE_MODIFIERS_OFFSET) if upgrade_data else 0
        upgrade_stat_ids = self._read_upgrade_stat_ids(upgrade_modifiers)
        upgraded_stats = {
            stat_id: full_stats[stat_id]
            for stat_id in upgrade_stat_ids
            if stat_id in full_stats
        }

        return WeaponSnapshot(
            weapon_id=weapon_id,
            name=WEAPON_NAMES_BY_ID.get(weapon_id, f"Weapon {weapon_id}"),
            level=max(level, 0),
            upgrade_stat_ids=upgrade_stat_ids,
            upgraded_stats=upgraded_stats,
            full_stats=full_stats,
        )

    def _read_weapon_stats_dict(self, dictionary_address: int) -> dict[int, WeaponStatValue]:
        entries = self.memory.read_ptr(dictionary_address + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return {}

        count = self.memory.read_i32(dictionary_address + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return {}
        if count > self.MAX_WEAPON_STATS_ENTRIES:
            raise MemoryReadError(f"Weapon stats dictionary count is invalid: {count}")

        stats: dict[int, WeaponStatValue] = {}
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.STAT_DICT_ENTRY_SIZE)
            hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            stat_id = self.memory.read_i32(entry + self.STAT_DICT_ENTRY_KEY_OFFSET)
            value = self.memory.read_float(entry + self.STAT_DICT_ENTRY_VALUE_OFFSET)
            spec = WEAPON_STAT_SPECS.get(stat_id)
            if spec is None:
                spec = WeaponStatSpec(f"Stat {stat_id}", WeaponStatFormat.FLAT)
            stats[stat_id] = WeaponStatValue(
                stat_id=stat_id,
                label=spec.label,
                value=value,
                value_format=spec.value_format,
            )
        return stats

    def _read_tome_levels_dict(self, dictionary_address: int) -> dict[int, int]:
        if not dictionary_address:
            return {}

        entries = self.memory.read_ptr(dictionary_address + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return {}

        count = self.memory.read_i32(dictionary_address + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return {}
        if count > self.MAX_WEAPON_DICT_ENTRIES:
            raise MemoryReadError(f"Tome levels dictionary count is invalid: {count}")

        levels: dict[int, int] = {}
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.STAT_DICT_ENTRY_SIZE)
            hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            tome_id = self.memory.read_i32(entry + self.STAT_DICT_ENTRY_KEY_OFFSET)
            level = self.memory.read_i32(entry + self.STAT_DICT_ENTRY_VALUE_OFFSET)
            levels[tome_id] = level
        return levels

    def _read_tome_upgrades_dict(
        self,
        dictionary_address: int,
    ) -> dict[int, tuple[int, str, float | None, PlayerStatFormat]]:
        if not dictionary_address:
            return {}

        entries = self.memory.read_ptr(dictionary_address + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return {}

        count = self.memory.read_i32(dictionary_address + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return {}
        if count > self.MAX_WEAPON_DICT_ENTRIES:
            raise MemoryReadError(f"Tome upgrades dictionary count is invalid: {count}")

        upgrades: dict[int, tuple[int, str, float | None, PlayerStatFormat]] = {}
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            tome_id = self.memory.read_i32(entry + self.WEAPON_DICT_ENTRY_KEY_OFFSET)
            modifier_ptr = self.memory.read_ptr(entry + self.WEAPON_DICT_ENTRY_VALUE_OFFSET)
            if not modifier_ptr:
                continue
            stat_id = self.memory.read_i32(modifier_ptr + self.STAT_MODIFIER_STAT_OFFSET)
            value = self.memory.read_float(modifier_ptr + self.STAT_MODIFIER_VALUE_OFFSET)
            label, value_format = self._resolve_stat_display(stat_id)
            upgrades[tome_id] = (stat_id, label, value, value_format)
        return upgrades

    def _read_upgrade_stat_ids(self, list_address: int) -> tuple[int, ...]:
        if not list_address:
            return ()

        items_array = self.memory.read_ptr(list_address + self.LIST_ITEMS_OFFSET)
        if not items_array:
            return ()

        size = self.memory.read_i32(list_address + self.LIST_SIZE_OFFSET)
        if size <= 0:
            return ()
        if size > self.MAX_UPGRADE_MODIFIERS:
            raise MemoryReadError(f"Upgrade modifier list size is invalid: {size}")

        stat_ids: list[int] = []
        seen: set[int] = set()
        for index in range(size):
            modifier_ptr = self.memory.read_ptr(items_array + self.ARRAY_DATA_OFFSET + (index * self.OBJECT_POINTER_SIZE))
            if not modifier_ptr:
                continue
            stat_id = self.memory.read_i32(modifier_ptr + self.STAT_MODIFIER_STAT_OFFSET)
            if stat_id not in seen:
                seen.add(stat_id)
                stat_ids.append(stat_id)
        return tuple(stat_ids)

    def _read_banished_items_set(self, set_address: int) -> list[str]:
        values = self._read_hashset_object_values(set_address)
        banishes: list[str] = []
        for value in values:
            try:
                item_id = self.memory.read_i32(value + self.ITEM_DATA_ENUM_OFFSET)
            except MemoryReadError:
                continue
            raw_name = ITEM_ENUM_NAMES_BY_ID.get(item_id)
            if raw_name is None:
                banishes.append(f"Item {item_id}")
                continue
            display_name = self._format_item_name(f"Item{raw_name}") or raw_name
            banishes.append(display_name)
        return banishes

    def _read_banished_upgradables_set(self, set_address: int) -> list[str]:
        values = self._read_hashset_object_values(set_address)
        banishes: list[str] = []
        for value in values:
            try:
                klass = self.memory.read_ptr(value + self.OBJECT_KLASS_OFFSET)
                name_ptr = self.memory.read_ptr(klass + self.KLASS_NAME_PTR_OFFSET) if klass else 0
                class_name = self.memory.read_ascii_string(name_ptr) if name_ptr else None
            except MemoryReadError:
                class_name = None

            if class_name == "TomeData":
                try:
                    tome_id = self.memory.read_i32(value + self.TOME_DATA_ENUM_OFFSET)
                except MemoryReadError:
                    continue
                tome_name = TOME_NAMES_BY_ID.get(tome_id, f"Tome {tome_id}")
                banishes.append(f"{tome_name} Tome")
                continue

            if class_name:
                if class_name.endswith("Data"):
                    class_name = class_name[:-4]
                banishes.append(class_name)
        return banishes

    def _read_hashset_object_values(self, set_address: int) -> list[int]:
        if not set_address:
            return []

        slots = self.memory.read_ptr(set_address + self.HASHSET_SLOTS_OFFSET)
        if not slots:
            return []

        count = self.memory.read_i32(set_address + self.HASHSET_COUNT_OFFSET)
        if count <= 0:
            return []
        if count > self.MAX_BANISHED_UNLOCKABLES:
            raise MemoryReadError(f"HashSet count is invalid: {count}")

        last_index = self.memory.read_i32(set_address + self.HASHSET_LAST_INDEX_OFFSET)
        if last_index <= 0:
            return []
        if last_index > self.MAX_BANISHED_UNLOCKABLES:
            raise MemoryReadError(f"HashSet lastIndex is invalid: {last_index}")

        values: list[int] = []
        for index in range(last_index):
            slot = slots + self.HASHSET_SLOT_START_OFFSET + (index * self.HASHSET_SLOT_SIZE)
            hash_code = self.memory.read_i32(slot + self.HASHSET_SLOT_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            value = self.memory.read_ptr(slot + self.HASHSET_SLOT_VALUE_OFFSET)
            if value:
                values.append(value)
        return values

    @staticmethod
    def _resolve_stat_display(stat_id: int) -> tuple[str, PlayerStatFormat]:
        for group in PLAYER_STAT_GROUPS:
            for spec in group:
                if spec.stat_id == stat_id:
                    return spec.label, spec.value_format
        weapon_spec = WEAPON_STAT_SPECS.get(stat_id)
        if weapon_spec is not None:
            return weapon_spec.label, PlayerStatFormat(weapon_spec.value_format.value)
        return f"Stat {stat_id}", PlayerStatFormat.FLAT


def iter_player_stat_groups(
    stats: dict[str, PlayerStatValue],
) -> tuple[tuple[PlayerStatValue, ...], ...]:
    return tuple(
        tuple(stats[spec.label] for spec in group)
        for group in PLAYER_STAT_GROUPS
    )


def format_player_stat_value(value: float | None, value_format: PlayerStatFormat) -> str:
    if value is None or not isfinite(value):
        return "--"

    if value_format is PlayerStatFormat.PERCENT:
        return f"{_format_number(value * 100)}%"

    if value_format is PlayerStatFormat.MULTIPLIER:
        return f"{_format_number(value)}x"

    return _format_number(value)


def format_weapon_stat_value(value: float | None, value_format: WeaponStatFormat) -> str:
    if value is None or not isfinite(value):
        return "--"

    if value_format is WeaponStatFormat.PERCENT:
        return f"{_format_number(value * 100)}%"

    if value_format is WeaponStatFormat.MULTIPLIER:
        return f"{_format_number(value)}x"

    return _format_number(value)


def _format_number(value: float) -> str:
    if abs(value) < 0.0005:
        value = 0.0

    if abs(value - round(value)) < 0.005:
        return str(int(round(value)))

    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")

    return f"{value:.2f}".rstrip("0").rstrip(".")
