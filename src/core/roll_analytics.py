"""Confirmed lifetime Dice/Chaos roll counts; no rarity or roll-strength estimates."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from core.character_passives import (
    CHARACTER_PASSIVE_SPEC_BY_CHARACTER_ID,
    CharacterPassiveEffectKind,
    CharacterPassiveStatus,
)
from core.stats.types import PLAYER_STAT_GROUPS
from core.tracker.chaos import CHAOS_TOME_GAME_STAT_ORDER

ROLL_SOURCES = ("dice", "chaos")
ROLL_STATS = tuple(
    (spec.stat_id, spec.label)
    for group in PLAYER_STAT_GROUPS for spec in group
    if spec.stat_id in CHAOS_TOME_GAME_STAT_ORDER
)
ROLL_STAT_IDS = frozenset(stat_id for stat_id, _label in ROLL_STATS)


@dataclass(frozen=True, slots=True)
class RollAnalyticsRow:
    stat_id: int
    label: str
    count: int
    percent: float | None


@dataclass(frozen=True, slots=True)
class RollAnalyticsSnapshot:
    source: str
    total: int
    rows: tuple[RollAnalyticsRow, ...]


def aggregate_roll_counts(source: str, counts: dict[int, int]) -> RollAnalyticsSnapshot:
    if source not in ROLL_SOURCES:
        raise ValueError("Unknown roll source")
    total = sum(counts.get(stat_id, 0) for stat_id in ROLL_STAT_IDS)
    return RollAnalyticsSnapshot(source, total, tuple(
        RollAnalyticsRow(stat_id, label, counts.get(stat_id, 0),
                         counts.get(stat_id, 0) / total * 100 if total else None)
        for stat_id, label in ROLL_STATS
    ))


def stable_roll_scope(process_identity: str, owner_stats: int, passive_ptr: int) -> str | None:
    # The passive and owner survive reconnects and change with the character's
    # lifetime. Never use LiveRunTracker's random, scanner-local run UUID here.
    if not process_identity or owner_stats <= 0 or passive_ptr <= 0:
        return None
    return sha256(f"roll-v1:{process_identity}:{owner_stats}:{passive_ptr}".encode()).hexdigest()


def confirmed_roll_counts(chaos, passive) -> dict[str, dict[int, int]]:
    """Withhold incomplete attribution, including legacy stacked minimum counts.

    A later complete snapshot catches up. Unavailable data is never a zero
    checkpoint, and non-Dice passives are never part of this history.
    """
    result = {}
    if chaos is not None and not chaos.ambiguous_rolls:
        counts = {row.stat_id: row.rolls for row in chaos.stats
                  if row.stat_id in ROLL_STAT_IDS and row.rolls > 0}
        if sum(counts.values()) == chaos.level:
            result["chaos"] = counts
    spec = CHARACTER_PASSIVE_SPEC_BY_CHARACTER_ID.get(getattr(passive, "character_id", -1))
    if (spec is not None and spec.is_gamba
            and passive.status == CharacterPassiveStatus.SUPPORTED
            and not passive.pending and not passive.ambiguous):
        result["dice"] = {
            row.stat_id: row.count for row in passive.effects
            if row.kind == CharacterPassiveEffectKind.PERMANENT_ROLL
            and row.stat_id in ROLL_STAT_IDS and row.count is not None and row.count > 0
        }
    return result
