"""Chaos Tome tracking: pure functions over ``_ChaosTomeState``.

Split out of ``live_run_tracker.py`` in step 13.  Nothing here acquires a
lock.  ``LiveRunTracker`` holds its single ``RLock`` for the whole of every
public method and calls into this module while already holding it — see
the roadmap's "The tracker has one lock and one writer".  A feature module
that locked for itself would reintroduce exactly the coherence problem
``RuntimeStateSnapshot`` exists to solve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import gcd
from typing import Any

from core.stat_labels import abbreviate_stat_label
from core.stats.formats import PlayerStatFormat
from core.stats.types import ChaosTomeSnapshot, ChaosTomeStatSnapshot
from core.tracker.snapshots import ChaosTomeStatTotal


@dataclass
class _ChaosTomeState:
    chaos_tome_level: int | None = None
    chaos_modifier_baselines: dict[int, tuple[float, ...]] = field(default_factory=dict)
    chaos_totals: dict[int, ChaosTomeStatTotal] = field(default_factory=dict)
    chaos_ambiguous_rolls: int = 0
    chaos_available_rolls: int = 0
    chaos_unbudgeted_candidates: dict[tuple[int, int], tuple[float, int]] = field(default_factory=dict)


CHAOS_TOME_BASE_VALUES: dict[int, float] = {
    0: 15, 1: 20, 2: 5, 3: 5, 4: 0.05, 5: 0.05,
    9: 0.08, 10: 0.08, 11: 0.10, 12: 0.12,
    15: 0.06, 16: 1, 17: 0.06, 18: 0.05, 19: 0.10,
    23: 0.10, 24: 0.10, 25: 0.08, 29: 0.20,
    30: 0.05, 31: 0.075, 32: 0.075, 38: 0.08,
    39: 0.15, 40: 0.10, 41: 0.05, 46: 1,
}


def round3(val: float) -> float:
    return float(round(val, 3))


def _compute_chaos_fingerprints() -> dict[int, list[float]]:
    fingerprints = {}
    rarities = (2.0, 1.6, 1.4, 1.2, 1.0)
    for stat_id, base in CHAOS_TOME_BASE_VALUES.items():
        stat_fps = set()
        for r1 in rarities:
            for r2 in rarities:
                val = round3(round3(base * r1) * 1.4 * r2)
                stat_fps.add(val)
        fingerprints[stat_id] = sorted(list(stat_fps), reverse=True)
    return fingerprints


CHAOS_FINGERPRINTS: dict[int, list[float]] = _compute_chaos_fingerprints()
CHAOS_TOME_STAT_IDS: frozenset[int] = frozenset(CHAOS_FINGERPRINTS.keys())
CHAOS_UNBUDGETED_BASELINE_SAMPLES = 4
CHAOS_TOME_GAME_STAT_ORDER: dict[int, int] = {
    stat_id: index
    for index, stat_id in enumerate(
        (
            0, 1, 2, 4, 5, 17, 3,
            12, 18, 19, 15, 16,
            9, 11, 10, 23, 24, 25,
            46, 30, 38,
            29, 32, 31, 39, 40, 41,
        )
    )
}


def chaos_tome_stat_sort_key(total: Any) -> tuple[int, str]:
    stat_id = int(getattr(total, "stat_id", -1))
    return (CHAOS_TOME_GAME_STAT_ORDER.get(stat_id, 999), str(getattr(total, "label", "")).lower())


def reset(state: _ChaosTomeState) -> None:
    state.chaos_tome_level = None
    state.chaos_modifier_baselines = {}
    state.chaos_totals = {}
    state.chaos_ambiguous_rolls = 0
    state.chaos_available_rolls = 0
    state.chaos_unbudgeted_candidates = {}


def update(
    state: _ChaosTomeState,
    *,
    chaos_level: int | None,
    permanent_modifiers: dict[int, tuple[Any, ...]],
) -> None:
    if chaos_level is None:
        # TomeInventory may be unavailable while the game mutates its
        # dictionaries. A missing read is not evidence that the tome was
        # removed; run resets and level decreases handle real resets.
        return

    current_level = max(0, int(chaos_level))

    if state.chaos_tome_level is None:
        if current_level <= 0:
            return
        state.chaos_tome_level = current_level
        state.chaos_modifier_baselines = {}
        state.chaos_available_rolls = current_level
        state.chaos_unbudgeted_candidates = {}
        record_modifier_deltas(state, permanent_modifiers)
        return

    if current_level < state.chaos_tome_level:
        return

    if current_level > state.chaos_tome_level:
        state.chaos_available_rolls += (current_level - state.chaos_tome_level)
        state.chaos_tome_level = current_level

    record_modifier_deltas(state, permanent_modifiers)


def summary_parts(state: _ChaosTomeState) -> list[str]:
    totals = sorted(
        state.chaos_totals.values(),
        key=chaos_tome_stat_sort_key,
    )
    parts: list[str] = []
    for total in totals:
        label = abbreviate_stat_label(total.label)
        parts.append(f"{label} {total.display_delta}")
    return parts


def snapshot(state: _ChaosTomeState):
    if state.chaos_tome_level is None:
        return None

    stats = tuple(
        ChaosTomeStatSnapshot(
            stat_id=total.stat_id,
            label=total.label,
            value=total.value,
            value_format=total.value_format or PlayerStatFormat.FLAT,
            rolls=total.rolls,
        )
        for total in sorted(
            state.chaos_totals.values(),
            key=chaos_tome_stat_sort_key,
        )
    )
    return ChaosTomeSnapshot(
        level=state.chaos_tome_level,
        stats=stats,
        ambiguous_rolls=state.chaos_ambiguous_rolls,
    )


def record_modifier_deltas(
    state: _ChaosTomeState,
    permanent_modifiers: dict[int, tuple[Any, ...]],
) -> None:
    for stat_id, modifiers in (permanent_modifiers or {}).items():
        stat_id = int(stat_id)
        values = tuple(modifiers or ())
        old_values = state.chaos_modifier_baselines.get(stat_id, ())
        new_values = tuple(float(getattr(m, "value", 0.0)) for m in values)

        new_baseline = list(old_values)

        # Check existing indices for stacked modifiers
        for i in range(min(len(old_values), len(new_values))):
            delta = new_values[i] - old_values[i]
            if abs(delta) > 0.001:
                matched_rolls = looks_like_chaos_value(
                    stat_id,
                    delta,
                    max_rolls=max(1, int(state.chaos_tome_level or 1)),
                )
                if matched_rolls > 0:
                    rolls_to_process = min(state.chaos_available_rolls, matched_rolls)
                    if rolls_to_process > 0:
                        add_total_by_value(
                            state,
                            stat_id,
                            values[i],
                            delta * (rolls_to_process / matched_rolls),
                            rolls=rolls_to_process,
                        )
                        state.chaos_available_rolls -= rolls_to_process
                        new_baseline[i] = new_values[i]
                        state.chaos_unbudgeted_candidates.pop((stat_id, i), None)
                    elif should_commit_unbudgeted_candidate(state, stat_id, i, new_values[i]):
                        new_baseline[i] = new_values[i]
                else:
                    new_baseline[i] = new_values[i]
                    state.chaos_unbudgeted_candidates.pop((stat_id, i), None)

        # Check new indices for spawned modifiers
        if len(new_values) > len(old_values):
            for i in range(len(old_values), len(new_values)):
                val = new_values[i]
                matched_rolls = looks_like_chaos_value(
                    stat_id,
                    val,
                    max_rolls=max(1, int(state.chaos_tome_level or 1)),
                )
                if matched_rolls > 0:
                    rolls_to_process = min(state.chaos_available_rolls, matched_rolls)
                    if rolls_to_process > 0:
                        add_total_by_value(
                            state,
                            stat_id,
                            values[i],
                            val * (rolls_to_process / matched_rolls),
                            rolls=rolls_to_process,
                        )
                        state.chaos_available_rolls -= rolls_to_process
                        new_baseline.append(val)
                        state.chaos_unbudgeted_candidates.pop((stat_id, i), None)
                    elif should_commit_unbudgeted_candidate(state, stat_id, i, val):
                        new_baseline.append(val)
                    else:
                        break
                else:
                    new_baseline.append(val)
                    state.chaos_unbudgeted_candidates.pop((stat_id, i), None)

        state.chaos_modifier_baselines[stat_id] = tuple(new_baseline)


def looks_like_chaos_value(
    stat_id: int,
    value: float,
    *,
    max_rolls: int = 1,
) -> int:
    numeric = abs(value)
    if numeric <= 0:
        return 0

    fingerprints = CHAOS_FINGERPRINTS.get(stat_id)
    if not fingerprints:
        return 0

    # The game stacks different Chaos rolls for the same stat into one
    # modifier value. Work in thousandths (the game's own rounding) and
    # find the smallest valid combination of known fingerprints.
    target = int(round(numeric * 1000.0))
    fingerprint_units = tuple(
        sorted({int(round(float(fp) * 1000.0)) for fp in fingerprints if fp > 0})
    )
    if target <= 0 or not fingerprint_units:
        return 0

    max_rolls = max(1, int(max_rolls))
    minimum_progress = max(1, min(fingerprint_units) - 2)
    max_rolls = min(max_rolls, (target // minimum_progress) + 1)
    scale = 0
    for fingerprint in fingerprint_units:
        scale = gcd(scale, fingerprint)
    scale = max(1, scale)
    scaled_fingerprints = tuple(fingerprint // scale for fingerprint in fingerprint_units)
    maximum_sum = (target + (2 * max_rolls)) // scale
    reachable = 1  # Bit N means that a scaled fingerprint sum of N is reachable.
    sum_mask = (1 << (maximum_sum + 1)) - 1
    for roll_count in range(1, max_rolls + 1):
        next_reachable = 0
        for fingerprint in scaled_fingerprints:
            next_reachable |= reachable << fingerprint
        reachable = next_reachable & sum_mask
        tolerance = max(2, 2 * roll_count)
        lower_raw = max(0, target - tolerance)
        upper_raw = target + tolerance
        lower = (lower_raw + scale - 1) // scale
        upper = min(maximum_sum, upper_raw // scale)
        window_width = upper - lower + 1
        if window_width > 0 and ((reachable >> lower) & ((1 << window_width) - 1)):
            return roll_count
        if not reachable:
            break

    return 0


def should_commit_unbudgeted_candidate(
    state: _ChaosTomeState,
    stat_id: int,
    index: int,
    value: float,
) -> bool:
    key = (stat_id, index)
    previous = state.chaos_unbudgeted_candidates.get(key)
    if previous is not None and abs(previous[0] - value) <= 0.001:
        samples = previous[1] + 1
    else:
        samples = 1

    if samples >= CHAOS_UNBUDGETED_BASELINE_SAMPLES:
        state.chaos_unbudgeted_candidates.pop(key, None)
        return True

    state.chaos_unbudgeted_candidates[key] = (value, samples)
    return False


def add_total_by_value(
    state: _ChaosTomeState,
    stat_id: int,
    modifier: Any,
    delta: float,
    *,
    rolls: int = 1,
) -> None:
    rolls = max(1, int(rolls))
    existing = state.chaos_totals.get(stat_id)
    if existing is None:
        state.chaos_totals[stat_id] = ChaosTomeStatTotal(
            stat_id=stat_id,
            label=str(getattr(modifier, "label", f"Stat {stat_id}")),
            value=delta,
            value_format=getattr(modifier, "value_format", None),
            rolls=rolls,
        )
        return
    state.chaos_totals[stat_id] = ChaosTomeStatTotal(
        stat_id=existing.stat_id,
        label=existing.label,
        value=existing.value + delta,
        value_format=existing.value_format,
        rolls=existing.rolls + rolls,
    )
