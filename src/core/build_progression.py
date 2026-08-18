"""Pure Build Progression domain models and evaluation.

This module deliberately owns no configuration, Qt objects, timers, or memory
clients.  It turns one immutable runtime boundary plus one immutable build
definition into the state every presentation surface renders.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from math import isfinite
from typing import Mapping

from core.tracker.snapshots import RunLifecycle, RuntimeStateSnapshot
from core.stats.formatters import format_player_stat_value
from core.run_summary import item_counts as count_items


WARNING_WINDOW_SECONDS = 120.0
PROGRESS_TARGET_FIELDS: Mapping[str, str] = {
    "Kills": "mob_kills",
    "Player Level": "player_level",
}
PROGRESS_TARGETS = tuple(PROGRESS_TARGET_FIELDS)


class RequirementKind(str, Enum):
    ITEM = "item"
    STAT = "stat"
    PROGRESS = "progress"


class DeadlineKind(str, Enum):
    NONE = "none"
    STAGE_START = "stage_start"
    STAGE_OVERTIME = "stage_overtime"


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


CAP_SUPPORTED_ITEMS: frozenset[str] = frozenset({
    "Spicy Meatball",
    "Grandma's Secret Tonic",
})


def calculate_radius_cap(size: float) -> int | None:
    """Smallest copy count n where Radius(n, S) = min(max((3+n)*S, 1), 8) reaches 8."""
    if not math.isfinite(size) or size <= 0:
        return None
    n = max(1, math.ceil(8.0 / size - 3))
    while min(max((3 + n) * size, 1), 8) < 8 and n < 10000:
        n += 1
    return n


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
    deadline: RequirementDeadline = RequirementDeadline()
    order: int = 0
    max_required: float | None = None
    cap_tracking: bool = False


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
    current_display: str
    required_display: str
    deadline: RequirementDeadline
    deadline_label: str
    time_delta_seconds: float | None
    status: RequirementStatus
    symbol: str
    satisfied_at_seconds: float | None
    order: int
    max_required: float | None = None
    late: bool = False
    cap_unresolved: bool = False
    min_met: bool = False
    cap_tracking: bool = False


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
    late_complete: bool = False


@dataclass(frozen=True)
class BuildProgressionEvaluation:
    snapshot: BuildProgressionSnapshot
    satisfied_at: Mapping[str, float]
    completion_time_seconds: float | None
    late: Mapping[str, bool]
    min_satisfied_at: Mapping[str, float]


def format_clock(seconds: float | None) -> str:
    if seconds is None or not isfinite(seconds):
        return "--:--"
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def format_deadline(deadline: RequirementDeadline) -> str:
    if deadline.kind is DeadlineKind.NONE:
        return ""
    stage = _target_stage(deadline)
    if stage is None:
        return ""
    if deadline.kind is DeadlineKind.STAGE_START:
        return f"BEFORE T{stage}"
    return f"T{stage} +{format_clock(deadline.seconds)}"


def evaluate_build_progression(
    definition: BuildProgressionDefinition,
    runtime: RuntimeStateSnapshot,
    *,
    previous_satisfied_at: Mapping[str, float] | None = None,
    previous_completion_time_seconds: float | None = None,
    previous_min_satisfied_at: Mapping[str, float] | None = None,
    previous_late: Mapping[str, bool] | None = None,
    effective_caps: Mapping[str, int | None] | None = None,
) -> BuildProgressionEvaluation:
    """Evaluate the configured build without reading or mutating external state."""
    previous_satisfied_at = previous_satisfied_at or {}
    previous_min_satisfied_at = previous_min_satisfied_at or {}
    previous_late = previous_late or {}
    effective_caps = effective_caps or {}
    run_time = runtime.run_timer_seconds
    latest = runtime.latest_snapshot
    items = runtime.fast_items
    if items is None and latest is not None and latest.items_available:
        items = latest.items
    # The real memory boundary publishes stacked display strings such as
    # ``"Wizard's Hat x198"``.  Reuse the run-summary parser used everywhere
    # else instead of counting those strings as one differently named item.
    item_counts = count_items(items) if items is not None else None
    stats = latest.stats if latest is not None else {}

    rows: list[BuildProgressionRow] = []
    next_satisfied: dict[str, float] = {}
    next_min_satisfied_at: dict[str, float] = {}
    next_late: dict[str, bool] = {}
    for requirement in definition.requirements:
        current, stat_value = _current_value(
            requirement,
            item_counts,
            stats,
            latest,
        )
        # --- Min/Max and Cap logic ---
        effective_max = requirement.max_required
        cap_unresolved = False
        if requirement.cap_tracking:
            resolved_cap = effective_caps.get(requirement.id)
            if resolved_cap is not None:
                effective_max = float(resolved_cap)
            else:
                # Cap tracking active but Size unavailable
                effective_max = None
                cap_unresolved = True

        min_met = current is not None and current >= requirement.required
        if effective_max is not None:
            satisfied = current is not None and current >= effective_max
        elif cap_unresolved and min_met:
            # Cap unresolved: min reached but cannot confirm max
            satisfied = False
        else:
            satisfied = min_met

        effective_target = requirement.required
        if min_met and effective_max is not None:
            effective_target = effective_max

        deadline = (
            requirement.deadline
            if definition.deadlines_enabled
            else RequirementDeadline()
        )
        deadline_status, delta = _deadline_status(deadline, runtime)

        # --- Late detection (before deadline neutralization) ---
        min_newly_satisfied = min_met and requirement.id not in previous_min_satisfied_at
        if min_newly_satisfied:
            late = deadline_status is RequirementStatus.OVERDUE
        elif min_met:
            late = previous_late.get(requirement.id, False)
        else:
            late = False

        # Disable deadline for max/cap stage (deadline applies only to min)
        if min_met and (effective_max is not None or cap_unresolved):
            deadline = RequirementDeadline()
            deadline_status, delta = RequirementStatus.NEUTRAL, None

        # Track min_satisfied_at
        if min_met:
            min_sat = previous_min_satisfied_at.get(requirement.id)
            if min_sat is None and run_time is not None:
                min_sat = max(0.0, float(run_time))
            if min_sat is not None:
                next_min_satisfied_at[requirement.id] = min_sat

        if late:
            next_late[requirement.id] = True

        # --- Status assignment ---
        if current is None:
            status = RequirementStatus.UNKNOWN
        elif satisfied:
            status = RequirementStatus.SATISFIED
        elif (
            deadline_status is RequirementStatus.OVERDUE
            and _snapshot_observation_precedes_deadline(requirement, deadline, runtime)
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
                required=effective_target,
                current_display=_display_value(requirement, current, stat_value),
                required_display=(
                    "\u2014" if cap_unresolved and min_met
                    else _display_value(requirement, effective_target, stat_value)
                ),
                deadline=deadline,
                deadline_label=format_deadline(deadline),
                time_delta_seconds=delta,
                status=status,
                # A late minimum is still obtained, even while an optional
                # maximum/cap remains in progress. Keep the leading checkmark
                # and let each projection colour it orange instead of showing
                # the ordinary neutral-dot symbol.
                symbol="✓" if late else STATUS_SYMBOLS[status],
                satisfied_at_seconds=satisfied_at,
                order=requirement.order,
                max_required=effective_max,
                late=late,
                cap_unresolved=cap_unresolved,
                min_met=min_met,
                cap_tracking=requirement.cap_tracking,
            )
        )

    rows.sort(key=_row_sort_key)
    total = len(rows)
    completed = sum(row.status is RequirementStatus.SATISFIED for row in rows)
    complete = bool(total) and completed == total
    late_complete = complete and any(row.late for row in rows)
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
        late_complete=late_complete,
    )
    return BuildProgressionEvaluation(
        snapshot, next_satisfied, completion_time, next_late, next_min_satisfied_at
    )


def _current_value(requirement, item_counts, stats, latest):
    if requirement.kind is RequirementKind.ITEM:
        if item_counts is None:
            return None, None
        return float(item_counts.get(requirement.target, 0)), None
    if requirement.kind is RequirementKind.PROGRESS:
        field = PROGRESS_TARGET_FIELDS.get(requirement.target)
        value = getattr(latest, field, None) if latest is not None and field else None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None, None
        return (parsed if isfinite(parsed) else None), None
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
    if requirement.kind in {RequirementKind.ITEM, RequirementKind.PROGRESS}:
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
    target_stage = _target_stage(deadline)
    if target_stage is None:
        return RequirementStatus.NEUTRAL, None
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


def _snapshot_observation_precedes_deadline(requirement, deadline, runtime) -> bool:
    if requirement.kind not in {RequirementKind.STAT, RequirementKind.PROGRESS}:
        return False
    latest = runtime.latest_snapshot
    if latest is None:
        return deadline.kind is not DeadlineKind.NONE
    target_stage = _target_stage(deadline)
    if target_stage is None:
        return False
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


def _target_stage(deadline: RequirementDeadline) -> int | None:
    """Return a supported tier for the selected deadline mode."""
    stage = int(deadline.stage or 0)
    if deadline.kind is DeadlineKind.STAGE_START:
        return stage if stage in {2, 3} else None
    return max(1, min(4, stage or 1))


def _row_sort_key(row: BuildProgressionRow):
    untimed = row.deadline.kind is DeadlineKind.NONE
    delta = row.time_delta_seconds
    if row.status is RequirementStatus.SATISFIED:
        group = 3
    elif row.status is RequirementStatus.OVERDUE:
        group = 2
    elif untimed:
        group = 0
    else:
        group = 1
    # Late rows that are not fully satisfied (working on max/cap)
    # sort among active rows, not among completed.
    if row.late and row.status is not RequirementStatus.SATISFIED:
        group = 0  # treat as untimed active
    deadline_rank = delta if delta is not None else float("inf")
    return (
        group,
        deadline_rank,
        row.order,
    )
