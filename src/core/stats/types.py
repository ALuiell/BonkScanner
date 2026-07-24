"""Player-stats domain model: snapshots, specs and the memory-reader port.

Qt-free and I/O-free. ``STAT_VALUE_BASE_OFFSET``/``STAT_SLOT_SIZE`` live here
because ``PlayerStatSpec.offset`` derives from them; ``PlayerStatsClient``
re-exposes them as class attributes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite, pi, sqrt
from typing import Protocol

from core.stats.formats import (
    CRIT_DAMAGE_BASE_MULTIPLIER,
    PlayerStatFormat,
    WeaponStatFormat,
)
from core.stats.formatters import (
    format_chaos_tome_stat_delta,
    format_player_stat_delta,
    format_player_stat_value,
    format_weapon_stat_value,
)

STAT_VALUE_BASE_OFFSET = 0x2C
STAT_SLOT_SIZE = 0x10


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
    # The run clock, used to tell a real stage timer from one the game has
    # fast-forwarded. Not the same as ``my_time_seconds``, which is a session
    # clock running since well before the run started.
    run_timer_seconds: float | None
    stage_index: int | None
    stage_time_seconds: float | None
    powerup_multiplier: float | None
    powerup_multiplier_display: str
    final_swarm_timer_seconds: float | None = None
    crypt_timer_seconds: float | None = None
    # ``MapController.isFinalBossStage`` -- the Forest/Desert boss room, the
    # game's own flag. Read from the same static block the stage index comes
    # from, so it costs no extra probe. Graveyard leaves it False and needs its
    # own markers; this field is only load-bearing for the other two maps.
    is_final_boss_stage: bool = False
    # ``GraveyardBossRoom`` flags via the RSG chain -- Graveyard's own boss
    # room, which ``isFinalBossStage`` does not cover (it reads False there).
    # ``fighting`` tracks the live fight and drops at the kill; ``defeated``
    # latches true and is what the tracker keeps for the post-boss phase. Both
    # instantaneous here; the tracker owns the latch so it can reset it per run.
    graveyard_boss_fighting: bool = False
    graveyard_boss_defeated: bool = False
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
        return STAT_VALUE_BASE_OFFSET + (self.stat_id * STAT_SLOT_SIZE)


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


def iter_player_stat_groups(
    stats: dict[str, PlayerStatValue],
) -> tuple[tuple[PlayerStatValue, ...], ...]:
    return tuple(
        tuple(stats[spec.label] for spec in group)
        for group in PLAYER_STAT_GROUPS
    )
