"""Memory client for player stats.

The domain half lives in ``core.stats``. Step 2 re-exported those names here so
that ``from player_stats import ...`` call sites kept working across the split;
step 10 moved this client and rewrote every call site to import types from
``core.stats`` directly, so the ``__all__`` re-exports below now have **no
external consumers** -- only this module's own internal use of them is load
bearing. They are kept for one release as a courtesy to anything unmerged;
delete them once nothing depends on this module for types.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import time
from typing import Iterable

from core.character_passives import (
    CHARACTER_PASSIVE_SPEC_BY_CHARACTER_ID,
    CharacterPassiveReading,
)
from core.item_metadata import ITEM_DISPLAY_NAME_BY_RAW_VALUE, ITEM_ENUM_NAMES_BY_ID
from infra.memory.reader import MemoryReadError, ProcessMemory

from core.stats.formats import (
    CRIT_DAMAGE_BASE_MULTIPLIER,
    PICKUP_RANGE_BASE_METERS,
    PlayerStatFormat,
    WeaponStatFormat,
)
from core.stats.formatters import (
    format_chaos_tome_stat_delta,
    format_player_stat_delta,
    format_player_stat_value,
    format_weapon_stat_value,
)
from core.stats.timeline import (
    PlayerStatsTimeline,
)
from core.stats.types import (
    ChargeShrineLogEntry,
    ChargeShrineReading,
    ChaosTomeSnapshot,
    ChaosTomeStatSnapshot,
    DamageSourceSnapshot,
    DisabledItemsReadResult,
    DisabledItemsReadStatus,
    InvalidItemStackCountError,
    ItemCooldownReading,
    ItemCooldownSnapshot,
    LUCK_LABEL,
    MemoryReader,
    PLAYER_STAT_GROUPS,
    PLAYER_STAT_SPEC_BY_LABEL,
    POWERUP_MULTIPLIER_CACHE_TTL_SECONDS,
    POWERUP_MULTIPLIER_LABEL,
    POWERUP_STATUS_EFFECT_NAMES,
    PlayerStatModifierSnapshot,
    PlayerStatSpec,
    PlayerStatValue,
    PlayerStatsSnapshot,
    PowerupReadHealth,
    PowerupTrackingSnapshot,
    STAT_SLOT_SIZE,
    STAT_VALUE_BASE_OFFSET,
    StatusEffectSnapshot,
    StatusEffectsReadResult,
    TOME_NAMES_BY_ID,
    TomeSnapshot,
    WEAPON_NAMES_BY_ID,
    WEAPON_STAT_SPECS,
    WeaponSnapshot,
    WeaponStatSpec,
    WeaponStatValue,
    calculate_chests_per_minute,
    iter_player_stat_groups,
)

__all__ = [
    "CRIT_DAMAGE_BASE_MULTIPLIER",
    "ChaosTomeSnapshot",
    "ChaosTomeStatSnapshot",
    "DamageSourceSnapshot",
    "DisabledItemsReadResult",
    "DisabledItemsReadStatus",
    "ITEM_COOLDOWN_LAYOUTS",
    "InvalidItemStackCountError",
    "ItemCooldownLayout",
    "ItemCooldownReading",
    "ItemCooldownSnapshot",
    "LUCK_LABEL",
    "MemoryReader",
    "PICKUP_RANGE_BASE_METERS",
    "PLAYER_STAT_GROUPS",
    "PLAYER_STAT_SPEC_BY_LABEL",
    "POWERUP_MULTIPLIER_CACHE_TTL_SECONDS",
    "POWERUP_MULTIPLIER_LABEL",
    "POWERUP_STATUS_EFFECT_NAMES",
    "PlayerStatFormat",
    "PlayerStatModifierSnapshot",
    "PlayerStatSpec",
    "PlayerStatValue",
    "PlayerStatsClient",
    "PlayerStatsSnapshot",
    "PlayerStatsTimeline",
    "PowerupReadHealth",
    "PowerupTrackingSnapshot",
    "STAT_SLOT_SIZE",
    "STAT_VALUE_BASE_OFFSET",
    "StatusEffectSnapshot",
    "StatusEffectsReadResult",
    "TOME_NAMES_BY_ID",
    "TomeSnapshot",
    "WEAPON_NAMES_BY_ID",
    "WEAPON_STAT_SPECS",
    "WeaponSnapshot",
    "WeaponStatFormat",
    "WeaponStatSpec",
    "WeaponStatValue",
    "calculate_chests_per_minute",
    "format_chaos_tome_stat_delta",
    "format_player_stat_delta",
    "format_player_stat_value",
    "format_weapon_stat_value",
    "iter_player_stat_groups",
]


@dataclass(frozen=True)
class ItemCooldownLayout:
    """Where one item class keeps its cooldown pair, and how to prove it.

    ``class_name`` is the IL2CPP class from ``dump.cs``. It is not the lookup
    key -- it is the *check*. The key is the item enum id, because the two
    naming spaces do not agree: ``ITEM_ENUM_NAMES_BY_ID[85]`` is ``BobsLantern``
    while the class is ``ItemBobLantern``, and ``74`` is ``GloveBlood`` against
    ``ItemGlovesBlood``. Keying on a name built from the enum table would miss
    silently.

    The verification matters more than it looks. Field offsets are per class, so
    reading this pair off the wrong object does not fail -- it returns
    well-formed floats. A sweep of the live inventory for values that track the
    game clock found nine hits: one was this item, seven were sub-second proc
    timers (``ItemSpikyShield`` and ``ItemBeefyRing`` keep theirs at ``0x3C``,
    exactly where the lantern keeps ``cooldown``), one was a *last*-fired mark
    reading in the past, and one was not a declared field at all. Nothing about
    a wrong read announces itself, so the class name is confirmed before the
    floats are trusted.
    """

    class_name: str
    cooldown_offset: int
    next_trigger_offset: int


#: Item enum id -> where that class keeps its cooldown pair.
#:
#: One entry, and the table shape is the point: it makes a substring or
#: value-shaped guess structurally impossible. Adding a row costs a `dump.cs`
#: confirmation (`tools/scan_timed_items.py`) *and* a live capture -- the dump
#: says a field exists and what it is called, never whether its period is long
#: enough to be worth a line on screen. `ItemGlovesBlood` has a textbook
#: `cooldown`/`readyAtTime` pair and cycles every ~3.7 s.
#:
#: Confirmed live 2026-08-03: `cooldown` = max(5, 45 - 3n) and the mark is
#: absolute on `MyTime.time`, re-armed exactly `+cooldown` on a trigger and to
#: `my_time + 2.000` on any pickup.
ITEM_COOLDOWN_LAYOUTS: dict[int, ItemCooldownLayout] = {
    85: ItemCooldownLayout("ItemBobLantern", cooldown_offset=0x3C, next_trigger_offset=0x40),
}


@dataclass(frozen=True)
class _CooldownSlot:
    """Resolved addresses for one item's cooldown pair.

    Addresses, never values. The dictionary's ``_version`` -- which is what
    invalidates the memo these live in -- moves on an Add or Remove and **not**
    on a stack change: measured, the version held at 27 across a stack going
    1 -> 3, and stepped 4 -> 5 when an item was added. So a cached address stays
    correct (the item object does not move; its pointer was identical across
    ~5300 samples) while a cached ``cooldown`` would go stale in silence the
    moment a copy is picked up.
    """

    item_id: int
    cooldown_address: int
    next_trigger_address: int


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
    CHARACTER_DATA_OFFSET = 0x18
    CHARACTER_DATA_CHARACTER_ID_OFFSET = 0x50
    CHARACTER_DATA_PASSIVE_DATA_OFFSET = 0x88
    PASSIVE_DATA_PASSIVE_ID_OFFSET = 0x28
    PASSIVE_ABILITY_OFFSET = 0x58
    PASSIVE_ABILITY_STAT_MODIFIERS_OFFSET = 0x10
    PASSIVE_STAT_MODIFIERS_CONTAINER_DICT_OFFSET = 0x10
    PASSIVE_LINEAR_PER_LEVEL_OFFSET = 0x18
    GAMBA_UPGRADE_MULTIPLIER_OFFSET = 0x18
    GAMBA_MIN_MULTIPLIER_OFFSET = 0x1C
    GAMBA_MAX_MULTIPLIER_OFFSET = 0x20
    GAMBA_CURRENT_LEVEL_OFFSET = 0x24
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
    # Owned by core.stats.types (PlayerStatSpec.offset derives from them);
    # re-exposed here because callers and tests read them off the client.
    STAT_VALUE_BASE_OFFSET = STAT_VALUE_BASE_OFFSET
    STAT_SLOT_SIZE = STAT_SLOT_SIZE
    ITEM_INVENTORY_OFFSET = 0x20
    ITEM_INVENTORY_ITEMS_DICT_OFFSET = 0x10
    INVENTORY_CONTAINER_OFFSET = 0xA0
    PASSIVE_ITEM_DICT_OFFSET = 0x50
    DICT_ENTRIES_OFFSET = 0x18
    DICT_COUNT_OFFSET = 0x20
    # Current IL2CPP Dictionary layout stores freeList/freeCount at 0x24/0x28.
    # The mutation version follows them at 0x2C.
    DICT_VERSION_OFFSET = 0x2C
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
    # ``MapController.isFinalBossStage`` -- the game naming the Forest/Desert
    # boss room, one byte after ``currentStage`` in the same static block. On
    # Graveyard it stays False (the boss room there is a separate RSG object),
    # so the powerup fallback reads it only to promote, never to demote.
    MAP_CONTROLLER_IS_FINAL_BOSS_STAGE_OFFSET = 0x20
    # Graveyard's own boss room, reached through the RSG (random stage
    # generator) singleton. From script.json/dump.cs, verified live 2026-07-24.
    #   RsgController_TypeInfo -> class -> +0xB8 static -> +0x20 Instance
    #     -> +0x48 roomBoss (GraveyardBossRoom)
    #       +0x38 isFightingBoss, +0xA0 isBossDefeated
    RSG_CONTROLLER_TYPE_INFO_OFFSET = 0x02F79E50
    RSG_INSTANCE_OFFSET = 0x20
    RSG_ROOM_BOSS_OFFSET = 0x48
    GRAVEYARD_BOSS_IS_FIGHTING_OFFSET = 0x38
    GRAVEYARD_BOSS_IS_DEFEATED_OFFSET = 0xA0
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
    ACHIEVEMENT_TRACKER_TYPE_INFO_OFFSET = 0x02F69FE8
    SHRINE_LOGS_TYPE_INFO_OFFSET = 0x02F81B18
    ACHIEVEMENT_CHARGED_SHRINES_OFFSET = 0x58
    SHRINE_LOGS_SHOWN_LOG_OFFSET = 0x08
    MAX_CHARGE_SHRINE_COUNTER = 4096
    MAX_SHRINE_LOG_ENTRIES = 4096

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
        self._cached_chests_bought_count = -1
        self._cached_chests_bought_version: int | None = None
        self._cached_chests_bought_address = 0
        self._cached_kills_dict = 0
        self._cached_kills_entries = 0
        self._cached_kills_count = -1
        self._cached_kills_version: int | None = None
        self._cached_kills_address = 0
        self._cached_key_dict = 0
        self._cached_key_entries = 0
        self._cached_key_dict_count = -1
        self._cached_key_version: int | None = None
        self._cached_key_stack_address = 0
        # The passive inventory's *layout*: which slots hold an item, where each
        # one's stack count lives, and what it is called. Validated exactly like
        # the Key address above -- dictionary pointer, entries pointer, count and
        # `_version` -- which is the invariant that cache already relies on in
        # production. A .NET dictionary bumps `_version` on every Add/Remove, so
        # any change to *which* items are held invalidates this; a stack count
        # changing (an item levelling up) does not, and must not, because the
        # stack counts are the part that is re-read on every pass.
        self._cached_item_layout_dict = 0
        self._cached_item_layout_entries = 0
        self._cached_item_layout_count = -1
        self._cached_item_layout_version: int | None = None
        self._cached_item_layout: (
            tuple[tuple[int, str, "_CooldownSlot | None"], ...] | None
        ) = None
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
        # A changed multiplier that has been seen once but not yet confirmed.
        # See `_get_cached_powerup_multiplier`.
        self._pending_powerup_multiplier_value: float | None = None
        self._cached_my_time_static_fields = 0
        self._cached_map_controller_static_fields = 0
        self._cached_rsg_static_fields = 0
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

    def get_luck(self, owner_stats: int | None = None) -> float | None:
        """Read Luck (stat 30) on its own.

        Its own reader rather than a ``get_player_stats`` call, because that
        walks every spec in ``PLAYER_STAT_GROUPS`` -- forty-odd ``read_float``
        calls -- which is the right cost on the 10 s snapshot and the wrong one
        on a pass that runs every second. This is the cached entries pointer
        and one float.

        ``None`` on a failed read, matching what ``get_player_stats`` puts in
        ``PlayerStatValue.value`` for the same failure, so the narrow source and
        the full snapshot report the same thing including when they fail.
        Deliberately not ``0.0``: Luck 0 is a real reading -- a run with no Luck
        items yet -- and the rarity model produces a valid distribution from it,
        so a failure disguised as zero would be indistinguishable from a fresh
        run rather than visible as an absent one.
        """
        owner_stats = owner_stats or self._resolve_owner_stats()
        spec = PLAYER_STAT_SPEC_BY_LABEL.get(LUCK_LABEL)
        if spec is None or spec.offset is None:
            return None
        try:
            entries = self._resolve_stats_entries_cached(owner_stats)
            return self.memory.read_float(entries + spec.offset)
        except MemoryReadError:
            # Same as `_get_cached_powerup_multiplier`: a failed read through
            # the cached entries pointer is the signal that the pointer itself
            # is stale, so drop it rather than failing against it every pass.
            self._cached_stats_entries = 0
            return None

    def get_size(self, owner_stats: int | None = None) -> float | None:
        """Read Size (stat 9) with up to three physical attempts.

        Each failed cached-pointer attempt resets the cache so the next
        attempt can re-resolve the pointer chain.  The per-pass source
        cache in the coordinator still exposes one logical SIZE result.
        """
        owner_stats = owner_stats or self._resolve_owner_stats()
        spec = PLAYER_STAT_SPEC_BY_LABEL.get("Size")
        if spec is None or spec.offset is None:
            return None
        for _ in range(3):
            try:
                entries = self._resolve_stats_entries_cached(owner_stats)
                return self.memory.read_float(entries + spec.offset)
            except MemoryReadError:
                self._cached_stats_entries = 0
        return None

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
        primary_error: MemoryReadError | InvalidItemStackCountError | None = None
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
        except (MemoryReadError, InvalidItemStackCountError) as exc:
            primary_error = exc

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

        items = self._read_passive_item_dictionary(passive_item_dict)
        if items or primary_error is None:
            return items
        # One route failed while the other merely looked empty. That disagreement
        # is not evidence of an empty inventory: publishing it would lower the
        # item-delta baseline and credit the same items again when the failed
        # route recovers.
        raise primary_error

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
        count = self.memory.read_i32(passive_item_dict + self.DICT_COUNT_OFFSET)
        version = self.memory.read_i32(passive_item_dict + self.DICT_VERSION_OFFSET)
        cache_valid = (
            passive_item_dict == self._cached_key_dict
            and entries == self._cached_key_entries
            and count == self._cached_key_dict_count
            and version == self._cached_key_version
        )
        if not cache_valid:
            self._cached_key_dict = passive_item_dict
            self._cached_key_entries = entries
            self._cached_key_dict_count = count
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

    def _dictionary_has_entries(self, dictionary: int) -> bool:
        """Is this dictionary the live one, or a drained shell?

        Both routes to the passive inventory can hand back a **non-null pointer
        to an empty dictionary**, and which one does depends on run state.
        Measured live on 2026-08-03, mid-run, with 25 items held: the container
        route resolved `0x...EF750` with `count=0, version=0, entries=0x0` while
        the player-inventory route resolved the real one with `count=25`. A
        resolver that stops at "non-null" therefore picks the dead one and never
        looks further.
        """
        try:
            if not self.memory.read_ptr(dictionary + self.DICT_ENTRIES_OFFSET):
                return False
            return self.memory.read_i32(dictionary + self.DICT_COUNT_OFFSET) > 0
        except MemoryReadError:
            return False

    def _resolve_preferred_passive_item_dict(self, owner_stats: int) -> int:
        """The passive item dictionary that actually holds the inventory.

        Prefers whichever candidate has entries rather than whichever pointer is
        non-null first. This is the rule `get_passive_items` has always applied
        by falling through on an *empty result*; stating it here means the two
        cannot disagree about which dictionary is live -- which they did, and
        the disagreement was silent: `_get_cached_key_count` read the drained
        container dictionary and reported `key_count=0` for a player visibly
        holding a Key.

        When neither candidate has entries the container one is returned
        unchanged, so "the player owns nothing yet" still reads as an empty
        inventory rather than a failure.
        """
        container_dict = 0
        try:
            inventory_container = self.memory.read_ptr(
                owner_stats + self.INVENTORY_CONTAINER_OFFSET
            )
            if inventory_container:
                container_dict = self.memory.read_ptr(
                    inventory_container + self.PASSIVE_ITEM_DICT_OFFSET
                )
                if container_dict and self._dictionary_has_entries(container_dict):
                    return container_dict
        except MemoryReadError:
            pass

        inventory_dict = 0
        try:
            player_inventory = self.memory.read_ptr(
                owner_stats + self.PLAYER_INVENTORY_OFFSET
            )
            item_inventory = (
                self.memory.read_ptr(player_inventory + self.ITEM_INVENTORY_OFFSET)
                if player_inventory
                else 0
            )
            inventory_dict = (
                self.memory.read_ptr(
                    item_inventory + self.ITEM_INVENTORY_ITEMS_DICT_OFFSET
                )
                if item_inventory
                else 0
            )
        except MemoryReadError:
            inventory_dict = 0

        if inventory_dict and self._dictionary_has_entries(inventory_dict):
            return inventory_dict
        # Neither holds anything: hand back the container one so an inventory
        # that is genuinely empty still resolves to a dictionary rather than to
        # a failure. `container_dict or inventory_dict` rather than a bare
        # `container_dict`, so a state where only the fallback pointer resolves
        # at all is not turned into "no dictionary".
        return container_dict or inventory_dict

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
        self._cached_key_dict_count = -1
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

        # The whole walk costs 4 reads per entry -- value pointer, key id, and
        # two for the stabilised stack count. Only the last pair can change
        # while the dictionary's `_version` holds, so with a valid layout this
        # halves the cost of the pass that made the fast lane affordable
        # (~120 -> ~65 reads at 30 items). Same invalidation as
        # `_get_cached_key_count`; nothing new is trusted here.
        cached_layout = self._passive_item_layout(passive_item_dict, entries, count)
        if cached_layout is not None:
            try:
                return tuple(
                    f"{item_name} x{max(1, self._layout_stack_count(stack_address))}"
                    for stack_address, item_name, _cooldown in cached_layout
                )
            except (MemoryReadError, InvalidItemStackCountError):
                # A cached address that cannot be read is no longer a trustworthy
                # description of this dictionary. Rebuild it on the next pass.
                self._clear_passive_item_layout()
                raise

        layout: list[tuple[int, str, _CooldownSlot | None]] = []
        items: list[str] = []
        broken_entries = 0
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + (index * self.DICT_ENTRY_SIZE)
            try:
                item_value = self.memory.read_ptr(entry + self.DICT_ENTRY_VALUE_OFFSET)
                if not item_value:
                    # A free slot: .NET nulls the value of a removed entry but
                    # keeps it inside `count`. Nothing is here to lose, so this
                    # is not an incomplete walk and does not defeat the memo.
                    continue

                # Rebound per entry, not left over from the previous one: the
                # read below can fail, and a stale id would then be attributed
                # to this slot -- which is exactly how a cooldown layout would
                # get bound to the wrong item.
                item_id: int | None = None
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
                    # A live value pointer that would not resolve to a name --
                    # an unknown enum id, or a class-meta/name chain that read
                    # as zero this pass. There *is* an item in this slot, so the
                    # walk is incomplete, not free: skip it for this read but
                    # treat it exactly like a torn entry so the incomplete
                    # layout is never memoised. Otherwise the item stays
                    # invisible until the dictionary's `_version` next moves --
                    # an Add or Remove -- which in recorded runs left single
                    # items missing for tens of consecutive snapshots.
                    broken_entries += 1
                    continue

                stack_count = self._read_stable_item_stack_count(
                    item_value + self.ITEM_STACK_COUNT_OFFSET
                )
            except InvalidItemStackCountError:
                self._clear_passive_item_layout()
                raise
            except MemoryReadError:
                broken_entries += 1
                continue

            # Resolved on the clean walk only, so the per-pass cost of the
            # cooldown feature on the cached path is two float reads for the one
            # item that has them -- not a second walk of the dictionary.
            cooldown_slot = self._resolve_cooldown_slot(item_value, item_id)
            layout.append((item_value + self.ITEM_STACK_COUNT_OFFSET, item_name, cooldown_slot))
            items.append(f"{item_name} x{max(1, stack_count)}")

        if broken_entries:
            # A non-empty subset is still incomplete. Publishing it as an
            # available inventory lets two bad samples confirm a false loss; the
            # item's return is then counted as a new pickup. Fail the whole pass
            # so both fast and slow consumers preserve their confirmed baseline.
            self._clear_passive_item_layout()
            raise MemoryReadError(
                "Passive item dictionary walk was incomplete: "
                f"{broken_entries} of {count} entries could not be decoded."
            )

        self._store_passive_item_layout(passive_item_dict, entries, count, tuple(layout))
        return tuple(items)

    def _resolve_cooldown_slot(
        self, item_value: int, item_id: int | None
    ) -> _CooldownSlot | None:
        """Bind an item object to its cooldown layout, or refuse to.

        Returns ``None`` for every item that is not in the table, which is
        almost all of them, and also for a listed item whose class metadata does
        not read back as the class the table names. That check is the whole
        safety of the feature: the offsets are per class, so a mismatch does not
        raise -- it hands back plausible floats. Refusing is silent and costs
        one line on screen; guessing is silent and costs a wrong number that
        looks right.

        Failing to read the class name is treated as a mismatch. This runs only
        on the clean-walk path, so a slot dropped here is retried on the very
        next pass rather than being frozen out until the dictionary changes.
        """
        if item_id is None:
            return None
        layout = ITEM_COOLDOWN_LAYOUTS.get(item_id)
        if layout is None:
            return None

        try:
            class_meta = self.memory.read_ptr(item_value + self.ITEM_CLASS_META_OFFSET)
            name_ptr = (
                self.memory.read_ptr(class_meta + self.CLASS_META_NAME_PTR_OFFSET)
                if class_meta
                else 0
            )
            class_name = self.memory.read_ascii_string(name_ptr) if name_ptr else None
        except MemoryReadError:
            return None

        if class_name != layout.class_name:
            return None

        return _CooldownSlot(
            item_id=item_id,
            cooldown_address=item_value + layout.cooldown_offset,
            next_trigger_address=item_value + layout.next_trigger_offset,
        )

    def get_item_cooldowns(self, owner_stats: int | None = None) -> ItemCooldownSnapshot:
        """Cooldown state for every timed passive item, against one clock read.

        ``my_time`` is read in this same call rather than by the caller, so a
        reading and the clock it is measured against cannot come from different
        passes. Both freeze together while the game is paused, which is correct
        and is also indistinguishable from the death screen -- neither the TTL
        nor a failed read will clear a stale display, because nothing here
        fails there. Whether to keep showing the widget is a run-lifecycle
        question, not this method's.

        Raises on an unreadable clock or dictionary. An empty ``readings`` tuple
        means the inventory holds no timed item, which is a real answer; a
        failure must not be flattened into one.
        """
        owner_stats = owner_stats or self._resolve_owner_stats()
        my_time = self.get_my_time_seconds()

        passive_item_dict = self._resolve_preferred_passive_item_dict(owner_stats)
        if not passive_item_dict:
            return ItemCooldownSnapshot(my_time_seconds=my_time)

        # Populates the memo as a side effect when it is cold, and is a no-op
        # walk when it is warm -- so this costs a dictionary walk once per
        # Add/Remove and two float reads per pass thereafter.
        self._read_passive_item_dictionary(passive_item_dict)
        layout = self._cached_item_layout
        # The memo must belong to the dictionary just walked. Without this the
        # method reads whatever layout happened to be cached by an *earlier*
        # call against a *different* dictionary -- which is not hypothetical:
        # while the container route was resolving a drained dictionary, this
        # returned correct-looking readings purely because `get_passive_items`
        # had run first and left a live layout behind.
        if not layout or self._cached_item_layout_dict != passive_item_dict:
            return ItemCooldownSnapshot(my_time_seconds=my_time)

        readings: list[ItemCooldownReading] = []
        for stack_address, item_name, cooldown_slot in layout:
            if cooldown_slot is None:
                continue
            try:
                cooldown = self.memory.read_float(cooldown_slot.cooldown_address)
                next_trigger = self.memory.read_float(cooldown_slot.next_trigger_address)
            except MemoryReadError:
                # One torn item, not a failed batch. The others in this pass are
                # still good, and the caller's TTL covers a slot that stays
                # unreadable.
                continue

            if not isfinite(cooldown) or not isfinite(next_trigger):
                continue
            # `cooldown <= 0` is insurance rather than a fix: at 20 Hz the
            # fields were never observed half-written -- they appear correct on
            # the same read the dictionary entry first appears on. It costs one
            # comparison to not find out the hard way on some other item.
            if cooldown <= 0.0:
                continue

            # `_layout_stack_count`, not a bespoke read: it already encodes the
            # policy the cached item path uses -- an unreadable stack degrades
            # to 1, while `InvalidItemStackCountError` (a *torn* read) is left
            # to propagate. Here that aborts the batch, the caller records no
            # reading, and the TTL clears the display. Failing closed on a torn
            # read is the same answer the item ladders give, reached for the
            # same reason.
            stack_count = self._layout_stack_count(stack_address)
            if stack_count < 1:
                continue

            readings.append(
                ItemCooldownReading(
                    item_id=cooldown_slot.item_id,
                    name=item_name,
                    stack_count=stack_count,
                    cooldown_seconds=cooldown,
                    next_trigger_time=next_trigger,
                )
            )

        return ItemCooldownSnapshot(
            my_time_seconds=my_time, readings=tuple(readings)
        )

    def _passive_item_layout(
        self,
        passive_item_dict: int,
        entries: int,
        count: int,
    ) -> tuple[tuple[int, str, _CooldownSlot | None], ...] | None:
        """The memoised slot layout, or ``None`` when it must be rebuilt."""
        if self._cached_item_layout is None:
            return None
        if (
            passive_item_dict != self._cached_item_layout_dict
            or entries != self._cached_item_layout_entries
            or count != self._cached_item_layout_count
        ):
            return None
        try:
            version = self.memory.read_i32(passive_item_dict + self.DICT_VERSION_OFFSET)
        except MemoryReadError:
            self._clear_passive_item_layout()
            return None
        if version != self._cached_item_layout_version:
            return None
        return self._cached_item_layout

    def _store_passive_item_layout(
        self,
        passive_item_dict: int,
        entries: int,
        count: int,
        layout: tuple[tuple[int, str, _CooldownSlot | None], ...],
    ) -> None:
        try:
            version = self.memory.read_i32(passive_item_dict + self.DICT_VERSION_OFFSET)
        except MemoryReadError:
            self._clear_passive_item_layout()
            return
        self._cached_item_layout_dict = passive_item_dict
        self._cached_item_layout_entries = entries
        self._cached_item_layout_count = count
        self._cached_item_layout_version = version
        self._cached_item_layout = layout

    def _clear_passive_item_layout(self) -> None:
        self._cached_item_layout_dict = 0
        self._cached_item_layout_entries = 0
        self._cached_item_layout_count = -1
        self._cached_item_layout_version = None
        self._cached_item_layout = None

    def _layout_stack_count(self, stack_address: int) -> int:
        """One entry's stack count on the cached path, or a failed whole pass."""
        return self._read_stable_item_stack_count(stack_address)

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

    def get_character_passive_reading(
        self,
        owner_stats: int | None = None,
        *,
        permanent_modifiers: dict[int, tuple[PlayerStatModifierSnapshot, ...]] | None = None,
    ) -> CharacterPassiveReading:
        """Read and validate the selected character's passive runtime object.

        Identity is always returned for an unknown future enum so core can
        publish an explicit ``unknown`` state. A known character paired with a
        different passive enum or runtime class is treated as a build mismatch
        and fails closed.
        """
        owner_stats = owner_stats or self._resolve_owner_stats()
        player_inventory = self.memory.read_ptr(
            owner_stats + self.PLAYER_INVENTORY_OFFSET
        )
        if not player_inventory:
            raise MemoryReadError("Player inventory is not initialized.")

        character_data = self.memory.read_ptr(
            player_inventory + self.CHARACTER_DATA_OFFSET
        )
        if not character_data:
            raise MemoryReadError("Character data is not initialized.")
        character_id = self.memory.read_i32(
            character_data + self.CHARACTER_DATA_CHARACTER_ID_OFFSET
        )

        passive_data = self.memory.read_ptr(
            character_data + self.CHARACTER_DATA_PASSIVE_DATA_OFFSET
        )
        if not passive_data:
            raise MemoryReadError("Character passive data is not initialized.")
        passive_id = self.memory.read_i32(
            passive_data + self.PASSIVE_DATA_PASSIVE_ID_OFFSET
        )

        passive_object = self.memory.read_ptr(
            player_inventory + self.PASSIVE_ABILITY_OFFSET
        )
        if not passive_object:
            raise MemoryReadError("Character passive runtime is not initialized.")
        runtime_class = self._read_object_class_name(passive_object)
        if not runtime_class:
            raise MemoryReadError("Character passive runtime class is unavailable.")

        spec = CHARACTER_PASSIVE_SPEC_BY_CHARACTER_ID.get(character_id)
        if spec is not None:
            if passive_id != spec.passive_id:
                raise MemoryReadError(
                    "Character/passive enum mismatch: "
                    f"{character_id}/{passive_id}, expected {spec.passive_id}."
                )
            if runtime_class != spec.runtime_class:
                raise MemoryReadError(
                    "Character passive class mismatch: "
                    f"{runtime_class}, expected {spec.runtime_class}."
                )

        player_xp = self.memory.read_ptr(player_inventory + self.PLAYER_XP_OFFSET)
        if not player_xp:
            raise MemoryReadError("Player XP is not initialized.")
        level = self.memory.read_i32(player_xp + self.PLAYER_XP_LEVEL_OFFSET)
        if not 0 <= level <= self.MAX_PASSIVE_ITEM_STACK_COUNT:
            raise MemoryReadError(f"Character level is invalid: {level}")

        character_name = spec.character_name if spec else f"Character {character_id}"
        passive_name = spec.passive_name if spec else f"Passive {passive_id}"
        common = dict(
            character_id=character_id,
            character_name=character_name,
            passive_id=passive_id,
            passive_name=passive_name,
            runtime_class=runtime_class,
            passive_object_ptr=passive_object,
            level=level,
        )

        if spec is None or not spec.supported:
            return CharacterPassiveReading(**common)

        if spec.linear is not None:
            per_level = self.memory.read_float(
                passive_object + self.PASSIVE_LINEAR_PER_LEVEL_OFFSET
            )
            modifiers = tuple(
                modifier
                for modifier in self._read_passive_stat_modifiers(passive_object)
                if int(modifier.stat_id) == spec.linear.stat_id
                and int(modifier.modify_type if modifier.modify_type is not None else -1) == 2
            )
            return CharacterPassiveReading(
                **common,
                per_level=per_level,
                passive_modifiers=modifiers,
            )

        # Gamba writes a permanent modifier before advancing currentLevel.
        # Snapshot the shared objects first and read the budget last so a
        # candidate observed inside that writer window remains pending.
        stat_inventory = self.memory.read_ptr(
            player_inventory + self.STAT_INVENTORY_OFFSET
        )
        permanent_dictionary = (
            self.memory.read_ptr(
                stat_inventory + self.STAT_INVENTORY_PERMANENT_CHANGES_OFFSET
            )
            if stat_inventory
            else 0
        )
        permanent_by_stat = (
            permanent_modifiers
            if permanent_modifiers is not None
            else self._read_permanent_stat_modifiers_dict(permanent_dictionary)
        )
        permanent_modifiers = tuple(
            modifier
            for stat_id in sorted(permanent_by_stat)
            for modifier in permanent_by_stat[stat_id]
        )
        current_level = self.memory.read_i32(
            passive_object + self.GAMBA_CURRENT_LEVEL_OFFSET
        )
        if not 0 <= current_level <= self.MAX_PASSIVE_ITEM_STACK_COUNT:
            raise MemoryReadError(f"Gamba current level is invalid: {current_level}")
        return CharacterPassiveReading(
            **common,
            permanent_modifiers=permanent_modifiers,
            gamba_current_level=current_level,
            gamba_upgrade_multiplier=self.memory.read_float(
                passive_object + self.GAMBA_UPGRADE_MULTIPLIER_OFFSET
            ),
            gamba_min_multiplier=self.memory.read_float(
                passive_object + self.GAMBA_MIN_MULTIPLIER_OFFSET
            ),
            gamba_max_multiplier=self.memory.read_float(
                passive_object + self.GAMBA_MAX_MULTIPLIER_OFFSET
            ),
        )

    def get_charge_shrine_tracking_state(self) -> ChargeShrineReading:
        """Read the shared shrine log followed by the Charge Shrine budget.

        ``shownLog`` also contains Gritch/Greed effects. This boundary preserves
        the raw entries; attribution belongs to ``core.tracker.shrines``, where
        the charged counter and the reward fingerprints can be considered
        together. Log-first ordering is deliberate: if a charge lands between
        the two reads, the newer counter opens a pending reward for the next
        tick. Counter-first could pair an old budget with a new modifier and
        permanently skip that reward.
        """
        shrine_log_fields = self._resolve_type_static_fields(
            self.SHRINE_LOGS_TYPE_INFO_OFFSET,
            "ShrineLogs",
        )
        shown_log = self.memory.read_ptr(
            shrine_log_fields + self.SHRINE_LOGS_SHOWN_LOG_OFFSET
        )
        entries = self._read_shrine_log(shown_log) if shown_log else ()

        achievement_fields = self._resolve_type_static_fields(
            self.ACHIEVEMENT_TRACKER_TYPE_INFO_OFFSET,
            "AchievementTracker",
        )
        charged_total = self.memory.read_i32(
            achievement_fields + self.ACHIEVEMENT_CHARGED_SHRINES_OFFSET
        )
        if not 0 <= charged_total <= self.MAX_CHARGE_SHRINE_COUNTER:
            raise MemoryReadError(
                f"Charge Shrine charged counter is invalid: {charged_total}"
            )
        return ChargeShrineReading(
            charged_total=charged_total,
            shown_log=entries,
            captured_at=time.monotonic(),
        )

    def _resolve_type_static_fields(self, type_info_offset: int, label: str) -> int:
        type_info_address = self.memory.module_offset(
            self.module_name,
            int(type_info_offset),
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            raise MemoryReadError(f"{label} type info is not initialized.")
        static_fields = self.memory.read_ptr(
            class_ptr + self.CLASS_STATIC_FIELDS_OFFSET
        )
        if not static_fields:
            raise MemoryReadError(f"{label} static fields are not initialized.")
        return static_fields

    def _read_shrine_log(
        self,
        list_address: int,
    ) -> tuple[ChargeShrineLogEntry, ...]:
        size = self.memory.read_i32(list_address + self.LIST_SIZE_OFFSET)
        if not 0 <= size <= self.MAX_SHRINE_LOG_ENTRIES:
            raise MemoryReadError(f"Shrine log size is invalid: {size}")
        if size == 0:
            return ()
        items_array = self.memory.read_ptr(list_address + self.LIST_ITEMS_OFFSET)
        if not items_array:
            raise MemoryReadError("Shrine log has entries but no items array.")

        entries: list[ChargeShrineLogEntry] = []
        for index in range(size):
            modifier_ptr = self.memory.read_ptr(
                items_array
                + self.ARRAY_DATA_OFFSET
                + (index * self.OBJECT_POINTER_SIZE)
            )
            if not modifier_ptr:
                raise MemoryReadError(
                    f"Shrine log entry {index} has a null modifier pointer."
                )
            stat_id = self.memory.read_i32(
                modifier_ptr + self.STAT_MODIFIER_STAT_OFFSET
            )
            modify_type = self.memory.read_i32(
                modifier_ptr + self.STAT_MODIFIER_TYPE_OFFSET
            )
            value = self.memory.read_float(
                modifier_ptr + self.STAT_MODIFIER_VALUE_OFFSET
            )
            if modify_type not in (0, 1, 2) or not isfinite(value):
                raise MemoryReadError(
                    "Shrine log modifier is invalid: "
                    f"stat={stat_id}, type={modify_type}, value={value}"
                )
            label, value_format = self._resolve_stat_display(stat_id)
            entries.append(
                ChargeShrineLogEntry(
                    object_ptr=modifier_ptr,
                    stat_id=stat_id,
                    label=label,
                    value=value,
                    value_format=value_format,
                    modify_type=modify_type,
                )
            )
        return tuple(entries)

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
            raise MemoryReadError("Run unlockables type info is not initialized.")

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            raise MemoryReadError("Run unlockables static fields are not initialized.")

        item_set = self.memory.read_ptr(static_fields + self.RUN_UNLOCKABLES_BANISHED_ITEMS_OFFSET)
        upgradable_set = self.memory.read_ptr(
            static_fields + self.RUN_UNLOCKABLES_BANISHED_UPGRADABLES_OFFSET
        )
        if not item_set or not upgradable_set:
            raise MemoryReadError("Run banish sets are not initialized.")
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
            # Read from the same already-resolved MyTime object as the two
            # above. ``my_time`` is a session clock, not the run clock, so it
            # cannot serve as the reference the powerup renderer needs: the
            # stage timer is only meaningful while it has not overrun the run.
            run_timer_seconds = self.memory.read_float(my_time_static_fields + self.RUN_TIMER_OFFSET)
        except MemoryReadError:
            self._clear_my_time_cache()
            my_time_seconds = None
            stage_timer_seconds = None
            run_timer_seconds = None
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
        # Positive-only, like every other boss-room read: a failed read is
        # False = "no information", never "not the boss room", because the
        # fallback consumes it only to promote into seconds-only mode.
        is_final_boss_stage = self._read_is_final_boss_stage()
        graveyard_boss_fighting, graveyard_boss_defeated = (
            self._read_graveyard_boss_flags()
        )

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
            run_timer_seconds=run_timer_seconds,
            stage_index=stage_index,
            stage_time_seconds=stage_time_seconds,
            powerup_multiplier=powerup_multiplier,
            powerup_multiplier_display=powerup_multiplier_display,
            final_swarm_timer_seconds=final_swarm_timer_seconds,
            crypt_timer_seconds=crypt_timer_seconds,
            is_final_boss_stage=is_final_boss_stage,
            graveyard_boss_fighting=graveyard_boss_fighting,
            graveyard_boss_defeated=graveyard_boss_defeated,
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
        count = self.memory.read_i32(stats_dict + self.DICT_COUNT_OFFSET)
        if count < 0 or count > self.MAX_RUN_STATS_ENTRIES:
            raise MemoryReadError(f"RunStats dictionary count is invalid: {count}")
        version = self.memory.read_i32(stats_dict + self.DICT_VERSION_OFFSET)

        if (
            stats_dict != self._cached_chests_bought_dict
            or entries != self._cached_chests_bought_entries
            or count != self._cached_chests_bought_count
            or version != self._cached_chests_bought_version
        ):
            self._cached_chests_bought_dict = stats_dict
            self._cached_chests_bought_entries = entries
            self._cached_chests_bought_count = count
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
        count = self.memory.read_i32(stats_dict + self.DICT_COUNT_OFFSET)
        if count < 0 or count > self.MAX_RUN_STATS_ENTRIES:
            raise MemoryReadError(f"RunStats dictionary count is invalid: {count}")
        version = self.memory.read_i32(stats_dict + self.DICT_VERSION_OFFSET)

        if (
            stats_dict != self._cached_kills_dict
            or entries != self._cached_kills_entries
            or count != self._cached_kills_count
            or version != self._cached_kills_version
        ):
            self._cached_kills_dict = stats_dict
            self._cached_kills_entries = entries
            self._cached_kills_count = count
            self._cached_kills_version = version
            self._cached_kills_address = self._find_run_stat_value_address(
                stats_dict,
                "kills",
            )

        if not self._cached_kills_address:
            # Zero kills, not unavailable memory. Every structural failure --
            # uninitialised type info, static fields, dictionary or entries
            # array, invalid count -- has already raised above, so reaching
            # here means a *valid* dictionary was walked and did not contain
            # "kills". The game creates that entry lazily, on its first
            # increment, so its absence is exactly the state "nothing has died
            # yet". `_get_cached_chests_bought` above is this method's
            # structural twin and already returns 0 at the identical decision
            # point. Raising here instead made every read fail for the opening
            # stretch of a run and took the successfully-read run timer down
            # with it -- see step_28_plan.md section 12.1.
            return 0
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

    def _read_is_final_boss_stage(self) -> bool:
        """``MapController.isFinalBossStage`` -- the Forest/Desert boss room.

        Reuses the same cached MapController static block ``_read_current_stage_time``
        resolves, so it is one byte on an already-resolved pointer. Positive-only:
        any failure returns False, which the fallback treats as "no information",
        never as "not the boss room".
        """
        static_fields = self._resolve_map_controller_static_fields()
        if not static_fields:
            return False
        try:
            return bool(
                self.memory.read_u8(
                    static_fields + self.MAP_CONTROLLER_IS_FINAL_BOSS_STAGE_OFFSET
                )
            )
        except MemoryReadError:
            return False

    def _resolve_rsg_static_fields(self) -> int:
        if self._cached_rsg_static_fields:
            return self._cached_rsg_static_fields
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.RSG_CONTROLLER_TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            return 0
        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            return 0
        self._cached_rsg_static_fields = static_fields
        return static_fields

    def _read_graveyard_boss_flags(self) -> tuple[bool, bool]:
        """``(is_fighting_boss, is_boss_defeated)`` for Graveyard's boss room.

        Positive-only, like the other boss-room reads: any failure -- the RSG
        singleton not resolving (every non-Graveyard map, and Graveyard before
        the boss dungeon generates), a null ``Instance`` or ``roomBoss``, a torn
        pointer -- returns ``(False, False)`` = "no information". ``roomBoss`` is
        non-null from the very first tick even in crypt 1, so only the flags on
        it carry the phase; the pointer being set means nothing on its own.
        """
        try:
            static_fields = self._resolve_rsg_static_fields()
            if not static_fields:
                return False, False
            instance = self.memory.read_ptr(static_fields + self.RSG_INSTANCE_OFFSET)
            if not instance:
                return False, False
            room_boss = self.memory.read_ptr(instance + self.RSG_ROOM_BOSS_OFFSET)
            if not room_boss:
                return False, False
            fighting = bool(
                self.memory.read_u8(room_boss + self.GRAVEYARD_BOSS_IS_FIGHTING_OFFSET)
            )
            defeated = bool(
                self.memory.read_u8(room_boss + self.GRAVEYARD_BOSS_IS_DEFEATED_OFFSET)
            )
            return fighting, defeated
        except MemoryReadError:
            return False, False

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
            # An unconfirmed value must not be left to sit out the TTL: the
            # confirming read is what decides whether it was a real change or
            # a bad frame, so take it on the very next call.
            and self._pending_powerup_multiplier_value is None
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
            self._pending_powerup_multiplier_value = None
            return None, "--"

        # Require a changed multiplier to be read twice before it is believed.
        #
        # This read is force-refreshed the moment the active-effect set
        # changes -- i.e. on the exact frame a powerup is picked up, when the
        # player struct is mid-update and the stats entries can hand back a
        # value that is briefly wrong. Downstream that value is not cosmetic:
        # it sets the buff's duration, so one bad frame at 1.0x turns a 22.5 s
        # buff into a 15 s one and moves its expiry mark on the stage timer.
        # A genuine multiplier change survives to the next read; a bad frame
        # does not. The cost is that a real change is published one tick
        # (500 ms) late, which nothing downstream measures.
        confirmed = self._cached_powerup_multiplier_value
        if (
            confirmed is not None
            and isfinite(confirmed)
            and isfinite(value)
            and value != confirmed
            and owner_stats == self._cached_powerup_multiplier_owner_stats
            and self._cached_powerup_multiplier_read_at > 0
            and self._pending_powerup_multiplier_value != value
        ):
            self._pending_powerup_multiplier_value = value
            return confirmed, self._cached_powerup_multiplier_display

        self._pending_powerup_multiplier_value = None
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
                    object_ptr=modifier_ptr,
                    modify_type=self.memory.read_i32(
                        modifier_ptr + self.STAT_MODIFIER_TYPE_OFFSET
                    ),
                )
            )
        return tuple(modifiers)

    def _read_passive_stat_modifiers(
        self,
        passive_object: int,
    ) -> tuple[PlayerStatModifierSnapshot, ...]:
        outer = self.memory.read_ptr(
            passive_object + self.PASSIVE_ABILITY_STAT_MODIFIERS_OFFSET
        )
        if not outer:
            return ()
        entries = self.memory.read_ptr(outer + self.DICT_ENTRIES_OFFSET)
        count = self.memory.read_i32(outer + self.DICT_COUNT_OFFSET)
        if count <= 0 or not entries:
            return ()
        if count > self.MAX_PERMANENT_STAT_ENTRIES:
            raise MemoryReadError(
                f"Passive stat dictionary count is invalid: {count}"
            )

        modifiers: list[PlayerStatModifierSnapshot] = []
        for index in range(count):
            entry = entries + self.DICT_ENTRY_START_OFFSET + index * self.DICT_ENTRY_SIZE
            if self.memory.read_i32(entry + self.DICT_ENTRY_HASH_CODE_OFFSET) < 0:
                continue
            outer_stat_id = self.memory.read_i32(entry + self.DICT_ENTRY_KEY_OFFSET)
            container = self.memory.read_ptr(entry + self.DICT_ENTRY_VALUE_OFFSET)
            inner = (
                self.memory.read_ptr(
                    container + self.PASSIVE_STAT_MODIFIERS_CONTAINER_DICT_OFFSET
                )
                if container
                else 0
            )
            if not inner:
                continue
            inner_entries = self.memory.read_ptr(inner + self.DICT_ENTRIES_OFFSET)
            inner_count = self.memory.read_i32(inner + self.DICT_COUNT_OFFSET)
            if inner_count <= 0 or not inner_entries:
                continue
            if inner_count > 16:
                raise MemoryReadError(
                    f"Passive modifier dictionary count is invalid: {inner_count}"
                )
            for inner_index in range(inner_count):
                inner_entry = (
                    inner_entries
                    + self.DICT_ENTRY_START_OFFSET
                    + inner_index * self.DICT_ENTRY_SIZE
                )
                if self.memory.read_i32(
                    inner_entry + self.DICT_ENTRY_HASH_CODE_OFFSET
                ) < 0:
                    continue
                modify_type = self.memory.read_i32(
                    inner_entry + self.DICT_ENTRY_KEY_OFFSET
                )
                modifier_ptr = self.memory.read_ptr(
                    inner_entry + self.DICT_ENTRY_VALUE_OFFSET
                )
                if not modifier_ptr:
                    continue
                stat_id = self.memory.read_i32(
                    modifier_ptr + self.STAT_MODIFIER_STAT_OFFSET
                )
                if stat_id != outer_stat_id:
                    continue
                label, value_format = self._resolve_stat_display(stat_id)
                modifiers.append(
                    PlayerStatModifierSnapshot(
                        stat_id=stat_id,
                        label=label,
                        value=self.memory.read_float(
                            modifier_ptr + self.STAT_MODIFIER_VALUE_OFFSET
                        ),
                        value_format=value_format,
                        object_ptr=modifier_ptr,
                        modify_type=modify_type,
                    )
                )
        return tuple(modifiers)

    def _read_object_class_name(self, object_ptr: int) -> str | None:
        class_ptr = self.memory.read_ptr(object_ptr + self.OBJECT_KLASS_OFFSET)
        if not class_ptr:
            return None
        name_ptr = self.memory.read_ptr(class_ptr + self.KLASS_NAME_PTR_OFFSET)
        return self.memory.read_ascii_string(name_ptr) if name_ptr else None

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
            # A partial persistent set is not a usable sample: callers cannot
            # distinguish a recovered old entry from a newly banished item.
            item_id = self.memory.read_i32(value + self.ITEM_DATA_ENUM_OFFSET)
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
            klass = self.memory.read_ptr(value + self.OBJECT_KLASS_OFFSET)
            if not klass:
                raise MemoryReadError("Banished upgradable class pointer is null.")
            name_ptr = self.memory.read_ptr(klass + self.KLASS_NAME_PTR_OFFSET)
            if not name_ptr:
                raise MemoryReadError("Banished upgradable class name pointer is null.")
            class_name = self.memory.read_ascii_string(name_ptr)
            if not class_name:
                raise MemoryReadError("Banished upgradable class name is unreadable.")

            if class_name == "TomeData":
                tome_id = self.memory.read_i32(value + self.TOME_DATA_ENUM_OFFSET)
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
            if not value:
                raise MemoryReadError("Active banish HashSet slot has a null value.")
            values.append(value)
        if len(values) != count:
            raise MemoryReadError(
                f"Banish HashSet read is partial: expected {count}, got {len(values)}"
            )
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
