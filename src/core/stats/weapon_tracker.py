"""Qt-free effective-stat projection for the native Weapon Tracker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Iterable, Mapping

from core.stats.types import WeaponSnapshot


class WeaponTrackerValueFormat(str, Enum):
    NUMBER = "number"
    INTEGER = "integer"
    MULTIPLIER = "multiplier"
    SECONDS = "seconds"
    PERCENT = "percent"


@dataclass(frozen=True, slots=True)
class WeaponTrackerMetricSpec:
    key: str
    stat_id: int
    player_stat_label: str
    short_label: str
    value_format: WeaponTrackerValueFormat


WEAPON_TRACKER_METRIC_ORDER = (
    "damage",
    "projectile_count",
    "size",
    "duration",
    "crit_chance",
    "crit_damage",
)

DEFAULT_WEAPON_TRACKER_SELECTED_STATS = (
    "damage",
    "projectile_count",
    "size",
)

WEAPON_TRACKER_METRICS: dict[str, WeaponTrackerMetricSpec] = {
    "damage": WeaponTrackerMetricSpec(
        "damage", 12, "Damage", "DMG", WeaponTrackerValueFormat.NUMBER
    ),
    "projectile_count": WeaponTrackerMetricSpec(
        "projectile_count",
        16,
        "Projectile Count",
        "PROJ",
        WeaponTrackerValueFormat.INTEGER,
    ),
    "size": WeaponTrackerMetricSpec(
        "size", 9, "Size", "SIZE", WeaponTrackerValueFormat.MULTIPLIER
    ),
    "duration": WeaponTrackerMetricSpec(
        "duration", 10, "Duration", "DUR", WeaponTrackerValueFormat.SECONDS
    ),
    "crit_chance": WeaponTrackerMetricSpec(
        "crit_chance",
        18,
        "Crit Chance",
        "CRIT",
        WeaponTrackerValueFormat.PERCENT,
    ),
    "crit_damage": WeaponTrackerMetricSpec(
        "crit_damage",
        19,
        "Crit Damage",
        "CRIT DMG",
        WeaponTrackerValueFormat.MULTIPLIER,
    ),
}


@dataclass(frozen=True, slots=True)
class WeaponTrackerMetric:
    key: str
    stat_id: int
    label: str
    value: float

    @property
    def display_value(self) -> str:
        return format_weapon_tracker_value(self.key, self.value)


@dataclass(frozen=True, slots=True)
class WeaponTrackerRow:
    weapon_id: int
    name: str
    level: int
    metrics: tuple[WeaponTrackerMetric, ...]


def normalize_weapon_tracker_metric_keys(value: object) -> tuple[str, ...]:
    """Drop unknown/duplicate metric keys and restore canonical display order."""
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    selected = {item for item in value if isinstance(item, str)}
    return tuple(key for key in WEAPON_TRACKER_METRIC_ORDER if key in selected)


def calculate_weapon_tracker_row(
    weapon: WeaponSnapshot,
    general_stats: Mapping[object, Any],
    selected_metric_keys: Iterable[str],
) -> WeaponTrackerRow | None:
    """Project one weapon, omitting unavailable metrics and empty weapons."""
    selected = set(selected_metric_keys)
    upgrade_stat_ids = set(weapon.upgrade_stat_ids)
    metrics: list[WeaponTrackerMetric] = []

    for key in WEAPON_TRACKER_METRIC_ORDER:
        spec = WEAPON_TRACKER_METRICS[key]
        if key not in selected or spec.stat_id not in upgrade_stat_ids:
            continue

        weapon_value = _finite_value(weapon.full_stats.get(spec.stat_id))
        global_value = _general_stat_value(general_stats, spec)
        if weapon_value is None or global_value is None:
            continue

        value = _calculate_metric_value(
            key,
            weapon,
            weapon_value=weapon_value,
            global_value=global_value,
            general_stats=general_stats,
        )
        if value is None or not isfinite(value):
            continue
        metrics.append(
            WeaponTrackerMetric(
                key=key,
                stat_id=spec.stat_id,
                label=spec.short_label,
                value=float(value),
            )
        )

    if not metrics:
        return None
    return WeaponTrackerRow(
        weapon_id=int(weapon.weapon_id),
        name=str(weapon.name),
        level=max(0, int(weapon.level)),
        metrics=tuple(metrics),
    )


def calculate_weapon_tracker_rows(
    weapons: Iterable[WeaponSnapshot],
    general_stats: Mapping[object, Any],
    selected_metric_keys: Iterable[str],
) -> tuple[WeaponTrackerRow, ...]:
    """Filter a stable reader-ordered inventory without re-sorting it."""
    selected = tuple(selected_metric_keys)
    rows = (
        calculate_weapon_tracker_row(weapon, general_stats, selected)
        for weapon in weapons
    )
    return tuple(row for row in rows if row is not None)


def format_weapon_tracker_value(key: str, value: float) -> str:
    """Format one already-calculated value with the approved tracker unit."""
    spec = WEAPON_TRACKER_METRICS[key]
    if spec.value_format is WeaponTrackerValueFormat.INTEGER:
        return str(int(value))
    if spec.value_format is WeaponTrackerValueFormat.MULTIPLIER:
        return f"×{_format_number(value)}"
    if spec.value_format is WeaponTrackerValueFormat.SECONDS:
        return f"{_format_number(value)}s"
    if spec.value_format is WeaponTrackerValueFormat.PERCENT:
        return f"{_format_number(value * 100.0)}%"
    return _format_number(value)


def _calculate_metric_value(
    key: str,
    weapon: WeaponSnapshot,
    *,
    weapon_value: float,
    global_value: float,
    general_stats: Mapping[object, Any],
) -> float | None:
    # Formula dispatch is intentionally explicit. The supported stats do not
    # share one universal weapon/global operation.
    if key == "damage":
        if weapon.weapon_id == 7:
            thorns = _lookup_general_value(general_stats, "Thorns", 3)
            if thorns is None:
                return None
            return (weapon_value + thorns) * global_value
        return weapon_value * global_value

    if key == "projectile_count":
        # ``int`` truncates toward zero. Shotgun intentionally uses this same
        # underlying stat projection rather than its attack or pellet counts.
        return float(int(max(1.0, weapon_value + int(global_value))))

    if key == "size":
        value = weapon_value * global_value
        cap = _optional_finite_cap(weapon.max_size_multiplier)
        if cap is False:
            return None
        if isinstance(cap, float) and cap > 1.0:
            value = min(value, cap)
        return value

    if key == "duration":
        value = weapon_value * global_value
        cap = _optional_finite_cap(weapon.max_duration)
        if cap is False:
            return None
        if isinstance(cap, float) and cap > 0.0:
            value = min(value, cap)
        return value

    if key == "crit_chance":
        return weapon_value + global_value

    if key == "crit_damage":
        return 2.0 * (weapon_value + global_value)

    return None


def _general_stat_value(
    general_stats: Mapping[object, Any],
    spec: WeaponTrackerMetricSpec,
) -> float | None:
    return _lookup_general_value(general_stats, spec.player_stat_label, spec.stat_id)


def _lookup_general_value(
    general_stats: Mapping[object, Any],
    label: str,
    stat_id: int,
) -> float | None:
    if label in general_stats:
        return _finite_value(general_stats[label])
    return _finite_value(general_stats.get(stat_id))


def _finite_value(value: object) -> float | None:
    raw_value = getattr(value, "value", value)
    try:
        converted = float(raw_value)
    except (TypeError, ValueError):
        return None
    return converted if isfinite(converted) else None


def _optional_finite_cap(value: object) -> float | bool | None:
    if value is None:
        return None
    converted = _finite_value(value)
    return converted if converted is not None else False


def _format_number(value: float) -> str:
    if abs(value) < 0.005:
        value = 0.0
    return f"{value:.2f}".rstrip("0").rstrip(".")
