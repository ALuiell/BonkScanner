from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Protocol, Callable

from memory import MemoryReadError, ProcessMemory


class MemoryReader(Protocol):
    def module_offset(self, module_name: str, offset: int) -> int:
        ...

    def read_ptr(self, address: int) -> int:
        ...

    def read_i32(self, address: int) -> int:
        ...

    def read_u8(self, address: int) -> int:
        ...

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        ...

    def scan_all(self, pattern: bytes) -> list[int]:
        ...


class MapStat(Enum):
    BOSS_CURSES = "boss_curses"
    CHALLENGES = "challenges"
    CHARGE_SHRINES = "charge_shrines"
    CHESTS = "chests"
    GREED_SHRINES = "greed_shrines"
    MAGNET_SHRINES = "magnet_shrines"
    MICROWAVES = "microwaves"
    MOAIS = "moais"
    POTS = "pots"
    SHADY_GUY = "shady_guy"


class EItem(IntEnum):
    Key = 0
    Beer = 1
    SpikyShield = 2
    Bonker = 3
    SlipperyRing = 4
    CowardsCloak = 5
    GymSauce = 6
    Battery = 7
    PhantomShroud = 8
    ForbiddenJuice = 9
    DemonBlade = 10
    GrandmasSecretTonic = 11
    GiantFork = 12
    MoldyCheese = 13
    GoldenSneakers = 14
    SpicyMeatball = 15
    Chonkplate = 16
    LightningOrb = 17
    IceCube = 18
    DemonicBlood = 19
    DemonicSoul = 20
    BeefyRing = 21
    Dragonfire = 22
    GoldenGlove = 23
    GoldenShield = 24
    ZaWarudo = 25
    OverpoweredLamp = 26
    Feathers = 27
    Ghost = 28
    SluttyCannon = 29
    TurboSocks = 30
    ShatteredWisdom = 31
    EchoShard = 32
    SuckyMagnet = 33
    Backpack = 34
    Clover = 35
    Campfire = 36
    Rollerblades = 37
    Skuleg = 38
    EagleClaw = 39
    Scarf = 40
    Anvil = 41
    Oats = 42
    CursedDoll = 43
    EnergyCore = 44
    ElectricPlug = 45
    BobDead = 46
    SoulHarvester = 47
    Mirror = 48
    JoesDagger = 49
    WeebHeadset = 50
    SpeedBoi = 51
    Gasmask = 52
    ToxicBarrel = 53
    HolyBook = 54
    BrassKnuckles = 55
    IdleJuice = 56
    Kevin = 57
    Borgar = 58
    Medkit = 59
    GamerGoggles = 60
    UnstableTransfusion = 61
    BloodyCleaver = 62
    CreditCardRed = 63
    CreditCardGreen = 64
    BossBuster = 65
    LeechingCrystal = 66
    TacticalGlasses = 67
    Cactus = 68
    CageKey = 69
    IceCrystal = 70
    TimeBracelet = 71
    GloveLightning = 72
    GlovePoison = 73
    GloveBlood = 74
    GloveCurse = 75
    GlovePower = 76
    Wrench = 77
    Beacon = 78
    GoldenRing = 79
    QuinsMask = 80
    CryptKey = 81
    OldMask = 82
    Snek = 83
    Pot = 84
    BobsLantern = 85
    Pumpkin = 86
    WizardsHat = 87


class EItemRarity(IntEnum):
    Common = 0
    Rare = 1
    Epic = 2
    Legendary = 3
    Corrupted = 4
    Quest = 5


@dataclass(frozen=True)
class StatValue:
    current: int
    max: int


type ShadyGuyVendorItems = dict[int, list[EItem]]


@dataclass(frozen=True)
class MapGenerationState:
    is_generating: bool = False
    map_seed: int | None = None
    current_map_ptr: int = 0
    current_stage_ptr: int = 0
    is_resetting: bool = False

    @property
    def has_loaded_map(self) -> bool:
        return bool(self.current_map_ptr and self.current_stage_ptr)


class GameDataClient:
    TYPE_INFO_OFFSET = 0x2FB5E68
    SHADY_GUY_TYPE_INFO_OFFSET = 0x2FB5928
    MAP_CONTROLLER_TYPE_INFO_OFFSET = 0x2F58E08
    MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET = 0x2F59000
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    MAP_CONTROLLER_CURRENT_MAP_OFFSET = 0x10
    MAP_CONTROLLER_CURRENT_STAGE_OFFSET = 0x18
    MAP_CONTROLLER_RESETING_OFFSET = 0x21
    MAP_GENERATION_IS_GENERATING_OFFSET = 0x10
    MAP_GENERATION_MAP_SEED_OFFSET = 0x2C
    DICT_ENTRIES_OFFSET = 0x18
    DICT_COUNT_OFFSET = 0x20
    ENTRY_BASE_OFFSET = 0x20
    ENTRY_SIZE = 0x18
    ENTRY_KEY_OFFSET = 0x8
    ENTRY_VALUE_OFFSET = 0x10
    CONTAINER_MAX_OFFSET = 0x10
    CONTAINER_CURRENT_OFFSET = 0x14
    OBJECT_MONITOR_OFFSET = 0x8
    OBJECT_CACHED_PTR_OFFSET = 0x10
    SHADY_GUY_RARITY_OFFSET = 0x90
    SHADY_GUY_ITEMS_OFFSET = 0x98
    SHADY_GUY_PRICES_OFFSET = 0xA0
    MANAGED_LIST_ARRAY_OFFSET = 0x10
    MANAGED_LIST_COUNT_OFFSET = 0x18
    MANAGED_ARRAY_ITEMS_OFFSET = 0x20
    ITEM_DATA_EITEM_OFFSET = 0x54
    ITEM_DATA_RARITY_OFFSET = 0x60
    MAX_DICT_ENTRIES = 4096
    MAX_SHADY_GUY_CANDIDATES = 512
    MAX_SHADY_GUY_ITEMS = 16

    LABEL_TO_STAT = {
        "Boss Curses": MapStat.BOSS_CURSES,
        "Challenges": MapStat.CHALLENGES,
        "Charge Shrines": MapStat.CHARGE_SHRINES,
        "Chests": MapStat.CHESTS,
        "Greed Shrines": MapStat.GREED_SHRINES,
        "Magnet Shrines": MapStat.MAGNET_SHRINES,
        "Microwaves": MapStat.MICROWAVES,
        "Moais": MapStat.MOAIS,
        "Pots": MapStat.POTS,
        "Shady Guy": MapStat.SHADY_GUY,
    }
    EXPECTED_READY_STATS = frozenset(LABEL_TO_STAT.values())

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

    def __enter__(self) -> "GameDataClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_map_generation_state(self) -> MapGenerationState:
        map_generation_static_fields = self._read_static_fields(
            self.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET,
        )
        map_controller_static_fields = self._read_static_fields(
            self.MAP_CONTROLLER_TYPE_INFO_OFFSET,
        )

        if not map_generation_static_fields and not map_controller_static_fields:
            return MapGenerationState()

        is_generating = self._read_bool(
            map_generation_static_fields,
            self.MAP_GENERATION_IS_GENERATING_OFFSET,
        )
        map_seed = self._read_i32_optional(
            map_generation_static_fields,
            self.MAP_GENERATION_MAP_SEED_OFFSET,
        )
        current_map_ptr = self._read_ptr_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_CURRENT_MAP_OFFSET,
        )
        current_stage_ptr = self._read_ptr_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_CURRENT_STAGE_OFFSET,
        )
        is_resetting = self._read_bool(
            map_controller_static_fields,
            self.MAP_CONTROLLER_RESETING_OFFSET,
        )

        return MapGenerationState(
            is_generating=is_generating,
            map_seed=map_seed,
            current_map_ptr=current_map_ptr,
            current_stage_ptr=current_stage_ptr,
            is_resetting=is_resetting,
        )

    def wait_for_map_ready(
        self,
        previous_seed: int | None = None,
        *,
        previous_state: MapGenerationState | None = None,
        previous_stats: dict[MapStat, StatValue] | None = None,
        require_change: bool = True,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
        abort_condition: Callable[[], bool] | None = None,
    ) -> dict[MapStat, StatValue]:
        deadline = time.monotonic() + timeout
        generation_seen = False
        map_change_seen = False
        baseline_seed = (
            previous_state.map_seed
            if previous_state is not None and previous_state.map_seed is not None
            else previous_seed
        )
        baseline_map_ptr = (
            previous_state.current_map_ptr
            if previous_state is not None and previous_state.current_map_ptr
            else None
        )
        baseline_stage_ptr = (
            previous_state.current_stage_ptr
            if previous_state is not None and previous_state.current_stage_ptr
            else None
        )
        baseline_stats = self._normalize_ready_stats(previous_stats) if previous_stats is not None else None
        stable_stats: dict[MapStat, StatValue] | None = None
        ready_raw_stats: dict[MapStat, StatValue] | None = None
        stable_stats_seen = False
        last_stats_count = 0
        zero_defaulted_stats: set[MapStat] = set(self.EXPECTED_READY_STATS)
        last_state = MapGenerationState()
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            if abort_condition is not None and abort_condition():
                raise InterruptedError("Wait aborted by user.")

            try:
                last_state = self.get_map_generation_state()
                generation_seen = generation_seen or last_state.is_generating
                map_change_seen = map_change_seen or generation_seen

                if (
                    baseline_seed is not None
                    and last_state.map_seed is not None
                    and last_state.map_seed != baseline_seed
                ):
                    map_change_seen = True
                if (
                    baseline_map_ptr is not None
                    and last_state.current_map_ptr
                    and last_state.current_map_ptr != baseline_map_ptr
                ):
                    map_change_seen = True
                if (
                    baseline_stage_ptr is not None
                    and last_state.current_stage_ptr
                    and last_state.current_stage_ptr != baseline_stage_ptr
                ):
                    map_change_seen = True

                stats = self.get_map_stats()
                ready_stats = self._normalize_ready_stats(stats)
                last_stats_count = len(stats)
                zero_defaulted_stats = self.EXPECTED_READY_STATS.difference(stats.keys())
                if baseline_stats is None:
                    baseline_stats = ready_stats
                elif ready_stats != baseline_stats:
                    map_change_seen = True

                if (
                    (not require_change or generation_seen or map_change_seen)
                    and not last_state.is_generating
                    and not last_state.is_resetting
                    and last_state.has_loaded_map
                    and self._is_ready_stats(stats)
                ):
                    if ready_stats == stable_stats and ready_raw_stats is not None:
                        return ready_raw_stats
                    stable_stats = ready_stats
                    ready_raw_stats = stats
                    stable_stats_seen = True
                else:
                    stable_stats = None
                    ready_raw_stats = None
            except MemoryReadError as exc:
                last_error = exc
                stable_stats = None
                ready_raw_stats = None

            time.sleep(poll_interval)

        error_text = (
            f"Timed out waiting for map readiness after {timeout:.1f}s. "
            f"Last state: {last_state}. "
            f"change_seen={map_change_seen}, generation_seen={generation_seen}, "
            f"stats_count={last_stats_count}, "
            f"zero_defaulted_stats={self._format_stats(zero_defaulted_stats)}, "
            f"stable_stats_seen={stable_stats_seen}."
        )
        if last_error is not None:
            error_text += f" Last memory error: {last_error}"
        raise TimeoutError(error_text)

    def get_map_stats(self) -> dict[MapStat, StatValue]:
        stats: dict[MapStat, StatValue] = {}

        type_info_address = self.memory.module_offset(
            self.module_name,
            self.TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            return stats

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            return stats

        interactables_dict = self.memory.read_ptr(static_fields)
        if not interactables_dict:
            return stats

        entries = self.memory.read_ptr(interactables_dict + self.DICT_ENTRIES_OFFSET)
        count = self.memory.read_i32(interactables_dict + self.DICT_COUNT_OFFSET)

        if not entries:
            return stats

        if count < 0 or count > self.MAX_DICT_ENTRIES:
            raise MemoryReadError(f"Interactables dictionary count is invalid: {count}")

        for index in range(count):
            interactables_entry = entries + self.ENTRY_BASE_OFFSET + (index * self.ENTRY_SIZE)

            try:
                key_ptr = self.memory.read_ptr(interactables_entry + self.ENTRY_KEY_OFFSET)
                value_ptr = self.memory.read_ptr(interactables_entry + self.ENTRY_VALUE_OFFSET)
            except MemoryReadError:
                continue

            if not key_ptr or not value_ptr:
                continue

            label = self.memory.read_mono_string(key_ptr)
            if not label:
                continue

            stat = self.LABEL_TO_STAT.get(label)
            if stat is None:
                continue

            try:
                max_value = self.memory.read_i32(value_ptr + self.CONTAINER_MAX_OFFSET)
                current_value = self.memory.read_i32(value_ptr + self.CONTAINER_CURRENT_OFFSET)
            except MemoryReadError:
                continue

            stats[stat] = StatValue(current=current_value, max=max_value)

        return stats

    def get_shady_guy_items(self) -> list[EItem]:
        vendor_items = self.get_shady_guy_vendor_items()
        items: list[EItem] = []

        for vendor_address in sorted(vendor_items):
            items.extend(vendor_items[vendor_address])

        return items

    def get_shady_guy_vendor_items(self) -> ShadyGuyVendorItems:
        class_ptr = self._read_type_info_class(self.SHADY_GUY_TYPE_INFO_OFFSET)
        if not class_ptr:
            return {}

        candidates = self.memory.scan_all(class_ptr.to_bytes(8, "little") + b"\x00" * 8)
        if len(candidates) > self.MAX_SHADY_GUY_CANDIDATES:
            raise MemoryReadError(
                f"Shady Guy candidate count is invalid: {len(candidates)}"
            )

        vendor_items: ShadyGuyVendorItems = {}
        for candidate in sorted(candidates):
            items = self._read_shady_guy_vendor_items(candidate)
            if items:
                vendor_items[candidate] = items

        return vendor_items

    def _read_static_fields(self, type_info_offset: int) -> int:
        try:
            class_ptr = self._read_type_info_class(type_info_offset)
            if not class_ptr:
                return 0
            return self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        except MemoryReadError:
            return 0

    def _read_type_info_class(self, type_info_offset: int) -> int:
        type_info_address = self.memory.module_offset(self.module_name, type_info_offset)
        return self.memory.read_ptr(type_info_address)

    def _read_bool(self, base_address: int, offset: int) -> bool:
        if not base_address:
            return False
        try:
            return self.memory.read_u8(base_address + offset) != 0
        except MemoryReadError:
            return False

    def _read_i32_optional(self, base_address: int, offset: int) -> int | None:
        if not base_address:
            return None
        try:
            return self.memory.read_i32(base_address + offset)
        except MemoryReadError:
            return None

    def _read_ptr_optional(self, base_address: int, offset: int) -> int:
        if not base_address:
            return 0
        try:
            return self.memory.read_ptr(base_address + offset)
        except MemoryReadError:
            return 0

    def _read_shady_guy_vendor_items(self, vendor_address: int) -> list[EItem]:
        try:
            if self.memory.read_ptr(vendor_address + self.OBJECT_MONITOR_OFFSET) != 0:
                return []
            if self.memory.read_ptr(vendor_address + self.OBJECT_CACHED_PTR_OFFSET) == 0:
                return []

            EItemRarity(self.memory.read_i32(vendor_address + self.SHADY_GUY_RARITY_OFFSET))
            items_list = self.memory.read_ptr(vendor_address + self.SHADY_GUY_ITEMS_OFFSET)
            prices_list = self.memory.read_ptr(vendor_address + self.SHADY_GUY_PRICES_OFFSET)
            if not items_list or not prices_list:
                return []

            item_ptrs = self._read_managed_pointer_list(items_list, self.MAX_SHADY_GUY_ITEMS)
            if not item_ptrs:
                return []

            prices = self._read_managed_i32_list(prices_list, self.MAX_SHADY_GUY_ITEMS)
            if len(prices) != len(item_ptrs):
                return []

            items: list[EItem] = []
            for item_ptr in item_ptrs:
                item_value = self.memory.read_i32(item_ptr + self.ITEM_DATA_EITEM_OFFSET)
                item_rarity = self.memory.read_i32(item_ptr + self.ITEM_DATA_RARITY_OFFSET)
                EItemRarity(item_rarity)
                items.append(EItem(item_value))

            return items
        except (MemoryReadError, ValueError):
            return []

    def _read_managed_pointer_list(self, list_address: int, max_entries: int) -> list[int]:
        array_address = self.memory.read_ptr(list_address + self.MANAGED_LIST_ARRAY_OFFSET)
        count = self.memory.read_i32(list_address + self.MANAGED_LIST_COUNT_OFFSET)
        if not array_address or count <= 0:
            return []
        if count > max_entries:
            raise MemoryReadError(
                f"Managed pointer list count is invalid: {count}"
            )

        return [
            self.memory.read_ptr(array_address + self.MANAGED_ARRAY_ITEMS_OFFSET + (index * 8))
            for index in range(count)
            if self.memory.read_ptr(array_address + self.MANAGED_ARRAY_ITEMS_OFFSET + (index * 8))
        ]

    def _read_managed_i32_list(self, list_address: int, max_entries: int) -> list[int]:
        array_address = self.memory.read_ptr(list_address + self.MANAGED_LIST_ARRAY_OFFSET)
        count = self.memory.read_i32(list_address + self.MANAGED_LIST_COUNT_OFFSET)
        if not array_address or count <= 0:
            return []
        if count > max_entries:
            raise MemoryReadError(
                f"Managed int list count is invalid: {count}"
            )

        return [
            self.memory.read_i32(array_address + self.MANAGED_ARRAY_ITEMS_OFFSET + (index * 4))
            for index in range(count)
        ]

    def _is_ready_stats(self, stats: dict[MapStat, StatValue]) -> bool:
        return bool(stats)

    def _normalize_ready_stats(
        self,
        stats: dict[MapStat, StatValue],
    ) -> dict[MapStat, StatValue]:
        return {
            stat: stats.get(stat, StatValue(current=0, max=0))
            for stat in self.EXPECTED_READY_STATS
        }

    def _format_stats(self, stats: set[MapStat]) -> str:
        if not stats:
            return "none"
        return ",".join(sorted(stat.value for stat in stats))
