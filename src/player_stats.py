from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite, pi, sqrt
import time
from typing import Iterable, Protocol

from item_metadata import ITEM_DISPLAY_NAME_BY_RAW_VALUE, ITEM_ENUM_NAMES_BY_ID
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


PICKUP_RANGE_BASE_METERS = 9.0
CRIT_DAMAGE_BASE_MULTIPLIER = 2.0


class DisabledItemsReadStatus(Enum):
    AVAILABLE = "available"
    NOT_INITIALIZED = "not_initialized"
    READ_ERROR = "read_error"


class InvalidItemStackCountError(ValueError):
    """Raised when a transient item-object read cannot be trusted."""


@dataclass(frozen=True)
class DisabledItemsReadResult:
    status: DisabledItemsReadStatus
    items: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status is DisabledItemsReadStatus.AVAILABLE


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
class PlayerStatModifierSnapshot:
    stat_id: int
    label: str
    value: float | None
    value_format: PlayerStatFormat

    @property
    def display_delta(self) -> str:
        return format_player_stat_delta(self.value, self.value_format)


@dataclass(frozen=True)
class ChaosTomeStatSnapshot:
    stat_id: int
    label: str
    value: float | None
    value_format: PlayerStatFormat
    rolls: int = 0

    @property
    def display_delta(self) -> str:
        return format_chaos_tome_stat_delta(self.label, self.value, self.value_format)


@dataclass(frozen=True)
class ChaosTomeSnapshot:
    level: int
    stats: tuple[ChaosTomeStatSnapshot, ...] = ()
    ambiguous_rolls: int = 0

    @property
    def tracked_stat_count(self) -> int:
        return len(self.stats)


@dataclass(frozen=True)
class StatusEffectSnapshot:
    effect_id: int
    name: str
    added_time: float
    expiration_time: float


@dataclass(frozen=True)
class PowerupReadHealth:
    """Validity of one dependency used to build a powerup snapshot."""

    available: bool = True
    complete: bool = True
    failure_reason: str | None = None
    captured_at: float = 0.0
    source: str = "fast"


@dataclass(frozen=True)
class StatusEffectsReadResult:
    effects: tuple[StatusEffectSnapshot, ...] = ()
    health: PowerupReadHealth = field(default_factory=PowerupReadHealth)


@dataclass(frozen=True)
class PowerupTrackingSnapshot:
    my_time_seconds: float | None
    stage_timer_seconds: float | None
    stage_index: int | None
    stage_time_seconds: float | None
    powerup_multiplier: float | None
    powerup_multiplier_display: str
    final_swarm_timer_seconds: float | None = None
    crypt_timer_seconds: float | None = None
    effects: tuple[StatusEffectSnapshot, ...] = ()
    status_effects_health: PowerupReadHealth = field(default_factory=PowerupReadHealth)
    timing_health: PowerupReadHealth = field(default_factory=PowerupReadHealth)
    multiplier_health: PowerupReadHealth = field(default_factory=PowerupReadHealth)


@dataclass(frozen=True)
class PlayerStatSpec:
    label: str
    stat_id: int | None
    value_format: PlayerStatFormat
    display_scale: float = 1.0

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
        PlayerStatSpec("Crit Damage", 19, PlayerStatFormat.MULTIPLIER, display_scale=CRIT_DAMAGE_BASE_MULTIPLIER),
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
PLAYER_STAT_SPEC_BY_LABEL: dict[str, PlayerStatSpec] = {
    spec.label: spec
    for group in PLAYER_STAT_GROUPS
    for spec in group
}

POWERUP_STATUS_EFFECT_NAMES: dict[int, str] = {
    1: "Rage",
    2: "Shield",
    3: "Stonks",
    4: "Clock",
}
POWERUP_MULTIPLIER_LABEL = "Powerup Multiplier"
POWERUP_MULTIPLIER_CACHE_TTL_SECONDS = 5.0

@dataclass(frozen=True)
class PlayerStatValue:
    spec: PlayerStatSpec
    value: float | None

    @property
    def display_value(self) -> str:
        value = self.value
        if value is not None and isfinite(value):
            value *= self.spec.display_scale
        return format_player_stat_value(value, self.spec.value_format)


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


@dataclass(frozen=True)
class DamageSourceSnapshot:
    source_key: str
    source_name: str
    damage: float
    added_at_time: float | None = None


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
    damage_sources: tuple[DamageSourceSnapshot, ...] = ()
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
    MONEY_UTILITY_TYPE_INFO_OFFSET = 0x02F5E0B0
    MAP_CONTROLLER_TYPE_INFO_OFFSET = 0x02F58E08
    RUN_TIMER_TYPE_INFO_OFFSET = 0x02F62398
    RUN_STATS_TYPE_INFO_OFFSET = 0x02F7A170
    RUN_UNLOCKABLES_TYPE_INFO_OFFSET = 0x02F7A210
    DATA_MANAGER_TYPE_INFO_OFFSET = 0x02F85790
    POTATO_TYPE_INFO_OFFSET = 0x02F6FC78
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    STATIC_ROOT_OFFSET = 0x0
    OWNER_STATS_OFFSET = 0x40
    MY_TIME_TIME_OFFSET = 0x04
    STATS_CONTEXT_OFFSET = 0x10
    STATS_ENTRIES_OFFSET = 0x18
    STAGE_TIMER_OFFSET = 0x1C
    RUN_TIMER_OFFSET = 0x20
    FINAL_SWARM_TIMER_OFFSET = 0x24
    CRYPT_TIMER_OFFSET = 0x2C
    PLAYER_INVENTORY_OFFSET = 0x28
    PLAYER_STATUS_EFFECTS_OFFSET = 0x38
    PLAYER_STATUS_EFFECTS_DICT_OFFSET = 0x10
    WEAPON_INVENTORY_OFFSET = 0x28
    TOME_INVENTORY_OFFSET = 0x48
    STAT_INVENTORY_OFFSET = 0x50
    STAT_INVENTORY_PERMANENT_CHANGES_OFFSET = 0x10
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
    DICT_VERSION_OFFSET = 0x24
    DICT_ENTRY_START_OFFSET = 0x20
    DICT_ENTRY_SIZE = 0x18
    DICT_ENTRY_HASH_CODE_OFFSET = 0x0
    DICT_ENTRY_KEY_OFFSET = 0x8
    DICT_ENTRY_VALUE_OFFSET = 0x10
    STATUS_EFFECT_ESTATUS_OFFSET = 0x10
    STATUS_EFFECT_EXPIRATION_OFFSET = 0x20
    STATUS_EFFECT_ADDED_OFFSET = 0x24
    MAP_CONTROLLER_INDEX_OFFSET = 0x08
    MAP_CONTROLLER_CURRENT_STAGE_OFFSET = 0x18
    STAGE_DATA_TIMELINE_OFFSET = 0xD0
    STAGE_TIMELINE_STAGE_TIME_OFFSET = 0x10
    MAX_PASSIVE_ITEM_DICT_ENTRIES = 512
    MAX_PASSIVE_ITEM_STACK_COUNT = 1_000_000
    MAX_WEAPON_DICT_ENTRIES = 64
    MAX_WEAPON_STATS_ENTRIES = 128
    MAX_UPGRADE_MODIFIERS = 64
    ITEM_CLASS_META_OFFSET = 0x0
    ITEM_STACK_COUNT_OFFSET = 0x18
    CLASS_META_NAME_PTR_OFFSET = 0x10
    LIST_ITEMS_OFFSET = 0x10
    LIST_SIZE_OFFSET = 0x18
    LIST_VERSION_OFFSET = 0x1C
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
    STAT_MODIFIER_TYPE_OFFSET = 0x14
    STAT_MODIFIER_VALUE_OFFSET = 0x18
    RUN_STATS_DICT_OFFSET = 0x0
    RUN_STATS_ENTRY_VALUE_OFFSET = 0x10
    MAX_RUN_STATS_ENTRIES = 256
    MONEY_UTILITY_CHESTS_PURCHASED_OFFSET = 0x48
    RUN_DAMAGE_SOURCES_DICT_OFFSET = 0x8
    DAMAGE_SOURCE_NAME_OFFSET = 0x10
    DAMAGE_SOURCE_ADDED_AT_TIME_OFFSET = 0x18
    DAMAGE_SOURCE_DAMAGE_OFFSET = 0x1C
    MAX_DAMAGE_SOURCE_ENTRIES = 256
    MAX_PERMANENT_STAT_ENTRIES = 256
    MAX_PERMANENT_STAT_MODIFIERS = 2048
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
    CHAOS_TOME_ID = 24

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
        self._cached_chests_bought_dict = 0
        self._cached_chests_bought_entries = 0
        self._cached_chests_bought_version: int | None = None
        self._cached_chests_bought_address = 0
        self._cached_kills_dict = 0
        self._cached_kills_entries = 0
        self._cached_kills_version: int | None = None
        self._cached_kills_address = 0
        self._cached_key_dict = 0
        self._cached_key_entries = 0
        self._cached_key_version: int | None = None
        self._cached_key_stack_address = 0
        self._cached_chaos_level_dict = 0
        self._cached_chaos_level_entries = 0
        self._cached_chaos_level_version: int | None = None
        self._cached_chaos_level_address = 0
        self._cached_permanent_modifiers_dict = 0
        self._cached_permanent_modifiers_entries = 0
        self._cached_permanent_modifiers_count = 0
        self._cached_permanent_modifiers_version: int | None = None
        self._cached_chaos_tracking_level: int | None = None
        self._cached_permanent_modifier_lists: dict[
            int,
            tuple[int, int, int, int, tuple[int, ...]],
        ] = {}
        self._cached_stats_entries_owner_stats = 0
        self._cached_stats_entries = 0
        self._cached_powerup_multiplier_owner_stats = 0
        self._cached_powerup_multiplier_value: float | None = None
        self._cached_powerup_multiplier_display = "--"
        self._cached_powerup_multiplier_read_at = 0.0
        self._cached_my_time_static_fields = 0
        self._cached_map_controller_static_fields = 0
        self._cached_stage_pointer = 0
        self._cached_stage_timeline_pointer = 0
        self._cached_stage_index: int | None = None
        self._cached_status_effects_dict = 0
        self._cached_status_effects_entries = 0
        self._cached_status_effects_count = 0
        self._cached_status_effects_capacity = 0
        self._cached_status_effects_version: int | None = None
        self._cached_status_effect_value_addresses: dict[int, int] = {}
        self._cached_active_powerup_signature: tuple[int, ...] = ()

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

    def get_current_gold(self, owner_stats: int | None = None) -> int:
        owner_stats = owner_stats or self._resolve_owner_stats()
        try:
            player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
            if not player_inventory:
                return 0
            return self.memory.read_i32(player_inventory + 0x70)
        except MemoryReadError:
            return 0

    def get_passive_items(self, owner_stats: int | None = None) -> tuple[str, ...]:
        owner_stats = owner_stats or self._resolve_owner_stats()
        primary_error: InvalidItemStackCountError | None = None
        try:
            inventory_container = self.memory.read_ptr(owner_stats + self.INVENTORY_CONTAINER_OFFSET)
            passive_item_dict = (
                self.memory.read_ptr(inventory_container + self.PASSIVE_ITEM_DICT_OFFSET)
                if inventory_container
                else 0
            )
            if passive_item_dict:
                items = self._read_passive_item_dictionary(passive_item_dict)
                if items:
                    return items
        except InvalidItemStackCountError as exc:
            primary_error = exc
        except MemoryReadError:
            pass

        try:
            player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
            item_inventory = (
                self.memory.read_ptr(player_inventory + self.ITEM_INVENTORY_OFFSET)
                if player_inventory
                else 0
            )
            passive_item_dict = (
                self.memory.read_ptr(item_inventory + self.ITEM_INVENTORY_ITEMS_DICT_OFFSET)
                if item_inventory
                else 0
            )
        except MemoryReadError:
            if primary_error is not None:
                raise primary_error
            raise
        if not passive_item_dict:
            if primary_error is not None:
                raise primary_error
            return ()

        return self._read_passive_item_dictionary(passive_item_dict)

    def get_passive_item_count(
        self,
        item_name: str,
        owner_stats: int | None = None,
    ) -> int:
        owner_stats = owner_stats or self._resolve_owner_stats()
        dictionaries: list[int] = []

        try:
            inventory_container = self.memory.read_ptr(
                owner_stats + self.INVENTORY_CONTAINER_OFFSET
            )
            if inventory_container:
                dictionaries.append(
                    self.memory.read_ptr(
                        inventory_container + self.PASSIVE_ITEM_DICT_OFFSET
                    )
                )
        except MemoryReadError:
            pass

        try:
            player_inventory = self.memory.read_ptr(
                owner_stats + self.PLAYER_INVENTORY_OFFSET
            )
            item_inventory = (
                self.memory.read_ptr(
                    player_inventory + self.ITEM_INVENTORY_OFFSET
                )
                if player_inventory
                else 0
            )
            if item_inventory:
                dictionaries.append(
                    self.memory.read_ptr(
                        item_inventory + self.ITEM_INVENTORY_ITEMS_DICT_OFFSET
                    )
                )
        except MemoryReadError:
            pass

        for passive_item_dict in dict.fromkeys(dictionaries):
            if not passive_item_dict:
                continue
            count = self._read_passive_item_count(passive_item_dict, item_name)
            if count is not None:
                return count
        return 0

    def get_expected_chest_inputs(
        self,
        owner_stats: int | None = None,
    ) -> tuple[int, int]:
        """Read the two fast-changing Expected inputs using validated addresses."""
        owner_stats = owner_stats or self._resolve_owner_stats()
        return (
            self._get_cached_chests_bought(),
            self._get_cached_key_count(owner_stats),
        )

    def _get_cached_key_count(self, owner_stats: int) -> int:
        passive_item_dict = self._resolve_preferred_passive_item_dict(owner_stats)
        if not passive_item_dict:
            self._clear_cached_key_address()
            raise MemoryReadError("Passive item dictionary is not initialized.")

        entries = self.memory.read_ptr(passive_item_dict + self.DICT_ENTRIES_OFFSET)
        version = self.memory.read_i32(passive_item_dict + self.DICT_VERSION_OFFSET)
        cache_valid = (
            passive_item_dict == self._cached_key_dict
            and entries == self._cached_key_entries
            and version == self._cached_key_version
        )
        if not cache_valid:
            self._cached_key_dict = passive_item_dict
            self._cached_key_entries = entries
            self._cached_key_version = version
            self._cached_key_stack_address = self._find_passive_item_stack_address(
                passive_item_dict,
                "Key",
            )

        if not self._cached_key_stack_address:
            return 0
        try:
            return self._read_stable_item_stack_count(self._cached_key_stack_address)
        except (MemoryReadError, InvalidItemStackCountError):
            self._clear_cached_key_address()
            raise

    def _read_stable_item_stack_count(self, address: int) -> int:
        """Reject torn/stale item reads before they reach live or recorded snapshots."""
        first = self.memory.read_i32(address)
        second = self.memory.read_i32(address)
        if first != second or not 1 <= first <= self.MAX_PASSIVE_ITEM_STACK_COUNT:
            raise InvalidItemStackCountError(
                f"Passive item stack count is unstable or invalid: {first}, {second}"
            )
        return first

    def _resolve_preferred_passive_item_dict(self, owner_stats: int) -> int:
        try:
            inventory_container = self.memory.read_ptr(
                owner_stats + self.INVENTORY_CONTAINER_OFFSET
            )
            if inventory_container:
                passive_item_dict = self.memory.read_ptr(
                    inventory_container + self.PASSIVE_ITEM_DICT_OFFSET
                )
                if passive_item_dict:
                    return passive_item_dict
        except MemoryReadError:
            pass

        try:
            player_inventory = self.memory.read_ptr(
                owner_stats + self.PLAYER_INVENTORY_OFFSET
            )
            item_inventory = (
                self.memory.read_ptr(player_inventory + self.ITEM_INVENTORY_OFFSET)
                if player_inventory
                else 0
            )
            return (
                self.memory.read_ptr(
                    item_inventory + self.ITEM_INVENTORY_ITEMS_DICT_OFFSET
                )
                if item_inventory
                else 0
            )
        except MemoryReadError:
            return 0

    def _find_passive_item_stack_address(
        self,
        passive_item_dict: int,
        target_name: str,
    ) -> int:
        entries = self.memory.read_ptr(passive_item_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return 0
        count = self.memory.read_i32(passive_item_dict + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return 0
        if count > self.MAX_PASSIVE_ITEM_DICT_ENTRIES:
            raise MemoryReadError(f"Passive item dictionary count is invalid: {count}")

        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            try:
                item_value = self.memory.read_ptr(entry + self.DICT_ENTRY_VALUE_OFFSET)
                class_meta = (
                    self.memory.read_ptr(item_value + self.ITEM_CLASS_META_OFFSET)
                    if item_value
                    else 0
                )
                name_ptr = (
                    self.memory.read_ptr(class_meta + self.CLASS_META_NAME_PTR_OFFSET)
                    if class_meta
                    else 0
                )
                raw_name = self.memory.read_ascii_string(name_ptr) if name_ptr else None
                if self._format_item_name(raw_name) == target_name:
                    return item_value + self.ITEM_STACK_COUNT_OFFSET
            except MemoryReadError:
                continue
        return 0

    def _clear_cached_key_address(self) -> None:
        self._cached_key_dict = 0
        self._cached_key_entries = 0
        self._cached_key_version = None
        self._cached_key_stack_address = 0

    def _read_passive_item_count(
        self,
        passive_item_dict: int,
        target_name: str,
    ) -> int | None:
        entries = self.memory.read_ptr(passive_item_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return None

        count = self.memory.read_i32(passive_item_dict + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return 0
        if count > self.MAX_PASSIVE_ITEM_DICT_ENTRIES:
            raise MemoryReadError(f"Passive item dictionary count is invalid: {count}")

        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            try:
                item_value = self.memory.read_ptr(entry + self.DICT_ENTRY_VALUE_OFFSET)
                if not item_value:
                    continue
                class_meta = self.memory.read_ptr(item_value + self.ITEM_CLASS_META_OFFSET)
                name_ptr = (
                    self.memory.read_ptr(class_meta + self.CLASS_META_NAME_PTR_OFFSET)
                    if class_meta
                    else 0
                )
                raw_name = self.memory.read_ascii_string(name_ptr) if name_ptr else None
                if self._format_item_name(raw_name) != target_name:
                    continue
                try:
                    stack_count = self._read_stable_item_stack_count(
                        item_value + self.ITEM_STACK_COUNT_OFFSET
                    )
                except MemoryReadError:
                    stack_count = 1
                return max(1, stack_count)
            except MemoryReadError:
                continue
        return 0

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

                try:
                    item_id = self.memory.read_i32(entry + self.DICT_ENTRY_KEY_OFFSET)
                    enum_name = ITEM_ENUM_NAMES_BY_ID.get(item_id)
                except MemoryReadError:
                    enum_name = None

                if enum_name:
                    item_name = self._format_item_name(f"Item{enum_name}")
                else:
                    class_meta = self.memory.read_ptr(item_value + self.ITEM_CLASS_META_OFFSET)
                    name_ptr = self.memory.read_ptr(class_meta + self.CLASS_META_NAME_PTR_OFFSET) if class_meta else 0
                    raw_name = self.memory.read_ascii_string(name_ptr) if name_ptr else None
                    item_name = self._format_item_name(raw_name)

                if not item_name:
                    continue

                try:
                    stack_count = self._read_stable_item_stack_count(
                        item_value + self.ITEM_STACK_COUNT_OFFSET
                    )
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
        tome_inventory = self._resolve_tome_inventory(owner_stats)
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

    def _resolve_tome_inventory(self, owner_stats: int) -> int:
        try:
            player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
        except MemoryReadError:
            return 0
        if not player_inventory:
            return 0

        try:
            tome_inventory = self.memory.read_ptr(player_inventory + self.TOME_INVENTORY_OFFSET)
        except MemoryReadError:
            return 0
        return tome_inventory

    def _read_live_tome_levels(self, owner_stats: int | None = None) -> dict[int, int]:
        owner_stats = owner_stats or self._resolve_owner_stats()
        tome_inventory = self._resolve_tome_inventory(owner_stats)
        if not tome_inventory:
            return {}
        return self._read_tome_levels_dict(
            self.memory.read_ptr(tome_inventory + self.TOME_LEVELS_DICT_OFFSET)
        )

    def get_chaos_tome_level(self, owner_stats: int | None = None) -> int | None:
        levels = self._read_live_tome_levels(owner_stats)
        level = levels.get(self.CHAOS_TOME_ID)
        if level is None:
            return None
        return max(int(level), 0)

    def get_chaos_tracking_state(
        self,
        owner_stats: int | None = None,
    ) -> tuple[int | None, dict[int, tuple[PlayerStatModifierSnapshot, ...]]]:
        """Read Chaos Tome state through validated cached container addresses."""
        owner_stats = owner_stats or self._resolve_owner_stats()
        player_inventory = self.memory.read_ptr(
            owner_stats + self.PLAYER_INVENTORY_OFFSET
        )
        if not player_inventory:
            self._clear_chaos_tracking_cache()
            return None, {}

        chaos_level = self._get_cached_chaos_tome_level(player_inventory)
        if chaos_level is None:
            self._clear_cached_permanent_modifiers()
            self._cached_chaos_tracking_level = None
            return None, {}
        force_modifier_rescan = (
            self._cached_chaos_tracking_level is not None
            and chaos_level > self._cached_chaos_tracking_level
        )
        self._cached_chaos_tracking_level = chaos_level
        return chaos_level, self._get_cached_permanent_stat_modifiers(
            player_inventory,
            force_rescan=force_modifier_rescan,
        )

    def _get_cached_chaos_tome_level(self, player_inventory: int) -> int | None:
        tome_inventory = self.memory.read_ptr(
            player_inventory + self.TOME_INVENTORY_OFFSET
        )
        if not tome_inventory:
            self._clear_cached_chaos_level()
            return None
        levels_dict = self.memory.read_ptr(
            tome_inventory + self.TOME_LEVELS_DICT_OFFSET
        )
        if not levels_dict:
            self._clear_cached_chaos_level()
            return None

        entries = self.memory.read_ptr(levels_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            self._clear_cached_chaos_level()
            return None
        version = self.memory.read_i32(levels_dict + self.DICT_VERSION_OFFSET)
        if (
            levels_dict != self._cached_chaos_level_dict
            or entries != self._cached_chaos_level_entries
            # Keep retrying while the entry is unresolved: dictionary version can
            # advance before its entry array/count is fully visible to this read.
            or not self._cached_chaos_level_address
        ):
            self._cached_chaos_level_dict = levels_dict
            self._cached_chaos_level_entries = entries
            self._cached_chaos_level_version = version
            self._cached_chaos_level_address = self._find_tome_level_address(
                levels_dict,
                self.CHAOS_TOME_ID,
            )

        if not self._cached_chaos_level_address:
            return None
        return max(0, self.memory.read_i32(self._cached_chaos_level_address))

    def _find_tome_level_address(self, levels_dict: int, target_tome_id: int) -> int:
        entries = self.memory.read_ptr(levels_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return 0
        count = self.memory.read_i32(levels_dict + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return 0
        if count > self.MAX_WEAPON_DICT_ENTRIES:
            raise MemoryReadError(f"Tome levels dictionary count is invalid: {count}")

        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.STAT_DICT_ENTRY_SIZE)
            if self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET) < 0:
                continue
            tome_id = self.memory.read_i32(entry + self.STAT_DICT_ENTRY_KEY_OFFSET)
            if tome_id == target_tome_id:
                return entry + self.STAT_DICT_ENTRY_VALUE_OFFSET
        return 0

    def _get_cached_permanent_stat_modifiers(
        self,
        player_inventory: int,
        *,
        force_rescan: bool = False,
    ) -> dict[int, tuple[PlayerStatModifierSnapshot, ...]]:
        stat_inventory = self.memory.read_ptr(
            player_inventory + self.STAT_INVENTORY_OFFSET
        )
        if not stat_inventory:
            self._clear_cached_permanent_modifiers()
            return {}
        dictionary_address = self.memory.read_ptr(
            stat_inventory + self.STAT_INVENTORY_PERMANENT_CHANGES_OFFSET
        )
        if not dictionary_address:
            self._clear_cached_permanent_modifiers()
            return {}

        entries = self.memory.read_ptr(dictionary_address + self.DICT_ENTRIES_OFFSET)
        if not entries:
            self._clear_cached_permanent_modifiers()
            return {}
        count = self.memory.read_i32(dictionary_address + self.DICT_COUNT_OFFSET)
        if count <= 0:
            self._clear_cached_permanent_modifiers()
            return {}
        if count > self.MAX_PERMANENT_STAT_ENTRIES:
            raise MemoryReadError(f"Permanent stat dictionary count is invalid: {count}")
        version = self.memory.read_i32(dictionary_address + self.DICT_VERSION_OFFSET)
        if (
            force_rescan
            or dictionary_address != self._cached_permanent_modifiers_dict
            or entries != self._cached_permanent_modifiers_entries
            or count != self._cached_permanent_modifiers_count
            or version != self._cached_permanent_modifiers_version
        ):
            self._cached_permanent_modifiers_dict = dictionary_address
            self._cached_permanent_modifiers_entries = entries
            self._cached_permanent_modifiers_count = count
            self._cached_permanent_modifiers_version = version
            self._cached_permanent_modifier_lists = (
                self._find_permanent_modifier_lists(dictionary_address, count=count)
            )

        result: dict[int, tuple[PlayerStatModifierSnapshot, ...]] = {}
        for stat_id, cached_list in tuple(
            self._cached_permanent_modifier_lists.items()
        ):
            list_address, old_items, old_size, old_version, modifier_ptrs = cached_list
            items_array = self.memory.read_ptr(list_address + self.LIST_ITEMS_OFFSET)
            size = self.memory.read_i32(list_address + self.LIST_SIZE_OFFSET)
            list_version = self.memory.read_i32(list_address + self.LIST_VERSION_OFFSET)
            if size < 0 or size > self.MAX_PERMANENT_STAT_MODIFIERS:
                raise MemoryReadError(f"Permanent stat modifier list size is invalid: {size}")
            if (
                items_array != old_items
                or size != old_size
                or list_version != old_version
            ):
                modifier_ptrs = self._find_stat_modifier_ptrs(
                    items_array,
                    size,
                    expected_stat_id=stat_id,
                )
                self._cached_permanent_modifier_lists[stat_id] = (
                    list_address,
                    items_array,
                    size,
                    list_version,
                    modifier_ptrs,
                )

            modifiers = tuple(
                self._read_cached_stat_modifier(stat_id, modifier_ptr)
                for modifier_ptr in modifier_ptrs
            )
            if modifiers:
                result[stat_id] = modifiers
        return result

    def _find_permanent_modifier_lists(
        self,
        dictionary_address: int,
        *,
        count: int | None = None,
    ) -> dict[int, tuple[int, int, int, int, tuple[int, ...]]]:
        entries = self.memory.read_ptr(dictionary_address + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return {}
        if count is None:
            count = self.memory.read_i32(dictionary_address + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return {}
        if count > self.MAX_PERMANENT_STAT_ENTRIES:
            raise MemoryReadError(f"Permanent stat dictionary count is invalid: {count}")

        lists: dict[int, tuple[int, int, int, int, tuple[int, ...]]] = {}
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            if self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET) < 0:
                continue
            stat_id = self.memory.read_i32(entry + self.WEAPON_DICT_ENTRY_KEY_OFFSET)
            list_address = self.memory.read_ptr(entry + self.WEAPON_DICT_ENTRY_VALUE_OFFSET)
            if not list_address:
                continue
            items_array = self.memory.read_ptr(list_address + self.LIST_ITEMS_OFFSET)
            size = self.memory.read_i32(list_address + self.LIST_SIZE_OFFSET)
            list_version = self.memory.read_i32(list_address + self.LIST_VERSION_OFFSET)
            if size < 0 or size > self.MAX_PERMANENT_STAT_MODIFIERS:
                raise MemoryReadError(f"Permanent stat modifier list size is invalid: {size}")
            modifier_ptrs = self._find_stat_modifier_ptrs(
                items_array,
                size,
                expected_stat_id=stat_id,
            )
            lists[stat_id] = (
                list_address,
                items_array,
                size,
                list_version,
                modifier_ptrs,
            )
        return lists

    def _find_stat_modifier_ptrs(
        self,
        items_array: int,
        size: int,
        *,
        expected_stat_id: int,
    ) -> tuple[int, ...]:
        if not items_array or size <= 0:
            return ()
        modifier_ptrs: list[int] = []
        for index in range(size):
            modifier_ptr = self.memory.read_ptr(
                items_array + self.ARRAY_DATA_OFFSET + (index * self.OBJECT_POINTER_SIZE)
            )
            if not modifier_ptr:
                continue
            if self.memory.read_i32(
                modifier_ptr + self.STAT_MODIFIER_STAT_OFFSET
            ) == expected_stat_id:
                modifier_ptrs.append(modifier_ptr)
        return tuple(modifier_ptrs)

    def _read_cached_stat_modifier(
        self,
        stat_id: int,
        modifier_ptr: int,
    ) -> PlayerStatModifierSnapshot:
        value = self.memory.read_float(modifier_ptr + self.STAT_MODIFIER_VALUE_OFFSET)
        label, value_format = self._resolve_stat_display(stat_id)
        return PlayerStatModifierSnapshot(
            stat_id=stat_id,
            label=label,
            value=value,
            value_format=value_format,
        )

    def _clear_cached_chaos_level(self) -> None:
        self._cached_chaos_level_dict = 0
        self._cached_chaos_level_entries = 0
        self._cached_chaos_level_version = None
        self._cached_chaos_level_address = 0

    def _clear_cached_permanent_modifiers(self) -> None:
        self._cached_permanent_modifiers_dict = 0
        self._cached_permanent_modifiers_entries = 0
        self._cached_permanent_modifiers_count = 0
        self._cached_permanent_modifiers_version = None
        self._cached_permanent_modifier_lists = {}

    def _clear_chaos_tracking_cache(self) -> None:
        self._clear_cached_chaos_level()
        self._cached_chaos_tracking_level = None
        self._clear_cached_permanent_modifiers()

    def get_permanent_stat_modifiers(
        self,
        owner_stats: int | None = None,
    ) -> dict[int, tuple[PlayerStatModifierSnapshot, ...]]:
        owner_stats = owner_stats or self._resolve_owner_stats()
        player_inventory = self.memory.read_ptr(owner_stats + self.PLAYER_INVENTORY_OFFSET)
        if not player_inventory:
            return {}
        stat_inventory = self.memory.read_ptr(player_inventory + self.STAT_INVENTORY_OFFSET)
        if not stat_inventory:
            return {}
        dictionary_address = self.memory.read_ptr(
            stat_inventory + self.STAT_INVENTORY_PERMANENT_CHANGES_OFFSET
        )
        return self._read_permanent_stat_modifiers_dict(dictionary_address)

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

    def get_my_time_seconds(self) -> float:
        static_fields = self._resolve_my_time_static_fields()
        return self.memory.read_float(static_fields + self.MY_TIME_TIME_OFFSET)

    def get_stage_timer_context(self) -> tuple[float, int | None, float | None]:
        my_time_static_fields = self._resolve_my_time_static_fields()
        stage_timer = self.memory.read_float(
            my_time_static_fields + self.STAGE_TIMER_OFFSET
        )
        stage_index, _stage_time_marker = self._read_current_stage_time()
        # CurrentStage.Timeline.stageTime is an elapsed/position marker used
        # for transition detection, not the total duration of the event stage.
        # Keep the fast timer context explicit about the schedule duration.
        stage_duration = {
            0: 600.0,
            1: 540.0,
            2: 480.0,
        }.get(stage_index)
        return stage_timer, stage_index, stage_duration

    def get_powerup_tracking_snapshot(
        self,
        owner_stats: int | None = None,
    ) -> PowerupTrackingSnapshot:
        owner_stats = owner_stats or self._resolve_owner_stats()
        captured_at = time.monotonic()
        timing_health = PowerupReadHealth(captured_at=captured_at)
        try:
            my_time_static_fields = self._resolve_my_time_static_fields()
        except MemoryReadError:
            my_time_static_fields = 0
            timing_health = PowerupReadHealth(
                available=False,
                complete=False,
                failure_reason="powerup_timing_unavailable",
                captured_at=captured_at,
            )
        try:
            if not my_time_static_fields:
                raise MemoryReadError("MyTime static fields are not initialized.")
            my_time_seconds = self.memory.read_float(my_time_static_fields + self.MY_TIME_TIME_OFFSET)
            stage_timer_seconds = self.memory.read_float(my_time_static_fields + self.STAGE_TIMER_OFFSET)
        except MemoryReadError:
            self._clear_my_time_cache()
            my_time_seconds = None
            stage_timer_seconds = None
            timing_health = PowerupReadHealth(
                available=False,
                complete=False,
                failure_reason="powerup_timing_unavailable",
                captured_at=captured_at,
            )
        if my_time_static_fields:
            try:
                final_swarm_timer_seconds = self.memory.read_float(
                    my_time_static_fields + self.FINAL_SWARM_TIMER_OFFSET
                )
            except MemoryReadError:
                final_swarm_timer_seconds = None
            try:
                crypt_timer_seconds = self.memory.read_float(
                    my_time_static_fields + self.CRYPT_TIMER_OFFSET
                )
            except MemoryReadError:
                crypt_timer_seconds = None
        else:
            final_swarm_timer_seconds = None
            crypt_timer_seconds = None
        try:
            stage_index, stage_time_seconds = self._read_current_stage_time()
        except MemoryReadError:
            stage_index, stage_time_seconds = None, None

        status_effects_result = self._read_active_status_effects(
            owner_stats,
            captured_at=captured_at,
        )
        effects = status_effects_result.effects
        active_signature = tuple(
            sorted(
                effect.effect_id
                for effect in effects
                if my_time_seconds is not None
                if isfinite(effect.expiration_time)
                and (effect.expiration_time - my_time_seconds) > 0
            )
        )
        force_multiplier_refresh = bool(
            active_signature
            and active_signature != self._cached_active_powerup_signature
        )
        powerup_multiplier, powerup_multiplier_display = (
            self._get_cached_powerup_multiplier(
                owner_stats,
                force_refresh=force_multiplier_refresh,
                now=captured_at,
            )
        )
        multiplier_health = PowerupReadHealth(captured_at=captured_at)
        if powerup_multiplier is None or not isfinite(powerup_multiplier):
            multiplier_health = PowerupReadHealth(
                available=False,
                complete=False,
                failure_reason="powerup_multiplier_unavailable",
                captured_at=captured_at,
            )
        self._cached_active_powerup_signature = active_signature
        return PowerupTrackingSnapshot(
            my_time_seconds=my_time_seconds,
            stage_timer_seconds=stage_timer_seconds,
            stage_index=stage_index,
            stage_time_seconds=stage_time_seconds,
            powerup_multiplier=powerup_multiplier,
            powerup_multiplier_display=powerup_multiplier_display,
            final_swarm_timer_seconds=final_swarm_timer_seconds,
            crypt_timer_seconds=crypt_timer_seconds,
            effects=effects,
            status_effects_health=status_effects_result.health,
            timing_health=timing_health,
            multiplier_health=multiplier_health,
        )

    def get_active_status_effects(
        self,
        owner_stats: int | None = None,
    ) -> tuple[StatusEffectSnapshot, ...]:
        return self._read_active_status_effects(owner_stats).effects

    def _read_active_status_effects(
        self,
        owner_stats: int | None = None,
        *,
        captured_at: float | None = None,
    ) -> StatusEffectsReadResult:
        owner_stats = owner_stats or self._resolve_owner_stats()
        if captured_at is None:
            captured_at = time.monotonic()

        def unavailable() -> StatusEffectsReadResult:
            self._clear_status_effects_cache()
            return StatusEffectsReadResult(
                health=PowerupReadHealth(
                    available=False,
                    complete=False,
                    failure_reason="status_effects_unavailable",
                    captured_at=captured_at,
                )
            )

        def partial() -> StatusEffectsReadResult:
            self._clear_status_effects_cache()
            return StatusEffectsReadResult(
                health=PowerupReadHealth(
                    available=False,
                    complete=False,
                    failure_reason="status_effects_partial",
                    captured_at=captured_at,
                )
            )

        try:
            player_inventory = self.memory.read_ptr(
                owner_stats + self.PLAYER_INVENTORY_OFFSET
            )
        except MemoryReadError:
            return unavailable()
        if not player_inventory:
            return unavailable()
        try:
            status_effects = self.memory.read_ptr(
                player_inventory + self.PLAYER_STATUS_EFFECTS_OFFSET
            )
        except MemoryReadError:
            return unavailable()
        if not status_effects:
            return unavailable()
        try:
            dictionary_address = self.memory.read_ptr(
                status_effects + self.PLAYER_STATUS_EFFECTS_DICT_OFFSET
            )
        except MemoryReadError:
            return unavailable()
        if not dictionary_address:
            return unavailable()

        try:
            entries = self.memory.read_ptr(dictionary_address + self.DICT_ENTRIES_OFFSET)
        except MemoryReadError:
            return unavailable()
        if not entries:
            return unavailable()
        try:
            count = self.memory.read_i32(dictionary_address + self.DICT_COUNT_OFFSET)
        except MemoryReadError:
            return partial()
        if count < 0 or count > 128:
            return partial()
        try:
            capacity = self.memory.read_i32(entries + self.ARRAY_LENGTH_OFFSET)
        except MemoryReadError:
            return partial()
        if capacity <= 0 or capacity > 128:
            return partial()
        try:
            version = self.memory.read_i32(dictionary_address + self.DICT_VERSION_OFFSET)
        except MemoryReadError:
            version = None
        if (
            dictionary_address != self._cached_status_effects_dict
            or entries != self._cached_status_effects_entries
            or count != self._cached_status_effects_count
            or capacity != self._cached_status_effects_capacity
            or version != self._cached_status_effects_version
        ):
            self._cached_status_effects_dict = dictionary_address
            self._cached_status_effects_entries = entries
            self._cached_status_effects_count = count
            self._cached_status_effects_capacity = capacity
            self._cached_status_effects_version = version

        # Unity can reuse a Dictionary entry for another EStatusEffect without
        # changing count, capacity, or version (for example Invulnerability 5
        # becoming TimeFreeze 4 after a death). Refresh the key-to-value map on
        # every fast poll so a supported effect cannot stay invisible behind a
        # stale slot cache.
        self._cached_status_effect_value_addresses, scan_partial = self._scan_status_effect_value_addresses(
            entries,
            capacity,
        )

        effects: list[StatusEffectSnapshot] = []
        entry_partial = scan_partial
        for effect_id, value_address in tuple(self._cached_status_effect_value_addresses.items()):
            try:
                effect_ptr = self.memory.read_ptr(value_address)
                if not effect_ptr:
                    continue
                object_effect_id = self.memory.read_i32(
                    effect_ptr + self.STATUS_EFFECT_ESTATUS_OFFSET
                )
                expiration_time = self.memory.read_float(
                    effect_ptr + self.STATUS_EFFECT_EXPIRATION_OFFSET
                )
                added_time = self.memory.read_float(
                    effect_ptr + self.STATUS_EFFECT_ADDED_OFFSET
                )
            except MemoryReadError:
                entry_partial = True
                continue
            if object_effect_id not in POWERUP_STATUS_EFFECT_NAMES:
                entry_partial = True
                continue
            effects.append(
                StatusEffectSnapshot(
                    effect_id=object_effect_id,
                    name=POWERUP_STATUS_EFFECT_NAMES[object_effect_id],
                    added_time=added_time,
                    expiration_time=expiration_time,
                )
            )
        health = PowerupReadHealth(captured_at=captured_at)
        if entry_partial:
            health = PowerupReadHealth(
                available=True,
                complete=False,
                failure_reason="status_effects_partial",
                captured_at=captured_at,
            )
        return StatusEffectsReadResult(
            effects=tuple(sorted(effects, key=lambda effect: effect.effect_id)),
            health=health,
        )

    def get_run_stat_values(self, keys: Iterable[str]) -> dict[str, float]:
        requested = frozenset(str(key) for key in keys)
        if not requested:
            return {}

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
            return {}
        if count > self.MAX_RUN_STATS_ENTRIES:
            raise MemoryReadError(f"RunStats dictionary count is invalid: {count}")

        values: dict[str, float] = {}
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            key_ptr = self.memory.read_ptr(entry + self.DICT_ENTRY_KEY_OFFSET)
            if not key_ptr:
                continue
            key = self.memory.read_mono_string(key_ptr)
            if key not in requested:
                continue
            values[key] = self.memory.read_float(entry + self.RUN_STATS_ENTRY_VALUE_OFFSET)
            if len(values) == len(requested):
                break

        return values

    def get_killed_mobs(self) -> int:
        return self._get_cached_killed_mobs()

    def get_chest_counters(self) -> tuple[int, int]:
        chests_bought = self.get_chests_bought()

        type_info_address = self.memory.module_offset(
            self.module_name,
            self.MONEY_UTILITY_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            raise MemoryReadError("MoneyUtility type info is not initialized.")

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            raise MemoryReadError("MoneyUtility static fields are not initialized.")

        chests_purchased = max(
            0,
            self.memory.read_i32(
                static_fields + self.MONEY_UTILITY_CHESTS_PURCHASED_OFFSET
            ),
        )
        return chests_bought, chests_purchased

    def get_chests_bought(self) -> int:
        run_stats = self.get_run_stat_values(("chestsBought",))
        return max(0, int(run_stats.get("chestsBought", 0.0)))

    def _get_cached_chests_bought(self) -> int:
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
        version = self.memory.read_i32(stats_dict + self.DICT_VERSION_OFFSET)

        if (
            stats_dict != self._cached_chests_bought_dict
            or entries != self._cached_chests_bought_entries
            or version != self._cached_chests_bought_version
        ):
            self._cached_chests_bought_dict = stats_dict
            self._cached_chests_bought_entries = entries
            self._cached_chests_bought_version = version
            self._cached_chests_bought_address = self._find_run_stat_value_address(
                stats_dict,
                "chestsBought",
            )

        if not self._cached_chests_bought_address:
            return 0
        return max(0, int(self.memory.read_float(self._cached_chests_bought_address)))

    def _get_cached_killed_mobs(self) -> int:
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
        version = self.memory.read_i32(stats_dict + self.DICT_VERSION_OFFSET)

        if (
            stats_dict != self._cached_kills_dict
            or entries != self._cached_kills_entries
            or version != self._cached_kills_version
        ):
            self._cached_kills_dict = stats_dict
            self._cached_kills_entries = entries
            self._cached_kills_version = version
            self._cached_kills_address = self._find_run_stat_value_address(
                stats_dict,
                "kills",
            )

        if not self._cached_kills_address:
            raise MemoryReadError("RunStats.stats does not contain a 'kills' entry.")
        return max(0, int(self.memory.read_float(self._cached_kills_address)))

    def _find_run_stat_value_address(self, stats_dict: int, target_key: str) -> int:
        entries = self.memory.read_ptr(stats_dict + self.DICT_ENTRIES_OFFSET)
        count = self.memory.read_i32(stats_dict + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return 0
        if count > self.MAX_RUN_STATS_ENTRIES:
            raise MemoryReadError(f"RunStats dictionary count is invalid: {count}")

        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            if self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET) < 0:
                continue
            key_ptr = self.memory.read_ptr(entry + self.DICT_ENTRY_KEY_OFFSET)
            if key_ptr and self.memory.read_mono_string(key_ptr) == target_key:
                return entry + self.RUN_STATS_ENTRY_VALUE_OFFSET
        return 0

    def get_live_damage_sources(self) -> tuple[DamageSourceSnapshot, ...]:
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

        damage_sources_dict = self.memory.read_ptr(static_fields + self.RUN_DAMAGE_SOURCES_DICT_OFFSET)
        if not damage_sources_dict:
            return ()

        entries = self.memory.read_ptr(damage_sources_dict + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return ()

        count = self.memory.read_i32(damage_sources_dict + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return ()
        if count > self.MAX_DAMAGE_SOURCE_ENTRIES:
            raise MemoryReadError(f"RunStats.damageSources count is invalid: {count}")

        sources: list[DamageSourceSnapshot] = []
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            key_ptr = self.memory.read_ptr(entry + self.DICT_ENTRY_KEY_OFFSET)
            value_ptr = self.memory.read_ptr(entry + self.DICT_ENTRY_VALUE_OFFSET)
            if not key_ptr or not value_ptr:
                continue
            key = self.memory.read_mono_string(key_ptr)
            if not key:
                continue
            damage_source_name_ptr = self.memory.read_ptr(value_ptr + self.DAMAGE_SOURCE_NAME_OFFSET)
            damage_source_name = self.memory.read_mono_string(damage_source_name_ptr) if damage_source_name_ptr else None
            added_at_time = self.memory.read_float(value_ptr + self.DAMAGE_SOURCE_ADDED_AT_TIME_OFFSET)
            damage = self.memory.read_float(value_ptr + self.DAMAGE_SOURCE_DAMAGE_OFFSET)
            sources.append(
                DamageSourceSnapshot(
                    source_key=key,
                    source_name=damage_source_name or key,
                    damage=max(0.0, float(damage)),
                    added_at_time=float(added_at_time),
                )
            )

        sources.sort(key=lambda source: source.damage, reverse=True)
        return tuple(sources)

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

    def _resolve_my_time_static_fields(self) -> int:
        if self._cached_my_time_static_fields:
            return self._cached_my_time_static_fields
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.RUN_TIMER_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            raise MemoryReadError("MyTime type info is not initialized.")

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            raise MemoryReadError("MyTime static fields are not initialized.")
        self._cached_my_time_static_fields = static_fields
        return static_fields

    def _read_current_stage_time(self) -> tuple[int | None, float | None]:
        static_fields = self._resolve_map_controller_static_fields()
        if not static_fields:
            return None, None

        stage_index: int | None = None
        try:
            stage_index = self.memory.read_i32(
                static_fields + self.MAP_CONTROLLER_INDEX_OFFSET
            )
        except MemoryReadError:
            stage_index = None

        stage_time: float | None = None
        try:
            current_stage = self.memory.read_ptr(
                static_fields + self.MAP_CONTROLLER_CURRENT_STAGE_OFFSET
            )
            if not current_stage:
                self._cached_stage_pointer = 0
                self._cached_stage_timeline_pointer = 0
            elif current_stage != self._cached_stage_pointer:
                self._cached_stage_pointer = current_stage
                self._cached_stage_timeline_pointer = self.memory.read_ptr(
                    current_stage + self.STAGE_DATA_TIMELINE_OFFSET
                )
            timeline = self._cached_stage_timeline_pointer
            if timeline:
                stage_time = self.memory.read_float(
                    timeline + self.STAGE_TIMELINE_STAGE_TIME_OFFSET
                )
        except MemoryReadError:
            self._cached_stage_pointer = 0
            self._cached_stage_timeline_pointer = 0
            stage_time = None

        if stage_time is None or not isfinite(stage_time) or stage_time <= 0 or stage_time > 1200:
            stage_time = {0: 600.0, 1: 540.0, 2: 480.0}.get(stage_index)
        self._cached_stage_index = stage_index
        return stage_index, stage_time

    def _resolve_stats_entries(self, owner_stats: int | None = None) -> int:
        owner_stats = owner_stats or self._resolve_owner_stats()
        stats_context = self.memory.read_ptr(owner_stats + self.STATS_CONTEXT_OFFSET)
        entries = self.memory.read_ptr(stats_context + self.STATS_ENTRIES_OFFSET)
        if not entries:
            raise MemoryReadError("Player stats entries are not initialized.")

        return entries

    def _resolve_stats_entries_cached(self, owner_stats: int) -> int:
        if (
            owner_stats == self._cached_stats_entries_owner_stats
            and self._cached_stats_entries
        ):
            return self._cached_stats_entries
        entries = self._resolve_stats_entries(owner_stats)
        self._cached_stats_entries_owner_stats = owner_stats
        self._cached_stats_entries = entries
        return entries

    def _resolve_map_controller_static_fields(self) -> int:
        if self._cached_map_controller_static_fields:
            return self._cached_map_controller_static_fields
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.MAP_CONTROLLER_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            return 0
        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            return 0
        self._cached_map_controller_static_fields = static_fields
        return static_fields

    def _get_cached_powerup_multiplier(
        self,
        owner_stats: int,
        *,
        force_refresh: bool = False,
        now: float | None = None,
    ) -> tuple[float | None, str]:
        now = time.monotonic() if now is None else now
        cache_age = now - self._cached_powerup_multiplier_read_at
        if (
            not force_refresh
            and owner_stats == self._cached_powerup_multiplier_owner_stats
            and self._cached_powerup_multiplier_read_at > 0
            and cache_age <= POWERUP_MULTIPLIER_CACHE_TTL_SECONDS
        ):
            return (
                self._cached_powerup_multiplier_value,
                self._cached_powerup_multiplier_display,
            )

        spec = PLAYER_STAT_SPEC_BY_LABEL.get(POWERUP_MULTIPLIER_LABEL)
        if spec is None or spec.offset is None:
            return None, "--"
        try:
            entries = self._resolve_stats_entries_cached(owner_stats)
            value = self.memory.read_float(entries + spec.offset)
        except MemoryReadError:
            self._cached_stats_entries = 0
            self._cached_powerup_multiplier_owner_stats = 0
            self._cached_powerup_multiplier_value = None
            self._cached_powerup_multiplier_display = "--"
            self._cached_powerup_multiplier_read_at = 0.0
            return None, "--"

        display = PlayerStatValue(spec=spec, value=value).display_value
        self._cached_powerup_multiplier_owner_stats = owner_stats
        self._cached_powerup_multiplier_value = value
        self._cached_powerup_multiplier_display = display
        self._cached_powerup_multiplier_read_at = now
        return value, display

    def _scan_status_effect_value_addresses(
        self,
        entries: int,
        capacity: int,
    ) -> tuple[dict[int, int], bool]:
        value_addresses: dict[int, int] = {}
        partial = False
        for index in range(capacity):
            entry = (
                entries
                + self.DICT_ENTRY_START_OFFSET
                + (index * self.DICT_ENTRY_SIZE)
            )
            try:
                if self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET) < 0:
                    continue
                effect_id = self.memory.read_i32(entry + self.DICT_ENTRY_KEY_OFFSET)
                if effect_id not in POWERUP_STATUS_EFFECT_NAMES:
                    continue
            except MemoryReadError:
                partial = True
                continue
            value_addresses[effect_id] = entry + self.DICT_ENTRY_VALUE_OFFSET
        return value_addresses, partial

    def _clear_my_time_cache(self) -> None:
        self._cached_my_time_static_fields = 0

    def _clear_status_effects_cache(self) -> None:
        self._cached_status_effects_dict = 0
        self._cached_status_effects_entries = 0
        self._cached_status_effects_count = 0
        self._cached_status_effects_capacity = 0
        self._cached_status_effects_version = None
        self._cached_status_effect_value_addresses = {}

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

    def _read_permanent_stat_modifiers_dict(
        self,
        dictionary_address: int,
    ) -> dict[int, tuple[PlayerStatModifierSnapshot, ...]]:
        if not dictionary_address:
            return {}

        entries = self.memory.read_ptr(dictionary_address + self.DICT_ENTRIES_OFFSET)
        if not entries:
            return {}

        count = self.memory.read_i32(dictionary_address + self.DICT_COUNT_OFFSET)
        if count <= 0:
            return {}
        if count > self.MAX_PERMANENT_STAT_ENTRIES:
            raise MemoryReadError(f"Permanent stat dictionary count is invalid: {count}")

        modifiers_by_stat: dict[int, tuple[PlayerStatModifierSnapshot, ...]] = {}
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
            if hash_code < 0:
                continue
            stat_id = self.memory.read_i32(entry + self.WEAPON_DICT_ENTRY_KEY_OFFSET)
            list_address = self.memory.read_ptr(entry + self.WEAPON_DICT_ENTRY_VALUE_OFFSET)
            modifiers = self._read_stat_modifier_list(list_address, expected_stat_id=stat_id)
            if modifiers:
                modifiers_by_stat[stat_id] = modifiers
        return modifiers_by_stat

    def _read_stat_modifier_list(
        self,
        list_address: int,
        *,
        expected_stat_id: int | None = None,
    ) -> tuple[PlayerStatModifierSnapshot, ...]:
        if not list_address:
            return ()

        items_array = self.memory.read_ptr(list_address + self.LIST_ITEMS_OFFSET)
        if not items_array:
            return ()

        size = self.memory.read_i32(list_address + self.LIST_SIZE_OFFSET)
        if size <= 0:
            return ()
        if size > self.MAX_PERMANENT_STAT_MODIFIERS:
            raise MemoryReadError(f"Permanent stat modifier list size is invalid: {size}")

        modifiers: list[PlayerStatModifierSnapshot] = []
        for index in range(size):
            modifier_ptr = self.memory.read_ptr(
                items_array + self.ARRAY_DATA_OFFSET + (index * self.OBJECT_POINTER_SIZE)
            )
            if not modifier_ptr:
                continue
            stat_id = self.memory.read_i32(modifier_ptr + self.STAT_MODIFIER_STAT_OFFSET)
            if expected_stat_id is not None and stat_id != expected_stat_id:
                continue
            value = self.memory.read_float(modifier_ptr + self.STAT_MODIFIER_VALUE_OFFSET)
            label, value_format = self._resolve_stat_display(stat_id)
            modifiers.append(
                PlayerStatModifierSnapshot(
                    stat_id=stat_id,
                    label=label,
                    value=value,
                    value_format=value_format,
                )
            )
        return tuple(modifiers)

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

    def get_disabled_items(self) -> DisabledItemsReadResult:
        # 1. Read global catalog
        try:
            type_info_address = self.memory.module_offset(
                self.module_name,
                self.DATA_MANAGER_TYPE_INFO_OFFSET,
            )
            class_ptr = self.memory.read_ptr(type_info_address)
            if not class_ptr:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
            if not static_fields:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            instance = self.memory.read_ptr(static_fields + 0x8)
            if not instance:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            unsorted_items_list = self.memory.read_ptr(instance + 0x60)
            if not unsorted_items_list:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            items_array = self.memory.read_ptr(unsorted_items_list + self.LIST_ITEMS_OFFSET)
            if not items_array:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)
            size = self.memory.read_i32(unsorted_items_list + self.LIST_SIZE_OFFSET)
            if size <= 0 or size > 1000:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            global_item_ids = set()
            for index in range(size):
                item_data_ptr = self.memory.read_ptr(
                    items_array + self.ARRAY_DATA_OFFSET + (index * self.OBJECT_POINTER_SIZE)
                )
                if not item_data_ptr:
                    continue
                item_id = self.memory.read_i32(item_data_ptr + self.ITEM_DATA_ENUM_OFFSET)
                global_item_ids.add(item_id)
            if not global_item_ids:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)
        except MemoryReadError:
            return DisabledItemsReadResult(DisabledItemsReadStatus.READ_ERROR)

        # 2. Read active pool
        try:
            type_info_address = self.memory.module_offset(
                self.module_name,
                self.RUN_UNLOCKABLES_TYPE_INFO_OFFSET,
            )
            class_ptr = self.memory.read_ptr(type_info_address)
            if not class_ptr:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
            if not static_fields:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            available_items_dict = self.memory.read_ptr(static_fields + 0x10)
            if not available_items_dict:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            entries = self.memory.read_ptr(available_items_dict + self.DICT_ENTRIES_OFFSET)
            if not entries:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            count = self.memory.read_i32(available_items_dict + self.DICT_COUNT_OFFSET)
            if count <= 0 or count > 100:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            capacity = self.memory.read_i32(entries + self.ARRAY_LENGTH_OFFSET)
            if capacity <= 0 or capacity > 100:
                return DisabledItemsReadResult(DisabledItemsReadStatus.READ_ERROR)

            available_item_ids = set()
            valid_lists = 0
            for index in range(capacity):
                entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
                hash_code = self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET)
                if hash_code < 0:
                    continue
                list_address = self.memory.read_ptr(entry + self.DICT_ENTRY_VALUE_OFFSET)
                if not list_address:
                    continue

                sub_array = self.memory.read_ptr(list_address + self.LIST_ITEMS_OFFSET)
                if not sub_array:
                    continue
                sub_size = self.memory.read_i32(list_address + self.LIST_SIZE_OFFSET)
                if sub_size < 0 or sub_size > 1000:
                    continue
                valid_lists += 1
                for sub_index in range(sub_size):
                    item_data_ptr = self.memory.read_ptr(
                        sub_array + self.ARRAY_DATA_OFFSET + (sub_index * self.OBJECT_POINTER_SIZE)
                    )
                    if not item_data_ptr:
                        continue
                    item_id = self.memory.read_i32(item_data_ptr + self.ITEM_DATA_ENUM_OFFSET)
                    available_item_ids.add(item_id)

            if valid_lists <= 0 or not available_item_ids:
                return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)

            banished_item_ids = set(self._read_banished_item_ids(
                self.memory.read_ptr(static_fields + self.RUN_UNLOCKABLES_BANISHED_ITEMS_OFFSET)
            ))
        except MemoryReadError:
            return DisabledItemsReadResult(DisabledItemsReadStatus.READ_ERROR)

        # 3. Diff and format
        disabled_item_ids = global_item_ids - (available_item_ids | banished_item_ids)
        disabled_names = []
        for item_id in disabled_item_ids:
            raw_name = ITEM_ENUM_NAMES_BY_ID.get(item_id)
            if raw_name is None:
                continue
            display_name = self._format_item_name(f"Item{raw_name}") or raw_name
            if display_name == "The One Ring":
                continue
            disabled_names.append(display_name)

        return DisabledItemsReadResult(
            DisabledItemsReadStatus.AVAILABLE,
            tuple(sorted(disabled_names)),
        )

    def _read_banished_item_ids(self, set_address: int) -> tuple[int, ...]:
        item_ids: list[int] = []
        for value in self._read_hashset_object_values(set_address):
            item_ids.append(self.memory.read_i32(value + self.ITEM_DATA_ENUM_OFFSET))
        return tuple(item_ids)


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


def format_player_stat_delta(value: float | None, value_format: PlayerStatFormat) -> str:
    if value is None or not isfinite(value):
        return "--"

    sign = "+" if value >= 0 else "-"
    absolute = abs(value)
    if value_format in {PlayerStatFormat.PERCENT, PlayerStatFormat.MULTIPLIER}:
        return f"{sign}{_format_number(absolute * 100)}%"
    return f"{sign}{_format_number(absolute)}"


def format_chaos_tome_stat_delta(
    label: str,
    value: float | None,
    value_format: PlayerStatFormat,
) -> str:
    if value is None or not isfinite(value):
        return "--"

    sign = "+" if value >= 0 else "-"
    absolute = abs(value)
    if label == "Pickup Range" and value_format is PlayerStatFormat.FLAT:
        return f"{sign}{_format_number(absolute * PICKUP_RANGE_BASE_METERS)}"
    if label == "Crit Damage" and value_format is PlayerStatFormat.MULTIPLIER:
        return f"{sign}{_format_number(absolute * CRIT_DAMAGE_BASE_MULTIPLIER * 100)}%"
    return format_player_stat_delta(value, value_format)


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
