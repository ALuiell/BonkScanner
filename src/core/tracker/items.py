"""Tracked-item rules and item-gain detection: pure functions over
``_TrackedItemState``.

Split out of ``live_run_tracker.py`` in step 13.  Nothing here acquires a
lock; ``LiveRunTracker`` calls in while already holding its single ``RLock``.

Item gains are confirmed, not trusted on first sight.  A count that rises is
held as a *pending* increase and only credited once a later read agrees,
because the game's item array is rebuilt in place and a mid-write read can
show a transient count.  ``_PendingItemIncrease`` carries the snapshot that
observed the rise, so the event is timestamped from when it happened rather
than from when it was confirmed.

The run-state dependency (``current_stage_index``) is passed in explicitly
rather than reached for: rules like ``map_1_only`` are evaluated against the
stage the item was picked up on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core import run_summary
# Sourced from core.run_summary rather than gui_styles directly: run_summary
# already owns that edge and uses the constant itself, so this stays a
# core -> core import instead of adding another core -> gui_styles one (the
# roadmap asks for that debt not to be deepened before step 14).
from core.run_summary import PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
from core.tracker.snapshots import (
    LiveRunSnapshot,
    TrackedItemEvent,
    TrackedItemRule,
    _PendingItemIncrease,
)


@dataclass
class _TrackedItemState:
    tracked_item_rules: tuple[TrackedItemRule, ...] = ()
    previous_item_counts: dict[str, int] | None = None
    pending_item_increases: dict[str, _PendingItemIncrease] = field(default_factory=dict)
    tracked_events: list[TrackedItemEvent] = field(default_factory=list)
    tracked_counts: dict[str, int] = field(default_factory=dict)
    combo_run_counts: dict[str, int] = field(default_factory=dict)


def fold_item_match_name(value: str) -> str:
    display_name = run_summary.normalize_item_name_for_display(str(value))
    canonical_name = run_summary.normalize_item_name_for_rarity(display_name)
    return "".join(char.lower() for char in canonical_name if char.isalnum())


def rows_for_rules(
    state: _TrackedItemState,
    rules: Iterable[TrackedItemRule],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rule in rules:
        rows.append(
            {
                "id": rule.id,
                "label": rule.label,
                "count": int(state.tracked_counts.get(rule.id, 0)),
                "mode": rule.mode,
            }
        )
    return rows


def reset_baseline(state: _TrackedItemState, *, reset_combo_counts: bool = True) -> None:
    state.previous_item_counts = None
    state.pending_item_increases = {}
    if reset_combo_counts:
        state.combo_run_counts = {rule.id: 0 for rule in state.tracked_item_rules}


def set_rules(
    state: _TrackedItemState,
    rules: Iterable[TrackedItemRule],
    *,
    latest_snapshot: LiveRunSnapshot | None,
) -> None:
    """Replace the rule set, preserving counts for rules that did not change."""
    new_rules = tuple(rules)
    if new_rules == state.tracked_item_rules:
        return
    old_rules_by_id = {rule.id: rule for rule in state.tracked_item_rules}
    old_counts = dict(state.tracked_counts)
    old_combo_run_counts = dict(state.combo_run_counts)
    preserved_rule_ids = {
        rule.id
        for rule in new_rules
        if old_rules_by_id.get(rule.id) == rule
    }
    old_events = list(state.tracked_events)
    state.tracked_item_rules = new_rules
    state.tracked_counts = {
        rule.id: old_counts.get(rule.id, 0) if rule.id in preserved_rule_ids else 0
        for rule in state.tracked_item_rules
    }
    state.combo_run_counts = {
        rule.id: old_combo_run_counts.get(rule.id, 0) if rule.id in preserved_rule_ids else 0
        for rule in state.tracked_item_rules
    }
    state.tracked_events = [
        event for event in old_events if event.rule_id in preserved_rule_ids
    ]
    reset_baseline(state, reset_combo_counts=False)
    if latest_snapshot is not None and latest_snapshot.items_available:
        current_counts = run_summary.item_counts(latest_snapshot.items)
        state.previous_item_counts = current_counts
        for rule in state.tracked_item_rules:
            if rule.id not in preserved_rule_ids and len(rule.item_names) > 1:
                state.combo_run_counts[rule.id] = combo_count_for_rule(rule, current_counts)


def process_item_deltas(
    state: _TrackedItemState,
    snapshot: LiveRunSnapshot,
    *,
    current_stage_index: int,
) -> None:
    if not snapshot.items_available:
        return
    current_counts = run_summary.item_counts(snapshot.items)
    if state.previous_item_counts is None:
        state.previous_item_counts = {}
        state.pending_item_increases = initial_item_increase_candidates(
            snapshot,
            current_counts,
            current_stage_index=current_stage_index,
        )
        return

    confirmed_counts = dict(state.previous_item_counts)
    confirmed_gain_contexts: dict[str, _PendingItemIncrease] = {}
    for item_name in set(current_counts) | set(state.pending_item_increases):
        current_count = max(0, int(current_counts.get(item_name, 0)))
        confirmed_count = max(0, int(confirmed_counts.get(item_name, 0)))
        pending = state.pending_item_increases.get(item_name)

        if current_count <= confirmed_count:
            state.pending_item_increases.pop(item_name, None)
            continue

        if pending is None:
            state.pending_item_increases[item_name] = item_increase_candidate(
                snapshot,
                current_count,
                current_stage_index=current_stage_index,
            )
            continue

        if current_count < pending.observed_count:
            state.pending_item_increases[item_name] = item_increase_candidate(
                snapshot,
                current_count,
                current_stage_index=current_stage_index,
                initial_map_one_only=pending.initial_map_one_only,
            )
            continue

        gained_count = max(0, pending.observed_count - confirmed_count)
        if gained_count <= 0:
            state.pending_item_increases.pop(item_name, None)
            continue
        process_item_gain(
            state,
            item_name=item_name,
            gained_count=gained_count,
            snapshot=pending.snapshot,
            stage_index=pending.stage_index,
            initial_map_one_only=pending.initial_map_one_only,
        )
        confirmed_counts[item_name] = pending.observed_count
        confirmed_gain_contexts[item_name] = pending
        if current_count > pending.observed_count:
            state.pending_item_increases[item_name] = item_increase_candidate(
                snapshot,
                current_count,
                current_stage_index=current_stage_index,
            )
        else:
            state.pending_item_increases.pop(item_name, None)

    state.previous_item_counts = confirmed_counts
    effective_counts = {
        item_name: min(
            max(0, int(current_count)),
            max(0, int(confirmed_counts.get(item_name, 0))),
        )
        for item_name, current_count in current_counts.items()
    }
    process_combo_item_rules(
        state,
        snapshot=snapshot,
        current_counts=effective_counts,
        stage_index=current_stage_index,
        gain_contexts=confirmed_gain_contexts,
    )


def initial_item_increase_candidates(
    snapshot: LiveRunSnapshot,
    counts: dict[str, int],
    *,
    current_stage_index: int,
) -> dict[str, _PendingItemIncrease]:
    is_clearly_early = (
        current_stage_index == 1
        and snapshot.game_time_seconds is not None
        and float(snapshot.game_time_seconds) <= 10.0
    )
    initial_stage_index = max(
        current_stage_index,
        1 if snapshot_looks_like_first_stage(snapshot) else 2,
    )
    return {
        item_name: item_increase_candidate(
            snapshot,
            count,
            current_stage_index=current_stage_index,
            stage_index=initial_stage_index,
            combo_stage_index=current_stage_index,
            initial_map_one_only=not is_clearly_early,
        )
        for item_name, count in counts.items()
        if count > 0
    }


def item_increase_candidate(
    snapshot: LiveRunSnapshot,
    count: int,
    *,
    current_stage_index: int,
    stage_index: int | None = None,
    combo_stage_index: int | None = None,
    initial_map_one_only: bool = False,
) -> _PendingItemIncrease:
    resolved_stage_index = current_stage_index if stage_index is None else int(stage_index)
    return _PendingItemIncrease(
        observed_count=max(0, int(count)),
        snapshot=snapshot,
        stage_index=resolved_stage_index,
        combo_stage_index=(
            resolved_stage_index
            if combo_stage_index is None
            else int(combo_stage_index)
        ),
        initial_map_one_only=initial_map_one_only,
    )


def process_item_gain(
    state: _TrackedItemState,
    *,
    item_name: str,
    gained_count: int,
    snapshot: LiveRunSnapshot,
    stage_index: int,
    initial_map_one_only: bool = False,
) -> None:
    for rule in state.tracked_item_rules:
        if len(rule.item_names) > 1:
            continue
        if initial_map_one_only and rule.mode != "map_1_only":
            continue
        if not rule_matches_item(rule, item_name):
            continue
        eligible_count = eligible_count_for_rule(
            state,
            rule,
            gained_count=gained_count,
            game_time_seconds=snapshot.game_time_seconds,
            stage_index=stage_index,
        )
        if eligible_count <= 0:
            continue
        state.tracked_counts[rule.id] = state.tracked_counts.get(rule.id, 0) + eligible_count
        event = TrackedItemEvent(
            rule_id=rule.id,
            item_name=item_name,
            gained_count=eligible_count,
            game_time_seconds=snapshot.game_time_seconds,
            stage_index=stage_index,
            map_seed=snapshot.map_seed,
            captured_at=snapshot.captured_at,
        )
        state.tracked_events.append(event)


def snapshot_looks_like_first_stage(snapshot: LiveRunSnapshot) -> bool:
    if snapshot.game_time_seconds is None or snapshot.stage_time_seconds is None:
        return True
    return (
        float(snapshot.stage_time_seconds)
        + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
        >= float(snapshot.game_time_seconds)
    )


def process_combo_item_rules(
    state: _TrackedItemState,
    *,
    snapshot: LiveRunSnapshot,
    current_counts: dict[str, int],
    stage_index: int,
    gain_contexts: dict[str, _PendingItemIncrease] | None = None,
) -> None:
    folded_counts = {
        fold_item_match_name(item_name): max(0, int(count))
        for item_name, count in current_counts.items()
    }
    for rule in state.tracked_item_rules:
        if len(rule.item_names) <= 1:
            continue
        rule_gain_contexts = [
            context
            for item_name, context in (gain_contexts or {}).items()
            if rule_matches_item(rule, item_name)
        ]
        if rule_gain_contexts:
            combo_context = max(
                rule_gain_contexts,
                key=lambda context: context.snapshot.captured_at,
            )
            event_snapshot = combo_context.snapshot
            event_stage_index = combo_context.combo_stage_index
        else:
            event_snapshot = snapshot
            event_stage_index = stage_index
        if eligible_count_for_rule(
            state,
            rule,
            gained_count=1,
            game_time_seconds=event_snapshot.game_time_seconds,
            stage_index=event_stage_index,
        ) <= 0:
            continue
        combo_count = combo_count_for_rule(rule, folded_counts, folded=True)
        if combo_count <= 0:
            continue
        combo_count = 1
        already_counted_this_run = state.combo_run_counts.get(rule.id, 0)
        eligible_count = max(0, combo_count - already_counted_this_run)
        if eligible_count <= 0:
            continue
        total_count = state.tracked_counts.get(rule.id, 0)
        if rule.mode == "first_n" and rule.max_copies is not None:
            remaining = max(0, int(rule.max_copies) - total_count)
            eligible_count = min(eligible_count, remaining)
        if eligible_count <= 0:
            continue
        state.tracked_counts[rule.id] = total_count + eligible_count
        state.combo_run_counts[rule.id] = already_counted_this_run + eligible_count
        state.tracked_events.append(
            TrackedItemEvent(
                rule_id=rule.id,
                item_name=" + ".join(rule.item_names),
                gained_count=eligible_count,
                game_time_seconds=event_snapshot.game_time_seconds,
                stage_index=event_stage_index,
                map_seed=event_snapshot.map_seed,
                captured_at=event_snapshot.captured_at,
            )
        )


def combo_count_for_rule(
    rule: TrackedItemRule,
    counts: dict[str, int],
    *,
    folded: bool = False,
) -> int:
    if not rule.item_names:
        return 0
    if folded:
        folded_counts = counts
    else:
        folded_counts = {
            fold_item_match_name(item_name): max(0, int(count))
            for item_name, count in counts.items()
        }
    return min(
        folded_counts.get(fold_item_match_name(item_name), 0)
        for item_name in rule.item_names
    )


def eligible_count_for_rule(
    state: _TrackedItemState,
    rule: TrackedItemRule,
    *,
    gained_count: int,
    game_time_seconds: float | None,
    stage_index: int,
) -> int:
    mode = rule.mode
    if mode == "map_1_only" and stage_index != 1:
        return 0
    if mode == "before_stage":
        before_stage = rule.before_stage
        if before_stage is None or stage_index >= int(before_stage):
            return 0
    if mode == "before_time":
        before_seconds = rule.before_seconds
        if before_seconds is None or game_time_seconds is None or float(game_time_seconds) > float(before_seconds):
            return 0
    if mode not in {"all_run", "map_1_only", "before_stage", "before_time", "first_n"}:
        return 0

    eligible_count = max(0, int(gained_count))
    max_copies = rule.max_copies
    if mode == "first_n" and max_copies is not None:
        remaining = max(0, int(max_copies) - state.tracked_counts.get(rule.id, 0))
        eligible_count = min(eligible_count, remaining)
    return eligible_count


def rule_matches_item(rule: TrackedItemRule, item_name: str) -> bool:
    folded_item = fold_item_match_name(item_name)
    return folded_item in {fold_item_match_name(name) for name in rule.item_names}
