"""Pure Build Progression domain models and evaluation.

This module deliberately owns no configuration, Qt objects, timers, or memory
clients.  It turns one immutable runtime boundary plus one immutable build
definition into the state every presentation surface renders.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Mapping

from core.tracker.snapshots import RunLifecycle, RuntimeStateSnapshot
from core.stats.formatters import format_player_stat_value


WARNING_WINDOW_SECONDS = 120.0


class RequirementKind(str, Enum):
    ITEM = "item"
    STAT = "stat"


class DeadlineKind(str, Enum):
    NONE = "none"
    RUN_CLOCK = "run_clock"
    STAGE_START = "stage_start"
    STAGE_OVERTIME = "stage_overtime"


class Priority(str, Enum):
    NORMAL = "normal"
    EARLY = "early"
    ASAP = "asap"


class RequirementStatus(str, Enum):
    UNKNOWN = "unknown"
    NEUTRAL = "neutral"
    WARNING = "warning"
    OVERDUE = "overdue"
    SATISFIED = "satisfied"


STATUS_SYMBOLS: Mapping[RequirementStatus, str] = {
    RequirementStatus.UNKNOWN: "?",
    RequirementStatus.NEUTRAL: "·",
    RequirementStatus.WARNING: "!",
    RequirementStatus.OVERDUE: "×",
    RequirementStatus.SATISFIED: "✓",
}


@dataclass(frozen=True)
class RequirementDeadline:
    kind: DeadlineKind = DeadlineKind.NONE
    stage: int | None = None
    seconds: float | None = None


@dataclass(frozen=True)
class BuildRequirement:
    id: str
    kind: RequirementKind
    target: str
    required: float
    ideal: float | None = None
    priority: Priority = Priority.NORMAL
    deadline: RequirementDeadline = RequirementDeadline()
    order: int = 0


@dataclass(frozen=True)
class BuildProgressionDefinition:
    name: str = "Build Progression"
    deadlines_enabled: bool = True
    requirements: tuple[BuildRequirement, ...] = ()


@dataclass(frozen=True)
class BuildProgressionRow:
    id: str
    kind: RequirementKind
    target: str
    current: float | None
    required: float
    ideal: float | None
    current_display: str
    required_display: str
    ideal_display: str | None
    priority: Priority
    deadline: RequirementDeadline
    deadline_label: str
    time_delta_seconds: float | None
    status: RequirementStatus
    symbol: str
    satisfied_at_seconds: float | None
    order: int


@dataclass(frozen=True)
class BuildProgressionSnapshot:
    configured: bool
    available: bool
    name: str
    run_id: str | None
    run_time_seconds: float | None
    completed: int
    total: int
    complete: bool
    completion_time_seconds: float | None
    rows: tuple[BuildProgressionRow, ...]


@dataclass(frozen=True)
class BuildProgressionEvaluation:
    snapshot: BuildProgressionSnapshot
    satisfied_at: Mapping[str, float]
    completion_time_seconds: float | None


def format_clock(seconds: float | None) -> str:
    if seconds is None or not isfinite(seconds):
        return "--:--"
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def format_deadline(deadline: RequirementDeadline) -> str:
    if deadline.kind is DeadlineKind.NONE:
        return ""
    if deadline.kind is DeadlineKind.RUN_CLOCK:
        return f"RUN · {format_clock(deadline.seconds)}"
    stage = max(1, min(4, int(deadline.stage or 1)))
    if deadline.kind is DeadlineKind.STAGE_START:
        return f"Before S{stage}"
    return f"S{stage} OT · {format_clock(deadline.seconds)}"


def evaluate_build_progression(
    definition: BuildProgressionDefinition,
    runtime: RuntimeStateSnapshot,
    *,
    previous_satisfied_at: Mapping[str, float] | None = None,
    previous_completion_time_seconds: float | None = None,
) -> BuildProgressionEvaluation:
    """Evaluate the configured build without reading or mutating external state."""
    previous_satisfied_at = previous_satisfied_at or {}
    run_time = runtime.run_timer_seconds
    latest = runtime.latest_snapshot
    items = runtime.fast_items
    if items is None and latest is not None and latest.items_available:
        items = latest.items
    item_counts = Counter(items) if items is not None else None
    stats = latest.stats if latest is not None else {}

    rows: list[BuildProgressionRow] = []
    next_satisfied: dict[str, float] = {}
    for requirement in definition.requirements:
        current, stat_value = _current_value(requirement, item_counts, stats)
        satisfied = current is not None and current >= requirement.required
        deadline = (
            requirement.deadline
            if definition.deadlines_enabled
            else RequirementDeadline()
        )
        deadline_status, delta = _deadline_status(deadline, runtime)
        if current is None:
            status = RequirementStatus.UNKNOWN
        elif satisfied:
            status = RequirementStatus.SATISFIED
        elif (
            deadline_status is RequirementStatus.OVERDUE
            and _stat_observation_precedes_deadline(requirement, deadline, runtime)
        ):
            status = RequirementStatus.WARNING
        else:
            status = deadline_status

        satisfied_at = None
        if satisfied:
            satisfied_at = previous_satisfied_at.get(requirement.id)
            if satisfied_at is None and run_time is not None:
                satisfied_at = max(0.0, float(run_time))
            if satisfied_at is not None:
                next_satisfied[requirement.id] = satisfied_at

        rows.append(
            BuildProgressionRow(
                id=requirement.id,
                kind=requirement.kind,
                target=requirement.target,
                current=current,
                required=requirement.required,
                ideal=requirement.ideal,
                current_display=_display_value(requirement, current, stat_value),
                required_display=_display_value(requirement, requirement.required, stat_value),
                ideal_display=(
                    _display_value(requirement, requirement.ideal, stat_value)
                    if requirement.ideal is not None
                    else None
                ),
                priority=requirement.priority,
                deadline=deadline,
                deadline_label=format_deadline(deadline),
                time_delta_seconds=delta,
                status=status,
                symbol=STATUS_SYMBOLS[status],
                satisfied_at_seconds=satisfied_at,
                order=requirement.order,
            )
        )

    rows.sort(key=_row_sort_key)
    total = len(rows)
    completed = sum(row.status is RequirementStatus.SATISFIED for row in rows)
    complete = bool(total) and completed == total
    completion_time = previous_completion_time_seconds if complete else None
    if complete and completion_time is None and run_time is not None:
        completion_time = max(0.0, float(run_time))

    snapshot = BuildProgressionSnapshot(
        configured=bool(total),
        available=runtime.lifecycle is RunLifecycle.ACTIVE,
        name=definition.name.strip() or "Build Progression",
        run_id=runtime.run_id,
        run_time_seconds=run_time,
        completed=completed,
        total=total,
        complete=complete,
        completion_time_seconds=completion_time,
        rows=tuple(rows),
    )
    return BuildProgressionEvaluation(snapshot, next_satisfied, completion_time)


def _current_value(requirement, item_counts, stats):
    if requirement.kind is RequirementKind.ITEM:
        if item_counts is None:
            return None, None
        return float(item_counts.get(requirement.target, 0)), None
    stat = stats.get(requirement.target) if isinstance(stats, dict) else None
    value = getattr(stat, "value", stat)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, stat
    return (parsed if isfinite(parsed) else None), stat


def _display_value(requirement, value, stat_value) -> str:
    if value is None:
        return "--"
    if requirement.kind is RequirementKind.ITEM:
        return str(int(value))
    spec = getattr(stat_value, "spec", None)
    value_format = getattr(spec, "value_format", None)
    if value_format is None:
        return f"{float(value):g}"
    display_scale = float(getattr(spec, "display_scale", 1.0))
    return format_player_stat_value(float(value) * display_scale, value_format)


def _deadline_status(deadline, runtime):
    if deadline.kind is DeadlineKind.NONE:
        return RequirementStatus.NEUTRAL, None
    run_time = runtime.run_timer_seconds
    if deadline.kind is DeadlineKind.RUN_CLOCK:
        if run_time is None or deadline.seconds is None:
            return RequirementStatus.UNKNOWN, None
        return _status_for_delta(float(deadline.seconds) - run_time)

    target_stage = max(1, min(4, int(deadline.stage or 1)))
    current_stage = max(0, int(runtime.current_stage_index or 0))
    timer = runtime.fast_stage_timer
    if deadline.kind is DeadlineKind.STAGE_START:
        if current_stage >= target_stage:
            return RequirementStatus.OVERDUE, None
        if current_stage != target_stage - 1 or timer is None:
            return RequirementStatus.NEUTRAL, None
        if timer.stage_timer_seconds is None or timer.stage_duration_seconds is None:
            return RequirementStatus.NEUTRAL, None
        delta = timer.stage_duration_seconds - timer.stage_timer_seconds
        return (
            RequirementStatus.WARNING
            if delta <= WARNING_WINDOW_SECONDS
            else RequirementStatus.NEUTRAL,
            delta,
        )

    if current_stage > target_stage:
        return RequirementStatus.OVERDUE, None
    if current_stage < target_stage or timer is None:
        return RequirementStatus.NEUTRAL, None
    if timer.stage_timer_seconds is None or timer.stage_duration_seconds is None:
        return RequirementStatus.NEUTRAL, None
    delta = (
        timer.stage_duration_seconds
        + float(deadline.seconds or 0.0)
        - timer.stage_timer_seconds
    )
    return _status_for_delta(delta)


def _status_for_delta(delta: float):
    if delta < 0:
        return RequirementStatus.OVERDUE, delta
    if delta <= WARNING_WINDOW_SECONDS:
        return RequirementStatus.WARNING, delta
    return RequirementStatus.NEUTRAL, delta


def _stat_observation_precedes_deadline(requirement, deadline, runtime) -> bool:
    if requirement.kind is not RequirementKind.STAT:
        return False
    latest = runtime.latest_snapshot
    if latest is None:
        return deadline.kind is not DeadlineKind.NONE
    if deadline.kind is DeadlineKind.RUN_CLOCK:
        return bool(
            deadline.seconds is not None
            and runtime.run_timer_seconds is not None
            and runtime.run_timer_seconds > deadline.seconds
            and (
                latest.game_time_seconds is None
                or latest.game_time_seconds < deadline.seconds
            )
        )
    target_stage = max(1, min(4, int(deadline.stage or 1)))
    observed_stage = (
        4
        if getattr(latest, "is_final_boss_stage", False)
        else (int(latest.stage_index) + 1 if latest.stage_index is not None else 0)
    )
    if deadline.kind is DeadlineKind.STAGE_START:
        return runtime.current_stage_index >= target_stage and observed_stage < target_stage
    if deadline.kind is DeadlineKind.STAGE_OVERTIME:
        if runtime.current_stage_index < target_stage:
            return False
        if observed_stage < target_stage:
            return True
        if observed_stage > target_stage:
            return False
        observed_timer = getattr(latest, "stage_timer_seconds", None)
        if observed_timer is None:
            observed_timer = getattr(latest, "stage_time_seconds", None)
        duration = getattr(latest, "stage_duration_seconds", None)
        if not duration and runtime.fast_stage_timer is not None:
            duration = runtime.fast_stage_timer.stage_duration_seconds
        threshold = float(duration or 0.0) + float(deadline.seconds or 0.0)
        return observed_timer is None or float(observed_timer) < threshold
    return False


_STATUS_ORDER = {
    RequirementStatus.OVERDUE: 0,
    RequirementStatus.WARNING: 1,
    RequirementStatus.NEUTRAL: 2,
    RequirementStatus.UNKNOWN: 2,
    RequirementStatus.SATISFIED: 4,
}
_PRIORITY_ORDER = {Priority.ASAP: 0, Priority.EARLY: 1, Priority.NORMAL: 2}


def _row_sort_key(row: BuildProgressionRow):
    untimed = row.deadline.kind is DeadlineKind.NONE
    delta = row.time_delta_seconds
    if row.status is RequirementStatus.OVERDUE:
        deadline_rank = delta if delta is not None else float("-inf")
    else:
        deadline_rank = delta if delta is not None else float("inf")
    return (
        _STATUS_ORDER[row.status],
        1 if untimed else 0,
        deadline_rank,
        _PRIORITY_ORDER[row.priority],
        row.order,
    )
