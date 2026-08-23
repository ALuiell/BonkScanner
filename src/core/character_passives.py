"""Character-passive catalog and immutable cross-layer snapshots.

The game exposes one common identity path for every character, while each
passive has its own runtime contract.  This module keeps that build-independent
catalog and the data boundary shared by memory, tracking, VOD and UI code.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from core.stats.formats import PlayerStatFormat
from core.stats.formatters import (
    format_chaos_tome_stat_delta,
    format_player_stat_delta,
)


class CharacterPassiveStatus(str, Enum):
    SUPPORTED = "supported"
    UPDATING = "updating"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CharacterPassiveEffectKind(str, Enum):
    PERMANENT_LEVEL = "permanent_level"
    PERMANENT_ROLL = "permanent_roll"
    CURRENT_CONDITIONAL = "current_conditional"
    PROGRESS = "progress"
    COUNTER = "counter"


@dataclass(frozen=True)
class LinearPassiveRule:
    stat_id: int
    per_level: float


@dataclass(frozen=True)
class CharacterPassiveSpec:
    character_id: int
    character_name: str
    passive_id: int
    passive_name: str
    runtime_class: str
    linear: LinearPassiveRule | None = None
    is_gamba: bool = False

    @property
    def supported(self) -> bool:
        return self.linear is not None or self.is_gamba


@dataclass(frozen=True)
class CharacterPassiveReading:
    """Validated, read-only runtime input for a passive adapter."""

    character_id: int
    character_name: str
    passive_id: int
    passive_name: str
    runtime_class: str
    passive_object_ptr: int
    level: int
    per_level: float | None = None
    passive_modifiers: tuple[object, ...] = ()
    permanent_modifiers: tuple[object, ...] = ()
    gamba_current_level: int | None = None
    gamba_upgrade_multiplier: float | None = None
    gamba_min_multiplier: float | None = None
    gamba_max_multiplier: float | None = None


@dataclass(frozen=True)
class CharacterPassiveEffectSnapshot:
    key: str
    label: str
    value: float | None
    value_format: PlayerStatFormat
    kind: CharacterPassiveEffectKind
    stat_id: int | None = None
    count: int | None = None

    @property
    def display_delta(self) -> str:
        if self.kind is CharacterPassiveEffectKind.PERMANENT_ROLL:
            return format_chaos_tome_stat_delta(
                self.label, self.value, self.value_format
            )
        return format_player_stat_delta(self.value, self.value_format)


@dataclass(frozen=True)
class CharacterPassiveSnapshot:
    character_id: int
    character_name: str
    passive_id: int
    passive_name: str
    runtime_class: str
    level: int
    status: CharacterPassiveStatus
    effects: tuple[CharacterPassiveEffectSnapshot, ...] = ()
    coverage: str = "identity_only"
    ambiguous: int = 0
    pending: int = 0

    @property
    def supported(self) -> bool:
        return self.status not in {
            CharacterPassiveStatus.UNSUPPORTED,
            CharacterPassiveStatus.UNAVAILABLE,
            CharacterPassiveStatus.UNKNOWN,
        }


def _spec(
    character_id: int,
    character_name: str,
    passive_id: int,
    passive_name: str,
    runtime_class: str,
    *,
    linear: tuple[int, float] | None = None,
    is_gamba: bool = False,
) -> CharacterPassiveSpec:
    return CharacterPassiveSpec(
        character_id=character_id,
        character_name=character_name,
        passive_id=passive_id,
        passive_name=passive_name,
        runtime_class=runtime_class,
        linear=LinearPassiveRule(*linear) if linear is not None else None,
        is_gamba=is_gamba,
    )


# Current-build catalog. Friendly names are the public vocabulary; in
# particular ECharacter.Dicehead is deliberately displayed as "Dice".
CHARACTER_PASSIVE_SPECS: tuple[CharacterPassiveSpec, ...] = (
    _spec(0, "Fox", 1, "RNG Blessing", "PassiveAbilityRngBlessing", linear=(30, 0.015)),
    _spec(1, "Calcium", 2, "Speed Demon", "PassiveAbilitySpeedDemon"),
    _spec(2, "Sir Oofie", 3, "Reinforced", "PassiveAbilityReinforced", linear=(4, 0.01)),
    _spec(3, "Cl4nk", 5, "Crit Happens", "PassiveAbilityCritHappens", linear=(18, 0.01)),
    _spec(4, "Megachad", 7, "Flex", "PassiveAbilityFlex"),
    _spec(5, "Ogre", 6, "Warrior", "PassiveAbilityWarrior", linear=(12, 0.015)),
    _spec(6, "Robinette", 18, "Stonks", "PassiveAbilityStonks"),
    _spec(7, "Athena", 19, "Lock In", "PassiveAbilityLockIn"),
    _spec(8, "Birdo", 10, "Float", "PassiveAbilityFloating"),
    _spec(9, "Bush", 0, "Bullseye", "PassiveAbilityBullseye"),
    _spec(10, "Bandit", 4, "Flowstate", "PassiveAbilityFlowstate", linear=(15, 0.01)),
    _spec(11, "Monke", 8, "Wall Climb", "PassiveAbilityWallClimb", linear=(0, 2.0)),
    _spec(12, "Noelle", 11, "Enduring", "PassiveAbilityEnduring"),
    _spec(13, "Tony McZoom", 20, "Zap", "PassiveAbilityZooma"),
    _spec(14, "Amog", 12, "Plague", "PassiveAbilityPlague"),
    _spec(15, "Spaceman", 13, "Quantum", "PassiveAbilityQuantumXp", linear=(32, 0.01)),
    _spec(16, "Ninja", 14, "Shadowstep", "PassiveAbilityShadowstep"),
    _spec(17, "Vlad", 16, "Vampire", "PassiveAbilityVampire", linear=(17, 0.01)),
    _spec(18, "Dice", 15, "Gamba", "PassiveAbilityGamba", is_gamba=True),
    _spec(19, "Sir Chadwell", 17, "Curse", "PassiveAbilityCurse", linear=(38, 0.01)),
    _spec(20, "Roberto", 21, "Hoarder", "PassiveAbilityHoarder"),
)

CHARACTER_PASSIVE_SPEC_BY_CHARACTER_ID = {
    spec.character_id: spec for spec in CHARACTER_PASSIVE_SPECS
}


def validate_linear_reading(
    spec: CharacterPassiveSpec,
    reading: CharacterPassiveReading,
) -> bool:
    """Check the dump-derived per-level field without trusting exact decimals."""
    if spec.linear is None or reading.per_level is None:
        return False
    value = float(reading.per_level)
    return isfinite(value) and abs(value - spec.linear.per_level) <= 1e-6
