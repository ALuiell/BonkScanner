from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
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


class PlayerStatFormat(Enum):
    FLAT = "flat"
    PERCENT = "percent"
    MULTIPLIER = "multiplier"


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
class PlayerStatsSnapshot:
    elapsed_seconds: int
    captured_at: float
    stats: dict[str, PlayerStatValue]

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

    def capture(self, stats: dict[str, PlayerStatValue]) -> PlayerStatsSnapshot:
        now = self.clock()
        start_time = self.start_time if self.start_time is not None else now
        snapshot = PlayerStatsSnapshot(
            elapsed_seconds=int(now - start_time),
            captured_at=now,
            stats=dict(stats),
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
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    STATIC_ROOT_OFFSET = 0x0
    OWNER_STATS_OFFSET = 0x40
    STATS_CONTEXT_OFFSET = 0x10
    STATS_ENTRIES_OFFSET = 0x18
    STAT_VALUE_BASE_OFFSET = 0x2C
    STAT_SLOT_SIZE = 0x10

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

    def get_player_stats(self) -> dict[str, PlayerStatValue]:
        entries = self._resolve_stats_entries()
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

    def _resolve_stats_entries(self) -> int:
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
        stats_context = self.memory.read_ptr(owner_stats + self.STATS_CONTEXT_OFFSET)
        entries = self.memory.read_ptr(stats_context + self.STATS_ENTRIES_OFFSET)
        if not entries:
            raise MemoryReadError("Player stats entries are not initialized.")

        return entries


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


def _format_number(value: float) -> str:
    if abs(value) < 0.0005:
        value = 0.0

    if abs(value - round(value)) < 0.005:
        return str(int(round(value)))

    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")

    return f"{value:.2f}".rstrip("0").rstrip(".")
