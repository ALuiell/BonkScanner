"""Pure rendering of stat values to display strings."""

from __future__ import annotations

from math import isfinite

from core.stats.formats import (
    CRIT_DAMAGE_BASE_MULTIPLIER,
    PICKUP_RANGE_BASE_METERS,
    PlayerStatFormat,
    WeaponStatFormat,
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


def format_shrine_stat_delta(
    label: str,
    value: float | None,
    value_format: PlayerStatFormat,
) -> str:
    """Format a Charge Shrine bonus with the same stat-specific scales.

    Shrine and Chaos modifiers are stored in the same raw stat units. Pickup
    Range and Crit Damage therefore need the same display conversions; keeping
    this named wrapper lets shrine consumers describe their own domain without
    duplicating those two easily missed rules.
    """
    return format_chaos_tome_stat_delta(label, value, value_format)


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
