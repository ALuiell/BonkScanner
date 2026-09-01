"""Typed boundary for one coherent full player-memory sample."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from core.stats.types import DamageSourceSnapshot, TomeSnapshot, WeaponSnapshot


@dataclass(frozen=True, slots=True)
class FullPlayerSample:
    stats: Mapping[str, Any]
    items: tuple[str, ...]
    items_available: bool
    weapons: tuple[WeaponSnapshot, ...]
    weapons_available: bool
    tomes: tuple[TomeSnapshot, ...]
    tomes_available: bool
    banishes: tuple[str, ...]
    banishes_available: bool
    damage_sources: tuple[DamageSourceSnapshot, ...]
    damage_sources_available: bool
    run_timer_seconds: float | None
    stage_timer_seconds: float | None
    stage_duration_seconds: float | None
    mob_kills: int | None
    player_level: int | None
    map_seed: int | None
    stage_ptr: int
    stage_index: int | None
    disabled_items: tuple[str, ...]
    disabled_items_available: bool
    is_final_boss_stage: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "stats", MappingProxyType(dict(self.stats)))
        for name in (
            "items",
            "weapons",
            "tomes",
            "banishes",
            "damage_sources",
            "disabled_items",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def as_legacy_tuple(self) -> tuple[Any, ...]:
        return tuple(getattr(self, name) for name in self.__dataclass_fields__)


class PlayerStatsSource(Protocol):
    def read_full_sample(self, context=None) -> FullPlayerSample:
        """Read one coherent full sample, optionally sharing a refresh pass."""
