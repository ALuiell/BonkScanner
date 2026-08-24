"""Charge Shrine reward attribution and immutable snapshots.

``ShrineLogs.shownLog`` is deliberately not treated as a Charge Shrine-only
log. Gritch/Greed and several encounter effects write to the same list. A
rising ``AchievementTracker.chargedShrines`` counter creates a reward budget;
only a modifier with a dump-derived Charge Shrine fingerprint may spend it.
Spawn totals, maps and stage coverage are outside this feature's contract.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isclose, isfinite
import struct

from core.stats.formats import PlayerStatFormat
from core.stats.types import (
    ChargeShrineLogEntry,
    ChargeShrineReading,
    ChargeShrineSnapshot,
    ChargeShrineStatSnapshot,
    PLAYER_STAT_SPEC_BY_LABEL,
)


@dataclass(frozen=True)
class ShrineStatRule:
    label: str
    base_value: float
    modify_type: int
    value_format: PlayerStatFormat


def _rule(label: str, base_value: float, modify_type: int) -> ShrineStatRule:
    spec = PLAYER_STAT_SPEC_BY_LABEL[label]
    return ShrineStatRule(label, base_value, modify_type, spec.value_format)


# EncounterUtility.GetRandomStatValue (RVA 0x436B10), limited to the 28 values
# inserted into upgradableStats in EncounterUtility..cctor (RVA 0x437260).
SHRINE_STAT_RULES: dict[int, ShrineStatRule] = {
    0: _rule("Max HP", 15.0, 2),
    1: _rule("HP Regen", 20.0, 2),
    2: _rule("Shield", 5.0, 2),
    3: _rule("Thorns", 5.0, 2),
    4: _rule("Armor", 0.05, 2),
    5: _rule("Evasion", 0.05, 2),
    9: _rule("Size", 0.08, 0),
    10: _rule("Duration", 0.08, 0),
    11: _rule("Projectile Speed", 0.10, 0),
    12: _rule("Damage", 0.12, 0),
    15: _rule("Attack Speed", 0.06, 0),
    16: _rule("Projectile Count", 1.0, 2),
    17: _rule("Lifesteal", 0.06, 2),
    18: _rule("Crit Chance", 0.05, 2),
    19: _rule("Crit Damage", 0.10, 0),
    23: _rule("Damage to Elites", 0.10, 0),
    24: _rule("Knockback", 0.10, 0),
    25: _rule("Movement Speed", 0.08, 0),
    # Jump Height is not part of the ordinary live stat table (its spec has no
    # memory slot and therefore uses a flat placeholder format), but the shrine
    # modifier is an additive multiplier and is displayed as a percentage.
    26: ShrineStatRule("Jump Height", 0.10, 0, PlayerStatFormat.MULTIPLIER),
    29: _rule("Pickup Range", 0.20, 0),
    30: _rule("Luck", 0.05, 2),
    31: _rule("Gold Gain", 0.075, 0),
    32: _rule("XP Gain", 0.075, 0),
    38: _rule("Difficulty", 0.08, 2),
    39: _rule("Elite Spawn Increase", 0.15, 0),
    40: _rule("Powerup Multiplier", 0.10, 0),
    41: _rule("Powerup Drop Chance", 0.05, 0),
    46: _rule("Extra Jumps", 1.0, 2),
}

SHRINE_STAT_ORDER = {stat_id: index for index, stat_id in enumerate(SHRINE_STAT_RULES)}
SHRINE_RARITY_MULTIPLIERS: tuple[tuple[str, float], ...] = (
    ("Common", 1.0),
    ("Uncommon", 1.2),
    ("Rare", 1.4),
    ("Epic", 1.6),
    ("Legendary", 2.0),
)
SHRINE_WRENCH_BONUS_PER_STACK = 0.075
# The shrine presents three offers, but only the one the player selects is
# appended to ``ShrineLogs.shownLog`` and becomes a permanent modifier.
SHRINE_SELECTED_REWARDS_PER_CHARGE = 1
SHRINE_VALUE_ABS_TOLERANCE = 2.5e-5
MAX_INFERRED_WRENCH_STACKS = 10_000


@dataclass(frozen=True)
class ShrineRewardMatch:
    rarity: str | None
    wrench_stacks: int | None
    ambiguous: bool = False


@dataclass(frozen=True)
class _PendingReward:
    wrench_stacks: int | None


@dataclass(frozen=True)
class _ShrineEvent:
    object_ptr: int
    stat_id: int
    value: float
    rarity: str | None
    wrench_stacks: int | None


@dataclass
class _ShrineState:
    initialized: bool = False
    last_charged_total: int = 0
    seen_log_ptrs: set[int] = field(default_factory=set)
    deferred_log_ptrs: set[int] = field(default_factory=set)
    pending: deque[_PendingReward] = field(default_factory=deque)
    events: list[_ShrineEvent] = field(default_factory=list)
    ambiguous_matches: int = 0


def reset(state: _ShrineState) -> None:
    state.initialized = False
    state.last_charged_total = 0
    state.seen_log_ptrs.clear()
    state.deferred_log_ptrs.clear()
    state.pending.clear()
    state.events.clear()
    state.ambiguous_matches = 0


def update(
    state: _ShrineState,
    reading: ChargeShrineReading,
    *,
    wrench_stacks: int | None,
) -> None:
    charged_total = max(0, int(reading.charged_total))
    if wrench_stacks is not None:
        wrench_stacks = max(0, int(wrench_stacks))

    if state.initialized and charged_total < state.last_charged_total:
        reset(state)

    if not state.initialized:
        _initialize_from_reading(
            state,
            reading,
            wrench_stacks=wrench_stacks,
        )
        return

    charged_delta = charged_total - state.last_charged_total
    for _ in range(max(0, charged_delta) * SHRINE_SELECTED_REWARDS_PER_CHARGE):
        state.pending.append(_PendingReward(wrench_stacks))

    for entry in reading.shown_log:
        object_ptr = int(entry.object_ptr)
        if not object_ptr or object_ptr in state.seen_log_ptrs:
            continue
        if _consume_log_entry(state, entry):
            state.seen_log_ptrs.add(object_ptr)
            state.deferred_log_ptrs.discard(object_ptr)
            continue
        match = match_shrine_reward(entry, wrench_stacks=None)
        if match is None:
            state.seen_log_ptrs.add(object_ptr)
            state.deferred_log_ptrs.discard(object_ptr)
            continue
        # A compatible reward observed without a budget can be the narrow
        # log-before-counter race described by the memory reader. Give it one
        # following sample to receive that budget, then retire it: ShrineLogs
        # is shared, so an unbounded grace period lets old modded effects spend
        # unrelated future Charge Shrine rewards.
        if object_ptr in state.deferred_log_ptrs:
            state.deferred_log_ptrs.remove(object_ptr)
            state.seen_log_ptrs.add(object_ptr)
        else:
            state.deferred_log_ptrs.add(object_ptr)

    state.last_charged_total = charged_total


def _initialize_from_reading(
    state: _ShrineState,
    reading: ChargeShrineReading,
    *,
    wrench_stacks: int | None,
) -> None:
    charged_total = max(0, int(reading.charged_total))
    state.initialized = True
    state.last_charged_total = charged_total
    state.deferred_log_ptrs.clear()
    state.seen_log_ptrs = {
        int(entry.object_ptr) for entry in reading.shown_log if int(entry.object_ptr)
    }

    compatible: list[tuple[ChargeShrineLogEntry, ShrineRewardMatch]] = []
    for entry in reading.shown_log:
        match = match_shrine_reward(entry, wrench_stacks=None)
        if match is not None:
            compatible.append((entry, match))

    expected_rewards = charged_total * SHRINE_SELECTED_REWARDS_PER_CHARGE
    selected = compatible[-expected_rewards:] if expected_rewards else []
    for entry, match in selected:
        _record_event(state, entry, match)

    unmatched = max(0, expected_rewards - len(selected))
    for _ in range(unmatched):
        state.pending.append(_PendingReward(wrench_stacks))


def _consume_log_entry(state: _ShrineState, entry: ChargeShrineLogEntry) -> bool:
    if not state.pending:
        return False
    pending = state.pending[0]
    match = match_shrine_reward(entry, wrench_stacks=pending.wrench_stacks)
    if match is None:
        # Inventory and reward writes are not atomic. The shared item sample is
        # normally exact, but inference keeps a valid reward from getting stuck
        # forever if Wrench changed across that tiny boundary.
        match = match_shrine_reward(entry, wrench_stacks=None)
    if match is None:
        return False
    state.pending.popleft()
    _record_event(state, entry, match)
    return True


def _record_event(
    state: _ShrineState,
    entry: ChargeShrineLogEntry,
    match: ShrineRewardMatch,
) -> None:
    state.events.append(
        _ShrineEvent(
            object_ptr=int(entry.object_ptr),
            stat_id=int(entry.stat_id),
            value=float(entry.value),
            rarity=match.rarity,
            wrench_stacks=match.wrench_stacks,
        )
    )
    if match.ambiguous:
        state.ambiguous_matches += 1


def match_shrine_reward(
    entry: ChargeShrineLogEntry,
    *,
    wrench_stacks: int | None,
) -> ShrineRewardMatch | None:
    rule = SHRINE_STAT_RULES.get(int(entry.stat_id))
    if rule is None or int(entry.modify_type) != rule.modify_type:
        return None
    try:
        value = float(entry.value)
    except (TypeError, ValueError):
        return None
    if not isfinite(value):
        return None

    candidates: list[tuple[str, int]] = []
    for rarity, rarity_multiplier in SHRINE_RARITY_MULTIPLIERS:
        rounded_base = _rounded_rarity_value(rule.base_value, rarity_multiplier)
        if wrench_stacks is None:
            if rounded_base == 0.0:
                continue
            inferred = round(((value / rounded_base) - 1.0) / SHRINE_WRENCH_BONUS_PER_STACK)
            if not 0 <= inferred <= MAX_INFERRED_WRENCH_STACKS:
                continue
            stacks = int(inferred)
        else:
            stacks = max(0, int(wrench_stacks))
        expected = _expected_reward_value(rounded_base, stacks)
        if isclose(value, expected, rel_tol=1e-5, abs_tol=SHRINE_VALUE_ABS_TOLERANCE):
            candidates.append((rarity, stacks))

    if not candidates:
        return None
    unique = tuple(dict.fromkeys(candidates))
    if len(unique) == 1:
        rarity, stacks = unique[0]
        return ShrineRewardMatch(rarity, stacks, False)
    return ShrineRewardMatch(None, None, True)


def snapshot(state: _ShrineState) -> ChargeShrineSnapshot | None:
    if not state.initialized:
        return None
    return ChargeShrineSnapshot(
        charged=state.last_charged_total,
        selected=len(state.events),
        pending=len(state.pending),
        stats=_aggregate_events(tuple(state.events)),
        ambiguous_matches=state.ambiguous_matches,
    )


def _aggregate_events(events: tuple[_ShrineEvent, ...]) -> tuple[ChargeShrineStatSnapshot, ...]:
    totals: dict[int, list] = {}
    for event in events:
        rule = SHRINE_STAT_RULES.get(event.stat_id)
        if rule is None:
            continue
        current = totals.setdefault(event.stat_id, [0.0, 0, {}])
        current[0] += event.value
        current[1] += 1
        if event.rarity:
            current[2][event.rarity] = current[2].get(event.rarity, 0) + 1

    return tuple(
        ChargeShrineStatSnapshot(
            stat_id=stat_id,
            label=SHRINE_STAT_RULES[stat_id].label,
            value=float(values[0]),
            value_format=SHRINE_STAT_RULES[stat_id].value_format,
            rolls=int(values[1]),
            rarity_counts=tuple(
                (rarity, int(values[2][rarity]))
                for rarity, _multiplier in SHRINE_RARITY_MULTIPLIERS
                if rarity in values[2]
            ),
        )
        for stat_id, values in sorted(
            totals.items(), key=lambda item: SHRINE_STAT_ORDER.get(item[0], 999)
        )
    )


def _rounded_rarity_value(base_value: float, rarity_multiplier: float) -> float:
    return float(round(_f32(_f32(base_value) * _f32(rarity_multiplier)), 3))


def _expected_reward_value(rounded_base: float, wrench_stacks: int) -> float:
    multiplier = _f32(
        _f32(1.0)
        + _f32(_f32(SHRINE_WRENCH_BONUS_PER_STACK) * _f32(float(wrench_stacks)))
    )
    return _f32(_f32(rounded_base) * multiplier)


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]
