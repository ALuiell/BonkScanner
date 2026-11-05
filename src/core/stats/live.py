"""Current display values, separate from recorded player snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL, PlayerStatValue


FAST_DISPLAY_STAT_LABELS = ("Luck", "Difficulty", "XP Gain")
LIVE_STAT_TTL_SECONDS = 3.0


@dataclass(frozen=True)
class LiveStatReading:
    value: float
    captured_at: float
    source: str
    ttl_seconds: float = LIVE_STAT_TTL_SECONDS


def merge_live_stats(snapshot, readings, *, now: float) -> dict[str, Any]:
    """Copy the full sample, overriding only with newer, usable observations."""
    stats = dict(getattr(snapshot, "stats", None) or {})
    snapshot_time = float(getattr(snapshot, "captured_at", float("-inf")))
    for label, reading in readings.items():
        full_value = getattr(stats.get(label), "value", None)
        if (
            isfinite(reading.value)
            and 0 <= now - reading.captured_at <= reading.ttl_seconds
            and (reading.captured_at >= snapshot_time or full_value is None or not isfinite(full_value))
        ):
            stats[label] = PlayerStatValue(
                spec=PLAYER_STAT_SPEC_BY_LABEL[label], value=reading.value
            )
    return stats


def current_player_stats(runtime) -> dict[str, Any]:
    """The common live boundary; older fixtures can still supply a full sample."""
    stats = getattr(runtime, "live_stats", None)
    if stats is None:
        stats = getattr(getattr(runtime, "latest_snapshot", None), "stats", None)
    return dict(stats or {})
