"""Immutable input contract for recording one VOD snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from core.character_passives import CharacterPassiveSnapshot
from core.stats.types import (
    ChaosTomeSnapshot,
    ChargeShrineSnapshot,
    DamageSourceSnapshot,
    PlayerStatValue,
    TomeSnapshot,
    WeaponSnapshot,
)


@dataclass(frozen=True, slots=True)
class VodCapturePayload:
    stats: Mapping[str, PlayerStatValue]
    items: tuple[str, ...] = ()
    weapons: tuple[WeaponSnapshot, ...] = ()
    tomes: tuple[TomeSnapshot, ...] = ()
    banishes: tuple[str, ...] = ()
    damage_sources: tuple[DamageSourceSnapshot, ...] = ()
    chaos_tome: ChaosTomeSnapshot | None = None
    shrines: ChargeShrineSnapshot | None = None
    character_passive: CharacterPassiveSnapshot | None = None
    chests_per_minute: float | None = None
    game_time_seconds: float | None = None
    mob_kills: int | None = None
    kps_at_capture: int | None = None
    minute_avg_kps_at_capture: int | None = None
    five_minute_avg_kps_at_capture: int | None = None
    run_avg_kps_at_capture: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0
    stage_index: int | None = None
    stage_time_seconds: float | None = None
    chests_opened: int | None = None
    chests_total: int | None = None
    pots_total: int | None = None
    paid_chests: int | None = None
    key_procs: int | None = None
    free_chests: int | None = None
    keys_count: int | None = None
    expected_key_procs: float | None = None
    chests_opened_by_stage: Mapping[int, int] | None = None
    chests_total_by_stage: Mapping[int, int] | None = None
    loot_actual: Mapping[str, int] | None = None
    loot_expected: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stats", MappingProxyType(dict(self.stats)))
        for name in (
            "chests_opened_by_stage",
            "chests_total_by_stage",
            "loot_actual",
            "loot_expected",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, MappingProxyType(dict(value)))
