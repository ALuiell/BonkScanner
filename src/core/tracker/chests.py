"""Chest and key tracking: pure functions over ``_ChestState``.

Split out of ``live_run_tracker.py`` in step 13.  Nothing here acquires a
lock; ``LiveRunTracker`` calls in while already holding its single ``RLock``.

The one run-state dependency is explicit: ``update_chests_and_keys`` needs
the latest ``LiveRunSnapshot`` to know which stage the counts belong to, so
the tracker passes it in rather than this module reaching back for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.tracker.snapshots import ChestStatsSnapshot, LiveRunSnapshot


@dataclass
class _ChestState:
    chests_opened: int = 0
    chests_total: int = 46
    keys_count: int = 0
    paid_chest_opens: int = 0
    key_chest_procs: int = 0
    free_chest_opens: int | None = None
    chest_counters_available: bool = False
    chest_history_incomplete: bool = False
    total_opened_minimum: int | None = None
    total_opened_is_minimum: bool = False
    expected_key_procs: float = 0.0
    expected_tracked_opens: int = 0
    expected_chests_bought: int | None = None
    expected_keys_count: int | None = None
    expected_available: bool = False
    expected_detected_run_reset: bool = False
    stage_ptrs_seen: list[int] = field(default_factory=list)
    stage_numbers_by_ptr: dict[int, int] = field(default_factory=dict)
    chests_opened_by_stage: dict[int, int] = field(default_factory=dict)
    chests_total_by_stage: dict[int, int] = field(default_factory=dict)


def key_proc_chance(keys_count: int) -> float:
    keys_count = max(0, int(keys_count))
    return (0.10 * keys_count) / ((0.10 * keys_count) + 1.0)


def raw_stage_to_human_stage(raw_stage_index: int) -> int:
    if raw_stage_index < 0:
        return 0
    return int(raw_stage_index) + 1


def baseline_chest_total_for_history(chests_total: int) -> int:
    total = max(0, int(chests_total))
    return 69 if total >= 69 else 46


def reset(
    state: _ChestState,
    *,
    preserve_expected: bool = False,
) -> None:
    """Reset run-scoped chest state without discarding proven fast history.

    The fast Expected lane can establish a zero baseline before the first full
    player snapshot is accepted.  That first snapshot is the slow lane finally
    claiming the *same* run, not a second run boundary, so its reset must retain
    the history when ``LiveRunTracker`` explicitly proves that situation.

    ``expected_detected_run_reset`` is the older form of the same hand-off: the
    fast cumulative counter noticed a rollback before the slow snapshot did.
    """
    state.chests_opened = 0
    state.chests_total = 46
    state.keys_count = 0
    state.paid_chest_opens = 0
    state.key_chest_procs = 0
    state.free_chest_opens = None
    state.chest_counters_available = False
    state.chest_history_incomplete = False
    state.total_opened_minimum = None
    state.total_opened_is_minimum = False
    if state.expected_detected_run_reset or preserve_expected:
        state.expected_detected_run_reset = False
    else:
        state.expected_key_procs = 0.0
        state.expected_tracked_opens = 0
        state.expected_chests_bought = None
        state.expected_keys_count = None
        state.expected_available = False
    state.stage_ptrs_seen = []
    state.stage_numbers_by_ptr = {}
    state.chests_opened_by_stage = {}
    state.chests_total_by_stage = {}


def update_chests_and_keys(
    state: _ChestState,
    chests_opened: int,
    chests_total: int,
    keys_count: int,
    *,
    latest_snapshot: LiveRunSnapshot | None,
) -> None:
    state.chests_opened = chests_opened
    state.chests_total = chests_total
    state.keys_count = keys_count

    latest = latest_snapshot
    stage_ptr = latest.stage_ptr if (latest and latest.stage_ptr) else 0
    raw_stage_index = int(getattr(latest, "stage_index", -1) or 0) if latest else -1
    if stage_ptr == 0:
        return

    if stage_ptr not in state.stage_ptrs_seen:
        stage_num = raw_stage_to_human_stage(raw_stage_index)
        fallback_total = baseline_chest_total_for_history(chests_total)
        if not state.stage_ptrs_seen and raw_stage_index > 0 and stage_num > 1:
            state.chest_history_incomplete = True
            for missing_stage in range(1, stage_num):
                state.chests_opened_by_stage.setdefault(missing_stage, -1)
                state.chests_total_by_stage.setdefault(missing_stage, fallback_total)
        if stage_num <= 0:
            stage_num = max(state.chests_total_by_stage.keys(), default=0) + 1
        while stage_num in state.chests_total_by_stage:
            stage_num += 1
        state.stage_ptrs_seen.append(stage_ptr)
        state.stage_numbers_by_ptr[stage_ptr] = stage_num
        state.chests_opened_by_stage[stage_num] = 0
        state.chests_total_by_stage[stage_num] = (
            fallback_total if state.chest_history_incomplete else chests_total
        )

    stage_num = state.stage_numbers_by_ptr.get(stage_ptr, 0)
    if stage_num <= 0:
        return

    # Protect against stage transition race conditions (residual counts)
    ptr_order = state.stage_ptrs_seen.index(stage_ptr)
    if ptr_order > 0:
        prev_stage_ptr = state.stage_ptrs_seen[ptr_order - 1]
        prev_stage_num = state.stage_numbers_by_ptr.get(prev_stage_ptr, 0)
        prev_opened = max(0, state.chests_opened_by_stage.get(prev_stage_num, 0))
        current_opened = max(0, state.chests_opened_by_stage.get(stage_num, 0))
        if current_opened == 0 and chests_opened == prev_opened:
            chests_opened = 0

    current_opened = max(0, state.chests_opened_by_stage.get(stage_num, 0))
    state.chests_opened_by_stage[stage_num] = max(current_opened, chests_opened)
    state.chests_total_by_stage[stage_num] = max(
        state.chests_total_by_stage.get(stage_num, 0), chests_total
    )


def resolve_maximum_chest_total(state: _ChestState) -> int | None:
    total = 0
    for stage_num, stage_total in state.chests_total_by_stage.items():
        opened = int(state.chests_opened_by_stage.get(stage_num, 0))
        if opened < 0:
            total += max(0, int(stage_total))
        else:
            total += max(0, opened)
    return total


def update_chest_counters(
    state: _ChestState,
    chests_bought: int,
    chests_purchased: int,
) -> bool:
    chests_bought = int(chests_bought)
    chests_purchased = int(chests_purchased)
    known_total = sum(max(0, value) for value in state.chests_opened_by_stage.values())
    max_total = resolve_maximum_chest_total(state)
    if max_total is None:
        return False
    total_opened = known_total
    total_opened_is_minimum = False
    if state.chest_history_incomplete:
        if chests_bought > max_total:
            return False
        total_opened = max(known_total, chests_bought)
        total_opened_is_minimum = True

    if not (
        0 <= chests_purchased <= chests_bought <= total_opened
    ):
        return False

    # The slow factual read is an independent proof that no normal chest has
    # been opened yet.  Use it to arm Expected even when the fast paired read
    # could not resolve the still-initialising passive-item dictionary.  No Key
    # probability is consumed at zero, so the current stack value is irrelevant
    # until a later fast sample observes an actual opening.
    if chests_bought == 0 and state.expected_chests_bought is None:
        state.expected_chests_bought = 0
        state.expected_keys_count = state.keys_count
        state.expected_available = True

    state.paid_chest_opens = chests_purchased
    state.key_chest_procs = chests_bought - chests_purchased
    state.free_chest_opens = (
        None if state.chest_history_incomplete else total_opened - chests_bought
    )
    state.total_opened_minimum = total_opened if total_opened_is_minimum else None
    state.total_opened_is_minimum = total_opened_is_minimum
    state.chest_counters_available = True
    return True


def track_expected_key_procs(
    state: _ChestState,
    chests_bought: int,
    keys_count: int,
) -> None:
    chests_bought = max(0, int(chests_bought))
    keys_count = max(0, int(keys_count))
    state.keys_count = keys_count

    if state.expected_chests_bought is None:
        state.expected_chests_bought = chests_bought
        state.expected_keys_count = keys_count
        state.expected_available = chests_bought == 0
        return

    if chests_bought < state.expected_chests_bought:
        state.expected_key_procs = 0.0
        state.expected_tracked_opens = 0
        state.expected_chests_bought = chests_bought
        state.expected_keys_count = keys_count
        state.expected_available = chests_bought == 0
        state.expected_detected_run_reset = True
        return

    delta = chests_bought - state.expected_chests_bought
    if delta > 0:
        # A key dropped by a chest can proc on that same chest, so the
        # post-open stack is the best observable probability sample.
        state.expected_key_procs += delta * key_proc_chance(keys_count)
        state.expected_tracked_opens += delta

    state.expected_chests_bought = chests_bought
    state.expected_keys_count = keys_count


def get_chest_stats(state: _ChestState) -> ChestStatsSnapshot:
    opened_by_num = {
        stage_num: state.chests_opened_by_stage.get(stage_num, 0)
        for stage_num in sorted(state.chests_total_by_stage)
    }
    total_by_num = {
        stage_num: state.chests_total_by_stage.get(stage_num, 0)
        for stage_num in sorted(state.chests_total_by_stage)
    }
    return ChestStatsSnapshot(
        current_opened=state.chests_opened,
        current_total=state.chests_total,
        keys_count=state.keys_count,
        paid=state.paid_chest_opens,
        key_procs=state.key_chest_procs,
        free_chests=state.free_chest_opens,
        opened_by_stage=opened_by_num,
        total_by_stage=total_by_num,
        counters_available=state.chest_counters_available,
        expected_key_procs=state.expected_key_procs,
        expected_tracked_opens=state.expected_tracked_opens,
        expected_available=state.expected_available,
        total_opened_minimum=state.total_opened_minimum,
        total_opened_is_minimum=state.total_opened_is_minimum,
        expected_initialized=state.expected_chests_bought is not None,
    )
