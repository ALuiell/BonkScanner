"""Character-passive adapters owned by :class:`LiveRunTracker`."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct
from typing import Any

from core.character_passives import (
    CHARACTER_PASSIVE_SPEC_BY_CHARACTER_ID,
    CharacterPassiveEffectKind,
    CharacterPassiveEffectSnapshot,
    CharacterPassiveReading,
    CharacterPassiveSnapshot,
    CharacterPassiveStatus,
    validate_linear_reading,
)
from core.stats.formats import PlayerStatFormat
from core.tracker.chaos import (
    CHAOS_TOME_BASE_VALUES,
    chaos_tome_stat_sort_key,
)
from core.tracker.shrines import SHRINE_STAT_RULES


GAMBA_RARITY_MULTIPLIERS = (1.0, 1.2, 1.4, 1.6, 2.0)
GAMBA_LEVEL_SPECIFIC_ROLLS = 255
GAMBA_MAX_ULP_DISTANCE = 2


@dataclass
class _GambaTotal:
    stat_id: int
    label: str
    value: float
    value_format: PlayerStatFormat
    rolls: int = 0


@dataclass
class _GambaState:
    current_level: int = 0
    initialized: bool = False
    observed_ptrs: set[int] = field(default_factory=set)
    attributed_ptrs: set[int] = field(default_factory=set)
    assignments: dict[int, tuple[int, Any]] = field(default_factory=dict)
    unresolved_indices: set[int] = field(default_factory=set)
    pending_candidates: dict[int, Any] = field(default_factory=dict)
    contested_ptrs: set[int] = field(default_factory=set)
    totals: dict[int, _GambaTotal] = field(default_factory=dict)
    attributed_rolls: int = 0
    ambiguous: int = 0


@dataclass
class _CharacterPassiveState:
    identity_key: tuple[int, int, str, int] | None = None
    latest: CharacterPassiveSnapshot | None = None
    gamba: _GambaState = field(default_factory=_GambaState)


def reset(state: _CharacterPassiveState) -> None:
    state.identity_key = None
    state.latest = None
    state.gamba = _GambaState()


def update(
    state: _CharacterPassiveState,
    reading: CharacterPassiveReading,
    *,
    reserved_modifier_ptrs: frozenset[int] = frozenset(),
    avoid_chaos_collisions: bool = False,
) -> None:
    identity_key = (
        int(reading.character_id),
        int(reading.passive_id),
        str(reading.runtime_class),
        int(reading.passive_object_ptr),
    )
    if state.identity_key != identity_key:
        reset(state)
        state.identity_key = identity_key

    spec = CHARACTER_PASSIVE_SPEC_BY_CHARACTER_ID.get(int(reading.character_id))
    if spec is None:
        state.latest = _identity_snapshot(
            reading, status=CharacterPassiveStatus.UNKNOWN
        )
        return
    if spec.linear is not None:
        state.latest = _linear_snapshot(spec, reading, previous=state.latest)
        return
    if spec.is_gamba:
        state.latest = _update_gamba(
            state.gamba,
            reading,
            reserved_modifier_ptrs=reserved_modifier_ptrs,
            avoid_chaos_collisions=avoid_chaos_collisions,
        )
        return
    state.latest = _identity_snapshot(
        reading, status=CharacterPassiveStatus.UNSUPPORTED
    )


def snapshot(state: _CharacterPassiveState) -> CharacterPassiveSnapshot | None:
    return state.latest


def claimed_modifier_ptrs(state: _CharacterPassiveState) -> frozenset[int]:
    return frozenset(state.gamba.attributed_ptrs)


def contested_modifier_ptrs(state: _CharacterPassiveState) -> frozenset[int]:
    return frozenset(state.gamba.contested_ptrs)


def _identity_snapshot(
    reading: CharacterPassiveReading,
    *,
    status: CharacterPassiveStatus,
) -> CharacterPassiveSnapshot:
    return CharacterPassiveSnapshot(
        character_id=reading.character_id,
        character_name=reading.character_name,
        passive_id=reading.passive_id,
        passive_name=reading.passive_name,
        runtime_class=reading.runtime_class,
        level=reading.level,
        status=status,
    )


def _linear_snapshot(spec, reading, *, previous) -> CharacterPassiveSnapshot:
    base = dict(
        character_id=reading.character_id,
        character_name=reading.character_name,
        passive_id=reading.passive_id,
        passive_name=reading.passive_name,
        runtime_class=reading.runtime_class,
        level=reading.level,
    )
    if not validate_linear_reading(spec, reading):
        return CharacterPassiveSnapshot(
            **base,
            status=CharacterPassiveStatus.UNAVAILABLE,
            coverage="invalid_runtime_field",
        )

    modifiers = tuple(reading.passive_modifiers)
    expected = _f32(_f32(float(reading.level)) * _f32(float(reading.per_level)))
    if not modifiers:
        if reading.level == 0:
            value = 0.0
            status = CharacterPassiveStatus.SUPPORTED
        else:
            prior_effects = tuple(getattr(previous, "effects", ()))
            if prior_effects:
                return CharacterPassiveSnapshot(
                    **base,
                    status=CharacterPassiveStatus.UPDATING,
                    effects=prior_effects,
                    coverage="runtime_updating",
                    pending=1,
                )
            value = None
            status = CharacterPassiveStatus.UPDATING
    else:
        # PassiveAbility.SetStat owns exactly one entry for this stat/type.
        modifier = modifiers[-1]
        value = float(getattr(modifier, "value", 0.0))
        status = (
            CharacterPassiveStatus.SUPPORTED
            if _ulp_distance(value, expected) <= GAMBA_MAX_ULP_DISTANCE
            else CharacterPassiveStatus.UPDATING
        )
    modifier = modifiers[-1] if modifiers else None
    stat_rule = SHRINE_STAT_RULES.get(spec.linear.stat_id)
    label = str(
        getattr(
            modifier,
            "label",
            stat_rule.label if stat_rule is not None else f"Stat {spec.linear.stat_id}",
        )
    )
    value_format = getattr(
        modifier,
        "value_format",
        stat_rule.value_format if stat_rule is not None else PlayerStatFormat.FLAT,
    )
    effect = CharacterPassiveEffectSnapshot(
        key=f"stat:{spec.linear.stat_id}",
        label=label,
        value=value,
        value_format=value_format,
        kind=CharacterPassiveEffectKind.PERMANENT_LEVEL,
        stat_id=spec.linear.stat_id,
    )
    return CharacterPassiveSnapshot(
        **base,
        status=status,
        effects=(effect,),
        coverage="complete" if status is CharacterPassiveStatus.SUPPORTED else "runtime_updating",
        pending=0 if status is CharacterPassiveStatus.SUPPORTED else 1,
    )


def _update_gamba(
    state: _GambaState,
    reading: CharacterPassiveReading,
    *,
    reserved_modifier_ptrs: frozenset[int],
    avoid_chaos_collisions: bool,
) -> CharacterPassiveSnapshot:
    base = dict(
        character_id=reading.character_id,
        character_name=reading.character_name,
        passive_id=reading.passive_id,
        passive_name=reading.passive_name,
        runtime_class=reading.runtime_class,
        level=reading.level,
    )
    current_level = reading.gamba_current_level
    constants = (
        reading.gamba_upgrade_multiplier,
        reading.gamba_min_multiplier,
        reading.gamba_max_multiplier,
    )
    if current_level is None or any(value is None for value in constants):
        return CharacterPassiveSnapshot(
            **base,
            status=CharacterPassiveStatus.UNAVAILABLE,
            coverage="invalid_runtime_field",
        )
    if not (
        abs(float(constants[0]) - 0.75) <= 1e-6
        and abs(float(constants[1]) - 0.06) <= 1e-6
        and abs(float(constants[2]) - 1.0) <= 1e-6
    ):
        return CharacterPassiveSnapshot(
            **base,
            status=CharacterPassiveStatus.UNAVAILABLE,
            coverage="invalid_runtime_field",
        )

    current_level = max(0, int(current_level))
    if state.initialized and current_level < state.current_level:
        fresh = _GambaState()
        state.__dict__.update(fresh.__dict__)

    # A shrine reservation is an exact source tag. If its log arrives one task
    # after the permanent object, revoke a provisional Dice assignment and put
    # its roll index back into the unresolved budget instead of double-claiming
    # the pointer.
    for ptr in reserved_modifier_ptrs:
        assignment = state.assignments.pop(ptr, None)
        if assignment is None:
            continue
        roll_index, modifier = assignment
        state.attributed_ptrs.discard(ptr)
        state.unresolved_indices.add(roll_index)
        _remove_gamba_total(state, modifier)

    for modifier in reading.permanent_modifiers:
        ptr = int(getattr(modifier, "object_ptr", 0) or 0)
        if not ptr or ptr in state.observed_ptrs:
            continue
        state.observed_ptrs.add(ptr)
        if ptr in reserved_modifier_ptrs or not _is_gamba_pool_candidate(modifier):
            continue
        state.pending_candidates[ptr] = modifier

    for ptr in tuple(state.pending_candidates):
        if ptr in reserved_modifier_ptrs:
            state.pending_candidates.pop(ptr, None)
            state.contested_ptrs.discard(ptr)

    if not state.initialized:
        state.unresolved_indices.update(range(current_level))
        state.initialized = True
    else:
        state.unresolved_indices.update(range(state.current_level, current_level))

    if state.unresolved_indices:
        if avoid_chaos_collisions:
            state.contested_ptrs.update(
                int(getattr(modifier, "object_ptr", 0))
                for modifier in state.pending_candidates.values()
                if _looks_like_single_chaos_roll(modifier)
                and any(
                    _matches_gamba_roll(modifier, roll_index)
                    for roll_index in state.unresolved_indices
                )
            )
        candidates = tuple(
            modifier
            for modifier in state.pending_candidates.values()
            if int(getattr(modifier, "object_ptr", 0)) not in state.contested_ptrs
        )
        assignments, unresolved, ambiguous = _solve_gamba_batch(
            tuple(sorted(state.unresolved_indices)),
            candidates,
        )
        for roll_index, modifier in assignments:
            ptr = int(getattr(modifier, "object_ptr", 0))
            if ptr in state.attributed_ptrs:
                continue
            state.attributed_ptrs.add(ptr)
            state.assignments[ptr] = (roll_index, modifier)
            state.unresolved_indices.discard(roll_index)
            state.pending_candidates.pop(ptr, None)
            _add_gamba_total(state, modifier)
        state.ambiguous = unresolved + ambiguous

    state.current_level = current_level
    missing = max(len(state.unresolved_indices), current_level - state.attributed_rolls)
    effects = tuple(
        CharacterPassiveEffectSnapshot(
            key=f"stat:{total.stat_id}",
            label=total.label,
            value=total.value,
            value_format=total.value_format,
            kind=CharacterPassiveEffectKind.PERMANENT_ROLL,
            stat_id=total.stat_id,
            count=total.rolls,
        )
        for total in sorted(state.totals.values(), key=chaos_tome_stat_sort_key)
    )
    complete = missing == 0 and state.ambiguous == 0
    return CharacterPassiveSnapshot(
        **base,
        status=(
            CharacterPassiveStatus.SUPPORTED
            if complete
            else CharacterPassiveStatus.PARTIAL
        ),
        effects=effects,
        coverage="complete" if complete else "partial",
        ambiguous=max(state.ambiguous, missing),
        pending=len(state.pending_candidates),
    )


def _solve_gamba_batch(
    indices: tuple[int, ...],
    candidates: tuple[Any, ...],
) -> tuple[list[tuple[int, Any]], int, int]:
    """Return a one-pointer/one-index maximum assignment.

    The first 255 indices retain their level-specific decay. At the clamp all
    later indices share the same five fingerprints, so only the aggregate
    pointer set is meaningful and can be assigned without pretending an order.
    """
    if not indices or not candidates:
        return [], len(indices), 0

    early = tuple(index for index in indices if index < GAMBA_LEVEL_SPECIFIC_ROLLS)
    floor = tuple(index for index in indices if index >= GAMBA_LEVEL_SPECIFIC_ROLLS)
    by_ptr = {int(getattr(candidate, "object_ptr", 0)): candidate for candidate in candidates}
    adjacency: dict[int, tuple[int, ...]] = {
        index: tuple(
            ptr
            for ptr, candidate in by_ptr.items()
            if _matches_gamba_roll(candidate, index)
        )
        for index in early
    }

    matched_ptr_to_index: dict[int, int] = {}

    def assign(index: int, visited: set[int]) -> bool:
        for ptr in adjacency.get(index, ()):
            if ptr in visited:
                continue
            visited.add(ptr)
            previous = matched_ptr_to_index.get(ptr)
            if previous is None or assign(previous, visited):
                matched_ptr_to_index[ptr] = index
                return True
        return False

    for index in sorted(early, key=lambda value: len(adjacency.get(value, ()))):
        assign(index, set())

    assignments = [
        (index, by_ptr[ptr]) for ptr, index in matched_ptr_to_index.items()
    ]
    used_ptrs = set(matched_ptr_to_index)
    floor_candidates = [
        candidate
        for ptr, candidate in by_ptr.items()
        if ptr not in used_ptrs and _matches_gamba_roll(candidate, 255)
    ]
    floor_count = min(len(floor), len(floor_candidates))
    assignments.extend(zip(floor[:floor_count], floor_candidates[:floor_count]))
    ambiguous = sum(
        1 for index in early if len(adjacency.get(index, ())) > 1
    )
    ambiguous += max(0, len(floor_candidates) - len(floor))
    return assignments, len(indices) - len(assignments), ambiguous


def _is_gamba_pool_candidate(modifier: Any) -> bool:
    stat_id = int(getattr(modifier, "stat_id", -1))
    rule = SHRINE_STAT_RULES.get(stat_id)
    if stat_id not in CHAOS_TOME_BASE_VALUES or rule is None:
        return False
    return int(getattr(modifier, "modify_type", -1)) == int(rule.modify_type)


def _matches_gamba_roll(modifier: Any, roll_index: int) -> bool:
    if not _is_gamba_pool_candidate(modifier):
        return False
    value = float(getattr(modifier, "value", float("nan")))
    if not math.isfinite(value):
        return False
    stat_id = int(getattr(modifier, "stat_id", -1))
    return any(
        _ulp_distance(value, gamba_roll_value(stat_id, rarity, roll_index))
        <= GAMBA_MAX_ULP_DISTANCE
        for rarity in GAMBA_RARITY_MULTIPLIERS
    )


def gamba_decay(roll_index: int) -> float:
    n = max(0, int(roll_index))
    ratio = _f32(_f32(float(n)) / _f32(50.0))
    powered = _f32(math.pow(ratio, _f32(1.5)))
    denominator = _f32(_f32(1.0) + powered)
    raw = _f32(_f32(0.75) / denominator)
    return _f32(min(_f32(1.0), max(_f32(0.06), raw)))


def gamba_roll_value(stat_id: int, rarity_multiplier: float, roll_index: int) -> float:
    base = _f32(CHAOS_TOME_BASE_VALUES[int(stat_id)])
    inner = _f32(round(_f32(base * _f32(rarity_multiplier)), 3))
    common_rounded = _f32(round(_f32(inner * _f32(1.0)), 3))
    return _f32(common_rounded * gamba_decay(roll_index))


def _add_gamba_total(state: _GambaState, modifier: Any) -> None:
    stat_id = int(getattr(modifier, "stat_id"))
    value = float(getattr(modifier, "value"))
    current = state.totals.get(stat_id)
    if current is None:
        state.totals[stat_id] = _GambaTotal(
            stat_id=stat_id,
            label=str(getattr(modifier, "label", f"Stat {stat_id}")),
            value=value,
            value_format=getattr(modifier, "value_format", PlayerStatFormat.FLAT),
            rolls=1,
        )
    else:
        current.value += value
        current.rolls += 1
    state.attributed_rolls += 1


def _remove_gamba_total(state: _GambaState, modifier: Any) -> None:
    stat_id = int(getattr(modifier, "stat_id"))
    current = state.totals.get(stat_id)
    if current is None:
        return
    current.value -= float(getattr(modifier, "value"))
    current.rolls -= 1
    state.attributed_rolls = max(0, state.attributed_rolls - 1)
    if current.rolls <= 0:
        state.totals.pop(stat_id, None)


def _looks_like_single_chaos_roll(modifier: Any) -> bool:
    # Imported lazily to keep this module's top-level dependency one-way while
    # still sharing Chaos Tome's canonical two-rarity fingerprint solver.
    from core.tracker.chaos import looks_like_chaos_value

    return looks_like_chaos_value(
        int(getattr(modifier, "stat_id", -1)),
        float(getattr(modifier, "value", 0.0)),
        max_rolls=1,
    ) > 0


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _ulp_distance(left: float, right: float) -> int:
    if not math.isfinite(float(left)) or not math.isfinite(float(right)):
        return 2**31
    left_bits = struct.unpack("<I", struct.pack("<f", float(left)))[0]
    right_bits = struct.unpack("<I", struct.pack("<f", float(right)))[0]
    return abs(int(left_bits) - int(right_bits))
