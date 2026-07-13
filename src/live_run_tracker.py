from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
import time
from typing import Any, Callable, Iterable
from uuid import uuid4

import copy
import threading
from functools import wraps

import run_summary
from gui_styles import PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
from player_stats import DisabledItemsReadResult, DisabledItemsReadStatus
from stat_label_abbreviations import abbreviate_stat_label

POWERUP_MAP_CONTEXT_TTL_SECONDS = 15.0
FAST_STAGE_TIMER_TTL_SECONDS = 2.0
POWERUPS_SNAPSHOT_TTL_SECONDS = 1.5


def with_lock(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with getattr(self, "_lock"):
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class LiveRunSnapshot:
    captured_at: float
    stats: dict[str, Any]
    items: tuple[str, ...] = ()
    items_available: bool = True
    weapons: tuple[Any, ...] = ()
    weapons_available: bool = False
    tomes: tuple[Any, ...] = ()
    tomes_available: bool = False
    banishes: tuple[str, ...] = ()
    disabled_items: tuple[str, ...] = ()
    disabled_items_available: bool = False
    damage_sources: tuple[Any, ...] = ()
    damage_sources_available: bool = False
    chests_per_minute: float | None = None
    game_time_seconds: float | None = None
    stage_timer_seconds: float | None = None
    stage_time_seconds: float | None = None
    stage_duration_seconds: float | None = None
    mob_kills: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0
    stage_index: int | None = None
    chests_total: int | None = None
    pots_total: int | None = None


@dataclass(frozen=True)
class TrackedItemRule:
    id: str
    label: str
    item_names: tuple[str, ...]
    mode: str
    before_stage: int | None = None
    before_seconds: float | None = None
    max_copies: int | None = None


@dataclass(frozen=True)
class TrackedItemEvent:
    rule_id: str
    item_name: str
    gained_count: int
    game_time_seconds: float | None
    stage_index: int
    map_seed: int | None
    captured_at: float


@dataclass(frozen=True)
class ChaosTomeStatTotal:
    stat_id: int
    label: str
    value: float
    value_format: Any
    rolls: int

    @property
    def display_delta(self) -> str:
        from player_stats import format_chaos_tome_stat_delta

        return format_chaos_tome_stat_delta(self.label, self.value, self.value_format)


@dataclass(frozen=True)
class LiveRunTrackerState:
    status: str
    updated_at: float
    run_id: str | None
    current_stage_index: int
    latest_snapshot: LiveRunSnapshot | None
    tracked_items: list[dict[str, Any]]
    stage_summary: list[dict[str, Any]]


class FeatureAvailability(str, Enum):
    NEVER_LOADED = "never_loaded"
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class RunLifecycle(str, Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass(frozen=True)
class FeatureStatus:
    availability: FeatureAvailability
    last_success_at: float | None = None
    last_error: str | None = None
    failure_count: int = 0


@dataclass(frozen=True)
class RuntimeStateSnapshot:
    """Coherent, read-only runtime view for projections and worker threads."""
    status: str
    lifecycle: RunLifecycle
    updated_at: float
    run_id: str | None
    current_stage_index: int
    latest_snapshot: LiveRunSnapshot | None
    tracked_items: tuple[dict[str, Any], ...]
    stage_summary: tuple[dict[str, Any], ...]
    chest_stats: ChestStatsSnapshot
    kps: dict[str, int | None]
    feature_status: dict[str, FeatureStatus]
    chaos_tome: Any | None
    powerups: PowerupsSnapshot
    powerup_map_context: PowerupMapContext | None
    fast_stage_timer: FastStageTimerContext | None
    graveyard_main_map_events_active: bool


@dataclass(frozen=True)
class FastStageTimerContext:
    captured_at: float = 0.0
    stage_timer_seconds: float | None = None
    stage_index: int | None = None
    stage_duration_seconds: float | None = None


@dataclass(frozen=True)
class ChestStatsSnapshot:
    current_opened: int
    current_total: int
    keys_count: int
    paid: int
    key_procs: int
    free_chests: int | None
    opened_by_stage: dict[int, int]
    total_by_stage: dict[int, int]
    counters_available: bool
    expected_key_procs: float = 0.0
    expected_tracked_opens: int = 0
    expected_available: bool = False
    total_opened_minimum: int | None = None
    total_opened_is_minimum: bool = False

    @property
    def total_opened(self) -> int | None:
        if self.total_opened_minimum is not None:
            return self.total_opened_minimum
        if any(int(value) < 0 for value in self.opened_by_stage.values()):
            return None
        return sum(self.opened_by_stage.values())

    @property
    def total_chests(self) -> int:
        return sum(self.total_by_stage.values())

    @property
    def normal_opened(self) -> int:
        return self.paid + self.key_procs


@dataclass(frozen=True)
class PowerupEffectState:
    effect_id: int
    name: str
    pickup_ui: str | None
    expires_ui: str | None
    pickup_offset_seconds: float
    expiration_offset_seconds: float
    remaining_seconds: float
    duration_seconds: float
    stage_index: int | None
    raw_stage_pickup: float
    raw_stage_expiration: float


@dataclass(frozen=True)
class PowerupsSnapshot:
    active: tuple[PowerupEffectState, ...] = ()
    powerup_multiplier: float | None = None
    powerup_multiplier_display: str = "--"
    standard_duration_seconds: float | None = None
    clock_duration_seconds: float | None = None
    stage_index: int | None = None
    stage_time_seconds: float | None = None
    captured_at: float = 0.0
    available: bool = False


@dataclass(frozen=True)
class _PowerupUiContext:
    timer_value: float
    timer_limit: float | None


@dataclass(frozen=True)
class PowerupMapContext:
    is_graveyard: bool = False
    captured_at: float = 0.0
    activity_max: dict[str, int] | None = None

    @classmethod
    def from_activity_max(
        cls,
        activity_max: dict[str, int],
        *,
        captured_at: float = 0.0,
    ) -> "PowerupMapContext":
        labels = set(activity_max)
        is_graveyard = bool(
            {"Pumpkin", "Gravestones", "Crypt Chests", "Crypt Pots"} & labels
            or int(activity_max.get("Chests", 0) or 0) == 69
        )
        return cls(
            is_graveyard=is_graveyard,
            captured_at=captured_at,
            activity_max=dict(activity_max),
        )


@dataclass
class _RunState:
    run_id: str | None = None
    lifecycle: RunLifecycle = RunLifecycle.WAITING
    snapshots: deque[LiveRunSnapshot] = field(default_factory=deque)
    current_stage_index: int = 1
    last_update_at: float | None = None
    last_failed_at: float | None = None
    last_no_game_at: float | None = None
    cached_stage_summary: list[dict[str, Any]] | None = None
    disabled_items_cache: tuple[str, ...] | None = None


@dataclass
class _CombatState:
    recent_kills_history: deque[tuple[float, int]] = field(default_factory=deque)
    ui_kps_baseline: tuple[float, int] | None = None
    ui_kps_value: int | None = None


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


@dataclass
class _ChaosTomeState:
    chaos_tome_level: int | None = None
    chaos_modifier_baselines: dict[int, tuple[float, ...]] = field(default_factory=dict)
    chaos_totals: dict[int, ChaosTomeStatTotal] = field(default_factory=dict)
    chaos_ambiguous_rolls: int = 0
    chaos_available_rolls: int = 0
    chaos_unbudgeted_candidates: dict[tuple[int, int], tuple[float, int]] = field(default_factory=dict)


@dataclass
class _PowerupState:
    powerups_snapshot: PowerupsSnapshot = field(default_factory=PowerupsSnapshot)
    powerup_map_context: PowerupMapContext = field(default_factory=PowerupMapContext)
    fast_stage_timer_context: FastStageTimerContext = field(default_factory=FastStageTimerContext)
    graveyard_final_swarm_timer_is_zero: bool = False


@dataclass
class _TrackedItemState:
    tracked_item_rules: tuple[TrackedItemRule, ...] = ()
    previous_item_counts: dict[str, int] | None = None
    tracked_events: list[TrackedItemEvent] = field(default_factory=list)
    tracked_counts: dict[str, int] = field(default_factory=dict)
    combo_run_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class _AvailabilityState:
    feature_status: dict[str, FeatureStatus] = field(default_factory=dict)


DEFAULT_TRACKED_ITEM_RULES: tuple[TrackedItemRule, ...] = (
    TrackedItemRule(
        id="anvils_map_1",
        label="Anvils Map 1",
        item_names=("Anvil",),
        mode="map_1_only",
    ),
    TrackedItemRule(
        id="anvils_total",
        label="Anvils",
        item_names=("Anvil",),
        mode="all_run",
    ),
)

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


class LiveRunTracker:
    _STATE_FIELDS = {
        **{name: "_run_state" for name in (
            "run_id", "_lifecycle", "snapshots", "current_stage_index",
            "_last_update_at", "_last_failed_at", "_last_no_game_at",
            "_cached_stage_summary", "_disabled_items_cache",
        )},
        **{name: "_combat_state" for name in (
            "_recent_kills_history", "_ui_kps_baseline", "_ui_kps_value",
        )},
        **{name: "_chest_state" for name in (
            "_chests_opened", "_chests_total", "_keys_count", "_paid_chest_opens",
            "_key_chest_procs", "_free_chest_opens", "_chest_counters_available",
            "_chest_history_incomplete", "_total_opened_minimum", "_total_opened_is_minimum",
            "_expected_key_procs", "_expected_tracked_opens", "_expected_chests_bought",
            "_expected_keys_count", "_expected_available", "_expected_detected_run_reset",
            "_stage_ptrs_seen", "_stage_numbers_by_ptr", "_chests_opened_by_stage",
            "_chests_total_by_stage",
        )},
        **{name: "_chaos_state" for name in (
            "_chaos_tome_level", "_chaos_modifier_baselines", "_chaos_totals",
            "_chaos_ambiguous_rolls", "_chaos_available_rolls", "_chaos_unbudgeted_candidates",
        )},
        **{name: "_powerup_state" for name in (
            "_powerups_snapshot", "_powerup_map_context", "_fast_stage_timer_context",
            "_graveyard_final_swarm_timer_is_zero",
        )},
        **{name: "_tracked_item_state" for name in (
            "tracked_item_rules", "_previous_item_counts", "_tracked_events",
            "_tracked_counts", "_combo_run_counts",
        )},
        "_feature_status": "_availability_state",
    }

    def __getattr__(self, name: str):
        state_name = self._STATE_FIELDS.get(name)
        if state_name is not None:
            state = object.__getattribute__(self, state_name)
            attr_name = name if name == "tracked_item_rules" else name.lstrip("_")
            return getattr(state, attr_name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        state_name = self._STATE_FIELDS.get(name)
        if state_name is not None and state_name in self.__dict__:
            state = self.__dict__[state_name]
            attr_name = name if name == "tracked_item_rules" else name.lstrip("_")
            setattr(state, attr_name, value)
            return
        object.__setattr__(self, name, value)

    def __init__(
        self,
        *,
        tracked_item_rules: Iterable[TrackedItemRule] = DEFAULT_TRACKED_ITEM_RULES,
        max_snapshots: int = 3600,
        stale_after_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_snapshots = max(1, int(max_snapshots))
        self.stale_after_seconds = max(0.1, float(stale_after_seconds))
        self.clock = clock
        self._run_state = _RunState(snapshots=deque(maxlen=self.max_snapshots))
        self._combat_state = _CombatState()
        self._chest_state = _ChestState()
        self._chaos_state = _ChaosTomeState()
        self._powerup_state = _PowerupState()
        self._tracked_item_state = _TrackedItemState()
        self._availability_state = _AvailabilityState(feature_status={
            name: FeatureStatus(FeatureAvailability.NEVER_LOADED)
            for name in (
                "run",
                "player",
                "combat",
                "progression",
                "world",
                "powerups",
                "chaos_tome",
                "expected_chests",
                "stage_timer",
            )
        })
        self.tracked_item_rules = tuple(tracked_item_rules)
        self._tracked_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._combo_run_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._lock = threading.RLock()

    @with_lock
    def update(self, snapshot: LiveRunSnapshot) -> None:
        self._cached_stage_summary = None
        now = self.clock()
        self._last_update_at = now
        self._last_failed_at = None
        self._last_no_game_at = None
        self._lifecycle = RunLifecycle.ACTIVE
        self._mark_feature_success_unlocked("run", now)
        self._mark_feature_success_unlocked("player", now)
        self._mark_feature_success_unlocked("combat", now)
        self._mark_feature_success_unlocked("progression", now)
        self._mark_feature_success_unlocked("world", now)
        reset_for_snapshot = False
        if not self._is_active_snapshot(snapshot):
            if not self.snapshots:
                return
            self.snapshots.append(snapshot)
            return

        if self._should_reset_for_snapshot(snapshot):
            self._reset_for_new_run()
            reset_for_snapshot = True

        if self.run_id is None:
            self.run_id = uuid4().hex
        if reset_for_snapshot:
            self.current_stage_index = run_summary.resolve_initial_stage_index(snapshot)

        previous_snapshot = self.snapshots[-1] if self.snapshots else None
        if previous_snapshot is not None and self._is_active_snapshot(previous_snapshot):
            self.current_stage_index = min(
                max(
                    run_summary.resolve_next_stage_index(
                        self.current_stage_index,
                        previous_snapshot,
                        snapshot,
                    ),
                    self.current_stage_index,
                ),
                4,
            )

        self.snapshots.append(snapshot)
        if snapshot.disabled_items_available:
            self._disabled_items_cache = snapshot.disabled_items
        self._process_item_deltas(snapshot)

    @with_lock
    def mark_read_failed(self, *, no_game: bool = False) -> None:
        now = self.clock()
        self._last_failed_at = now
        self._mark_feature_failure_unlocked("run", now, "game memory read failed")
        if no_game:
            self._last_no_game_at = now
            self._recent_kills_history.clear()
            self._fast_stage_timer_context = FastStageTimerContext()
            self._reset_ui_kps_unlocked()

    @with_lock
    def mark_run_completed(self) -> None:
        """Freeze the last active run for local post-run inspection."""
        if self.snapshots:
            self._lifecycle = RunLifecycle.COMPLETED

    @with_lock
    def mark_feature_failed(self, feature: str, error: Exception | str | None = None) -> None:
        self._mark_feature_failure_unlocked(feature, self.clock(), str(error or "read failed"))

    @with_lock
    def mark_feature_available(self, feature: str) -> None:
        self._mark_feature_success_unlocked(feature, self.clock())

    @with_lock
    def set_tracked_item_rules(self, rules: Iterable[TrackedItemRule]) -> None:
        new_rules = tuple(rules)
        if new_rules == self.tracked_item_rules:
            return
        old_rules_by_id = {rule.id: rule for rule in self.tracked_item_rules}
        old_counts = dict(self._tracked_counts)
        old_combo_run_counts = dict(self._combo_run_counts)
        preserved_rule_ids = {
            rule.id
            for rule in new_rules
            if old_rules_by_id.get(rule.id) == rule
        }
        old_events = list(self._tracked_events)
        self.tracked_item_rules = new_rules
        self._tracked_counts = {
            rule.id: old_counts.get(rule.id, 0) if rule.id in preserved_rule_ids else 0
            for rule in self.tracked_item_rules
        }
        self._combo_run_counts = {
            rule.id: old_combo_run_counts.get(rule.id, 0) if rule.id in preserved_rule_ids else 0
            for rule in self.tracked_item_rules
        }
        self._tracked_events = [
            event for event in old_events if event.rule_id in preserved_rule_ids
        ]
        self._reset_current_run_item_baseline(reset_combo_counts=False)
        if self.snapshots and self.snapshots[-1].items_available:
            current_counts = run_summary.item_counts(self.snapshots[-1].items)
            self._previous_item_counts = current_counts
            for rule in self.tracked_item_rules:
                if rule.id not in preserved_rule_ids and len(rule.item_names) > 1:
                    self._combo_run_counts[rule.id] = self._combo_count_for_rule(rule, current_counts)

    @with_lock
    def stage_summary_rows(self) -> list[dict[str, Any]]:
        """
        Returns a summary of stages in the current run.
        The result is cached to avoid double calculation in the same update tick,
        and returned as a deep copy to prevent mutation bugs by callers.
        """
        return self._stage_summary_rows_unlocked()

    @with_lock
    def tracked_item_rows(self) -> list[dict[str, Any]]:
        return self._tracked_item_rows_unlocked()

    @with_lock
    def tracked_item_rows_for_rules(self, rules: Iterable[TrackedItemRule]) -> list[dict[str, Any]]:
        return self._tracked_item_rows_for_rules_unlocked(tuple(rules))

    @with_lock
    def update_chaos_tome(
        self,
        *,
        chaos_level: int | None,
        permanent_modifiers: dict[int, tuple[Any, ...]],
    ) -> None:
        self._mark_feature_success_unlocked("chaos_tome", self.clock())
        if chaos_level is None:
            # TomeInventory may be unavailable while the game mutates its
            # dictionaries. A missing read is not evidence that the tome was
            # removed; run resets and level decreases handle real resets.
            return

        current_level = max(0, int(chaos_level))
        current_baselines = {
            int(stat_id): tuple(float(getattr(m, "value", 0.0)) for m in (modifiers or ()))
            for stat_id, modifiers in (permanent_modifiers or {}).items()
        }

        if self._chaos_tome_level is None:
            if current_level <= 0:
                return
            self._chaos_tome_level = current_level
            self._chaos_modifier_baselines = {}
            self._chaos_available_rolls = current_level
            self._chaos_unbudgeted_candidates = {}
            self._record_chaos_modifier_deltas(permanent_modifiers)
            return

        if current_level < self._chaos_tome_level:
            return

        if current_level > self._chaos_tome_level:
            self._chaos_available_rolls += (current_level - self._chaos_tome_level)
            self._chaos_tome_level = current_level

        self._record_chaos_modifier_deltas(permanent_modifiers)

    @with_lock
    def chaos_tome_summary_parts(self) -> list[str]:
        totals = sorted(
            self._chaos_totals.values(),
            key=chaos_tome_stat_sort_key,
        )
        parts: list[str] = []
        for total in totals:
            label = abbreviate_stat_label(total.label)
            parts.append(f"{label} {total.display_delta}")
        return parts

    @with_lock
    def chaos_tome_snapshot(self):
        if self._chaos_tome_level is None:
            return None

        from player_stats import ChaosTomeSnapshot, ChaosTomeStatSnapshot, PlayerStatFormat

        stats = tuple(
            ChaosTomeStatSnapshot(
                stat_id=total.stat_id,
                label=total.label,
                value=total.value,
                value_format=total.value_format or PlayerStatFormat.FLAT,
                rolls=total.rolls,
            )
            for total in sorted(
                self._chaos_totals.values(),
                key=chaos_tome_stat_sort_key,
            )
        )
        return ChaosTomeSnapshot(
            level=self._chaos_tome_level,
            stats=stats,
            ambiguous_rolls=self._chaos_ambiguous_rolls,
        )

    @with_lock
    def chaos_tome_level(self) -> int | None:
        return self._chaos_tome_level

    @with_lock
    def chaos_tome_ambiguous_rolls(self) -> int:
        return self._chaos_ambiguous_rolls

    @with_lock
    def state_snapshot(self) -> LiveRunTrackerState:
        """Return a coherent tracker view for consumers that need multiple fields."""
        now = self.clock()
        return LiveRunTrackerState(
            status=self._status_unlocked(now),
            updated_at=now,
            run_id=self.run_id,
            current_stage_index=self.current_stage_index,
            latest_snapshot=self.snapshots[-1] if self.snapshots else None,
            tracked_items=self._tracked_item_rows_unlocked(),
            stage_summary=self._stage_summary_rows_unlocked(),
        )

    @with_lock
    def runtime_snapshot(self) -> RuntimeStateSnapshot:
        """Return one immutable boundary object for consumer projections."""
        now = self.clock()
        map_context = self._fresh_powerup_map_context_unlocked()
        return RuntimeStateSnapshot(
            status=self._status_unlocked(now),
            lifecycle=self._lifecycle,
            updated_at=now,
            run_id=self.run_id,
            current_stage_index=self.current_stage_index,
            latest_snapshot=copy.deepcopy(self._latest_snapshot_unlocked()),
            tracked_items=tuple(self._tracked_item_rows_unlocked()),
            stage_summary=tuple(self._stage_summary_rows_unlocked()),
            chest_stats=self._get_chest_stats_unlocked(),
            kps={
                "current": self._ui_kps_value,
                "minute_avg": self._average_kps_for_window_unlocked(60.0),
                "five_minute_avg": self._average_kps_for_window_unlocked(300.0),
                "run_avg": self._current_run_avg_kps_unlocked(),
            },
            feature_status=self._feature_status_snapshot_unlocked(now),
            chaos_tome=self.chaos_tome_snapshot(),
            powerups=self._fresh_powerups_snapshot_unlocked(),
            powerup_map_context=copy.deepcopy(map_context),
            fast_stage_timer=copy.deepcopy(self._fresh_fast_stage_timer_context_unlocked()),
            graveyard_main_map_events_active=self._graveyard_main_map_events_active_unlocked(),
        )

    def _stage_summary_rows_unlocked(self) -> list[dict[str, Any]]:
        if self._cached_stage_summary is None:
            self._cached_stage_summary = run_summary.build_stage_summary(tuple(self.snapshots))
        return copy.deepcopy(self._cached_stage_summary)

    def _tracked_item_rows_unlocked(self) -> list[dict[str, Any]]:
        return self._tracked_item_rows_for_rules_unlocked(self.tracked_item_rules)

    def _tracked_item_rows_for_rules_unlocked(self, rules: Iterable[TrackedItemRule]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for rule in rules:
            rows.append(
                {
                    "id": rule.id,
                    "label": rule.label,
                    "count": int(self._tracked_counts.get(rule.id, 0)),
                    "mode": rule.mode,
                }
            )
        return rows

    @with_lock
    def track_kills(self, game_time_seconds: float | None, current_kills: int | None) -> None:
        if game_time_seconds is None or current_kills is None:
            return
        self._mark_feature_success_unlocked("combat", self.clock())

        if self._recent_kills_history:
            last_time, last_kills = self._recent_kills_history[-1]
            if current_kills < last_kills or game_time_seconds < last_time:
                self._recent_kills_history.clear()
                self._reset_ui_kps_unlocked()
            elif game_time_seconds == last_time:
                # Prevent deque bloat when the game is paused (time is frozen)
                self._recent_kills_history[-1] = (game_time_seconds, max(last_kills, current_kills))
                return

        self._recent_kills_history.append((game_time_seconds, current_kills))

        while self._recent_kills_history and self._recent_kills_history[0][0] < game_time_seconds - 300.0:
            self._recent_kills_history.popleft()

        self._track_ui_kps_unlocked(game_time_seconds, current_kills)

    @with_lock
    def current_kps(self) -> int | None:
        return self._average_kps_for_window_unlocked(3.0)

    @with_lock
    def current_minute_avg_kps(self) -> int | None:
        return self._average_kps_for_window_unlocked(60.0)

    @with_lock
    def current_five_minute_avg_kps(self) -> int | None:
        return self._average_kps_for_window_unlocked(300.0)

    @with_lock
    def current_ui_kps(self) -> int | None:
        return self._ui_kps_value

    @with_lock
    def current_run_avg_kps(self) -> int | None:
        return self._current_run_avg_kps_unlocked()

    def _current_run_avg_kps_unlocked(self) -> int | None:
        if not self._recent_kills_history:
            return None

        newest_time, newest_kills = self._recent_kills_history[-1]
        if newest_time <= 0:
            return None

        return int(round(newest_kills / newest_time))

    @with_lock
    def run_identity(self) -> tuple[str | None, int]:
        return self.run_id, self.current_stage_index

    @with_lock
    def latest_snapshot(self) -> LiveRunSnapshot | None:
        return self._latest_snapshot_unlocked()

    @with_lock
    def powerup_map_context(self) -> PowerupMapContext | None:
        return self._fresh_powerup_map_context_unlocked()

    @with_lock
    def update_fast_stage_timer(
        self,
        *,
        stage_timer_seconds: float | None,
        stage_index: int | None,
        stage_duration_seconds: float | None,
    ) -> None:
        if stage_timer_seconds is None:
            self._fast_stage_timer_context = FastStageTimerContext()
            return
        self._mark_feature_success_unlocked("progression", self.clock())
        self._fast_stage_timer_context = FastStageTimerContext(
            captured_at=self.clock(),
            stage_timer_seconds=float(stage_timer_seconds),
            stage_index=None if stage_index is None else int(stage_index),
            stage_duration_seconds=(
                None
                if stage_duration_seconds is None
                else float(stage_duration_seconds)
            ),
        )

    @with_lock
    def fast_stage_timer_context(self) -> FastStageTimerContext | None:
        return self._fresh_fast_stage_timer_context_unlocked()

    @with_lock
    def graveyard_main_map_events_active(self) -> bool:
        return self._graveyard_main_map_events_active_unlocked()

    def _graveyard_main_map_events_active_unlocked(self) -> bool:
        map_context = self._fresh_powerup_map_context_unlocked()
        if not map_context or not map_context.is_graveyard:
            return False
        activities = map_context.activity_max or {}
        return (
            "Crypt Chests" not in activities
            and "Crypt Pots" not in activities
            and self._graveyard_final_swarm_timer_is_zero
        )

    def _latest_snapshot_unlocked(self) -> LiveRunSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def _fresh_fast_stage_timer_context_unlocked(self) -> FastStageTimerContext | None:
        context = self._fast_stage_timer_context
        if context.captured_at <= 0:
            return None
        if self.clock() - context.captured_at > FAST_STAGE_TIMER_TTL_SECONDS:
            return None
        return context

    def _fresh_powerups_snapshot_unlocked(self) -> PowerupsSnapshot:
        snapshot = self._powerups_snapshot
        if not snapshot.available:
            return snapshot
        if snapshot.captured_at <= 0:
            return PowerupsSnapshot()
        if self.clock() - snapshot.captured_at > POWERUPS_SNAPSHOT_TTL_SECONDS:
            return PowerupsSnapshot()
        return snapshot

    @with_lock
    def has_active_run(self) -> bool:
        latest = self._latest_snapshot_unlocked()
        return bool(
            latest is not None
            and self._last_no_game_at is None
            and self._is_active_snapshot(latest)
        )

    @with_lock
    def get_disabled_items(self) -> DisabledItemsReadResult:
        if self._disabled_items_cache is None:
            return DisabledItemsReadResult(DisabledItemsReadStatus.NOT_INITIALIZED)
        return DisabledItemsReadResult(
            DisabledItemsReadStatus.AVAILABLE,
            self._disabled_items_cache,
        )

    @with_lock
    def update_powerup_map_context(self, context: PowerupMapContext) -> None:
        if context.captured_at <= 0:
            context = PowerupMapContext(
                is_graveyard=context.is_graveyard,
                captured_at=self.clock(),
                activity_max=context.activity_max,
            )
        self._powerup_map_context = context

    def _fresh_powerup_map_context_unlocked(self) -> PowerupMapContext | None:
        context = self._powerup_map_context
        if context.captured_at <= 0:
            return None
        if self.clock() - context.captured_at > POWERUP_MAP_CONTEXT_TTL_SECONDS:
            return None
        return context

    @with_lock
    def update_powerups(
        self,
        snapshot: Any,
        *,
        map_context: PowerupMapContext | None = None,
    ) -> bool:
        if map_context is not None:
            if map_context.captured_at <= 0:
                map_context = PowerupMapContext(
                    is_graveyard=map_context.is_graveyard,
                    captured_at=self.clock(),
                    activity_max=map_context.activity_max,
                )
            self._powerup_map_context = map_context

        for health_name in (
            "status_effects_health",
            "timing_health",
        ):
            health = getattr(snapshot, health_name, None)
            if health is None:
                continue
            if bool(getattr(health, "available", False)) and bool(
                getattr(health, "complete", False)
            ):
                continue
            reason = str(
                getattr(health, "failure_reason", None)
                or "powerup_snapshot_incomplete"
            )
            self._mark_feature_failure_unlocked("powerups", self.clock(), reason)
            return False

        self._mark_feature_success_unlocked("powerups", self.clock())

        # Graveyard room transitions replace entries in the activity dictionary.
        # `crypt_timer` remains non-zero after leaving a crypt, so it cannot
        # identify the current room.
        fresh_map_context = self._fresh_powerup_map_context_unlocked()
        is_graveyard = bool(fresh_map_context and fresh_map_context.is_graveyard)

        if is_graveyard:
            final_swarm_timer = getattr(snapshot, "final_swarm_timer_seconds", None) if snapshot is not None else None
            try:
                swarm_val = float(final_swarm_timer)
            except (TypeError, ValueError):
                swarm_val = float("nan")
            self._graveyard_final_swarm_timer_is_zero = swarm_val == 0.0
        else:
            self._graveyard_final_swarm_timer_is_zero = False
        powerup_multiplier = getattr(snapshot, "powerup_multiplier", None)
        try:
            powerup_multiplier = float(powerup_multiplier)
        except (TypeError, ValueError):
            powerup_multiplier = None
        if powerup_multiplier is not None and not isfinite(powerup_multiplier):
            powerup_multiplier = None

        standard_duration = (
            15.0 * powerup_multiplier if powerup_multiplier is not None else None
        )
        clock_duration = (
            12.0 * powerup_multiplier if powerup_multiplier is not None else None
        )

        my_time = getattr(snapshot, "my_time_seconds", None)
        stage_timer = getattr(snapshot, "stage_timer_seconds", None)
        stage_time = getattr(snapshot, "stage_time_seconds", None)
        final_swarm_timer = getattr(snapshot, "final_swarm_timer_seconds", None)
        crypt_timer = getattr(snapshot, "crypt_timer_seconds", None)
        stage_index = getattr(snapshot, "stage_index", None)
        active: list[PowerupEffectState] = []

        if (
            my_time is not None
            and stage_timer is not None
            and stage_time is not None
            and powerup_multiplier is not None
            and int(stage_index if stage_index is not None else -1) < 3
        ):
            for effect in getattr(snapshot, "effects", ()) or ():
                try:
                    effect_id = int(getattr(effect, "effect_id", -1))
                    added_time_raw = getattr(effect, "added_time", None)
                    added_time = (
                        float(added_time_raw) if added_time_raw is not None else float("nan")
                    )
                    expiration_time = float(getattr(effect, "expiration_time", 0.0))
                    remaining = expiration_time - float(my_time)
                    if remaining <= 0 or not isfinite(remaining):
                        continue
                    base_duration = 12.0 if effect_id == 4 else 15.0
                    duration = base_duration * powerup_multiplier
                    pickup_time = expiration_time - duration
                    ui_context = self._resolve_powerup_ui_context_unlocked(
                        my_time=float(my_time),
                        pickup_time=pickup_time,
                        stage_timer=float(stage_timer),
                        stage_time=float(stage_time),
                        final_swarm_timer=final_swarm_timer,
                        crypt_timer=crypt_timer,
                    )
                    if (
                        isfinite(added_time)
                        and added_time <= expiration_time
                        and added_time <= float(my_time)
                    ):
                        added_time_ui_context = self._resolve_powerup_ui_context_unlocked(
                            my_time=float(my_time),
                            pickup_time=added_time,
                            stage_timer=float(stage_timer),
                            stage_time=float(stage_time),
                            final_swarm_timer=final_swarm_timer,
                            crypt_timer=crypt_timer,
                        )
                        if added_time_ui_context == ui_context:
                            pickup_time = added_time
                            ui_context = added_time_ui_context
                    raw_pickup = ui_context.timer_value + (pickup_time - float(my_time))
                    raw_expiration = ui_context.timer_value + (
                        expiration_time - float(my_time)
                    )
                    if not isfinite(raw_pickup) or not isfinite(raw_expiration):
                        continue
                except (TypeError, ValueError, OverflowError):
                    continue
                active.append(
                    PowerupEffectState(
                        effect_id=effect_id,
                        name=str(getattr(effect, "name", effect_id)),
                        pickup_ui=(
                            self._format_ui_stage_time(
                                raw_pickup,
                                ui_context.timer_limit,
                            )
                            if ui_context.timer_limit is not None
                            else None
                        ),
                        expires_ui=(
                            self._format_ui_stage_time(
                                raw_expiration,
                                ui_context.timer_limit,
                            )
                            if ui_context.timer_limit is not None
                            else None
                        ),
                        pickup_offset_seconds=pickup_time - float(my_time),
                        expiration_offset_seconds=expiration_time - float(my_time),
                        remaining_seconds=remaining,
                        duration_seconds=duration,
                        stage_index=stage_index,
                        raw_stage_pickup=raw_pickup,
                        raw_stage_expiration=raw_expiration,
                    )
                )

        active.sort(key=lambda effect: effect.raw_stage_expiration, reverse=True)
        self._powerups_snapshot = PowerupsSnapshot(
            active=tuple(active),
            powerup_multiplier=powerup_multiplier,
            powerup_multiplier_display=str(
                getattr(snapshot, "powerup_multiplier_display", "--") or "--"
            ),
            standard_duration_seconds=standard_duration,
            clock_duration_seconds=clock_duration,
            stage_index=stage_index,
            stage_time_seconds=stage_time,
            captured_at=self.clock(),
            available=True,
        )
        return True

    @with_lock
    def clear_powerups(self) -> None:
        self._powerups_snapshot = PowerupsSnapshot()

    @with_lock
    def powerups_snapshot(self) -> PowerupsSnapshot:
        return self._fresh_powerups_snapshot_unlocked()

    @with_lock
    def format_powerups_summary(self, *, include_left_word: bool = True) -> str:
        snapshot = self._fresh_powerups_snapshot_unlocked()
        if not snapshot.available:
            return "Powerups: --"
        powerups_text = self._format_powerups_text_unlocked(
            snapshot,
            include_left_word=include_left_word,
        )
        if snapshot.powerup_multiplier_display == "--":
            return f"Powerups: {powerups_text}"
        return f"Powerups: {powerups_text} (PM {snapshot.powerup_multiplier_display})"

    @with_lock
    def powerups_summary_text(self, *, include_left_word: bool = True) -> str:
        snapshot = self._fresh_powerups_snapshot_unlocked()
        if not snapshot.available:
            return "--"
        return self._format_powerups_text_unlocked(
            snapshot,
            include_left_word=include_left_word,
        )

    def _format_powerups_text_unlocked(
        self,
        snapshot: PowerupsSnapshot,
        *,
        include_left_word: bool = True,
    ) -> str:
        durations_text = None
        if (
            snapshot.standard_duration_seconds is not None
            and snapshot.clock_duration_seconds is not None
        ):
            durations_text = (
                "Durations: "
                f"standard {self._format_duration_seconds(snapshot.standard_duration_seconds)}s, "
                f"clock {self._format_duration_seconds(snapshot.clock_duration_seconds)}s"
            )
        if snapshot.active:
            parts = []
            suffix = " left" if include_left_word else ""
            for effect in snapshot.active:
                duration_text = (
                    f"({self._format_duration_seconds(effect.remaining_seconds)}s{suffix})"
                )
                if effect.pickup_ui is None or effect.expires_ui is None:
                    parts.append(f"{effect.name} {duration_text}")
                else:
                    parts.append(
                        f"{effect.name} {effect.pickup_ui} -> {effect.expires_ui} "
                        f"{duration_text}"
                    )
            if durations_text is not None:
                parts.append(durations_text)
            return " | ".join(parts)
        if durations_text is None:
            return "none active"
        return f"none active | {durations_text}"

    @with_lock
    def update_chests_and_keys(self, chests_opened: int, chests_total: int, keys_count: int) -> None:
        self._mark_feature_success_unlocked("progression", self.clock())
        self._chests_opened = chests_opened
        self._chests_total = chests_total
        self._keys_count = keys_count

        latest = self.latest_snapshot()
        stage_ptr = latest.stage_ptr if (latest and latest.stage_ptr) else 0
        raw_stage_index = int(getattr(latest, "stage_index", -1) or 0) if latest else -1
        if stage_ptr == 0:
            return

        if stage_ptr not in self._stage_ptrs_seen:
            stage_num = self._raw_stage_to_human_stage(raw_stage_index)
            fallback_total = self._baseline_chest_total_for_history(chests_total)
            if not self._stage_ptrs_seen and raw_stage_index > 0 and stage_num > 1:
                self._chest_history_incomplete = True
                for missing_stage in range(1, stage_num):
                    self._chests_opened_by_stage.setdefault(missing_stage, -1)
                    self._chests_total_by_stage.setdefault(missing_stage, fallback_total)
            if stage_num <= 0:
                stage_num = max(self._chests_total_by_stage.keys(), default=0) + 1
            while stage_num in self._chests_total_by_stage:
                stage_num += 1
            self._stage_ptrs_seen.append(stage_ptr)
            self._stage_numbers_by_ptr[stage_ptr] = stage_num
            self._chests_opened_by_stage[stage_num] = 0
            self._chests_total_by_stage[stage_num] = (
                fallback_total if self._chest_history_incomplete else chests_total
            )

        stage_num = self._stage_numbers_by_ptr.get(stage_ptr, 0)
        if stage_num <= 0:
            return

        # Protect against stage transition race conditions (residual counts)
        ptr_order = self._stage_ptrs_seen.index(stage_ptr)
        if ptr_order > 0:
            prev_stage_ptr = self._stage_ptrs_seen[ptr_order - 1]
            prev_stage_num = self._stage_numbers_by_ptr.get(prev_stage_ptr, 0)
            prev_opened = max(0, self._chests_opened_by_stage.get(prev_stage_num, 0))
            current_opened = max(0, self._chests_opened_by_stage.get(stage_num, 0))
            if current_opened == 0 and chests_opened == prev_opened:
                chests_opened = 0

        current_opened = max(0, self._chests_opened_by_stage.get(stage_num, 0))
        self._chests_opened_by_stage[stage_num] = max(current_opened, chests_opened)
        self._chests_total_by_stage[stage_num] = max(self._chests_total_by_stage.get(stage_num, 0), chests_total)

    @with_lock
    def update_chest_counters(self, chests_bought: int, chests_purchased: int) -> bool:
        self._mark_feature_success_unlocked("progression", self.clock())
        chests_bought = int(chests_bought)
        chests_purchased = int(chests_purchased)
        known_total = sum(max(0, value) for value in self._chests_opened_by_stage.values())
        max_total = self._resolve_maximum_chest_total_unlocked()
        if max_total is None:
            return False
        total_opened = known_total
        total_opened_is_minimum = False
        if self._chest_history_incomplete:
            if chests_bought > max_total:
                return False
            total_opened = max(known_total, chests_bought)
            total_opened_is_minimum = True

        if not (
            0 <= chests_purchased <= chests_bought <= total_opened
        ):
            return False

        self._paid_chest_opens = chests_purchased
        self._key_chest_procs = chests_bought - chests_purchased
        self._free_chest_opens = (
            None if self._chest_history_incomplete else total_opened - chests_bought
        )
        self._total_opened_minimum = total_opened if total_opened_is_minimum else None
        self._total_opened_is_minimum = total_opened_is_minimum
        self._chest_counters_available = True
        return True

    def _resolve_maximum_chest_total_unlocked(self) -> int | None:
        total = 0
        for stage_num, stage_total in self._chests_total_by_stage.items():
            opened = int(self._chests_opened_by_stage.get(stage_num, 0))
            if opened < 0:
                total += max(0, int(stage_total))
            else:
                total += max(0, opened)
        return total

    @staticmethod
    def _raw_stage_to_human_stage(raw_stage_index: int) -> int:
        if raw_stage_index < 0:
            return 0
        return int(raw_stage_index) + 1

    @staticmethod
    def _baseline_chest_total_for_history(chests_total: int) -> int:
        total = max(0, int(chests_total))
        return 69 if total >= 69 else 46

    @staticmethod
    def key_proc_chance(keys_count: int) -> float:
        keys_count = max(0, int(keys_count))
        return (0.10 * keys_count) / ((0.10 * keys_count) + 1.0)

    @staticmethod
    def _format_duration_seconds(value: float) -> str:
        return str(int(round(value)))

    def _resolve_powerup_ui_context_unlocked(
        self,
        *,
        my_time: float,
        pickup_time: float,
        stage_timer: float,
        stage_time: float,
        final_swarm_timer: Any,
        crypt_timer: Any,
    ) -> _PowerupUiContext:
        map_context = self._fresh_powerup_map_context_unlocked()
        if map_context is None:
            return _PowerupUiContext(stage_timer, None)
        if not map_context.is_graveyard:
            return _PowerupUiContext(stage_timer, stage_time)

        try:
            final_swarm_value = float(final_swarm_timer)
        except (TypeError, ValueError):
            final_swarm_value = float("nan")
        if (
            isfinite(final_swarm_value)
            and final_swarm_value > 0.0
            and pickup_time >= my_time - final_swarm_value
        ):
            return _PowerupUiContext(final_swarm_value, 0.0)

        try:
            crypt_value = float(crypt_timer)
        except (TypeError, ValueError):
            crypt_value = float("nan")
        if (
            isfinite(crypt_value)
            and crypt_value > 0.0
            and stage_timer <= 1.0
            and pickup_time >= my_time - crypt_value
        ):
            return _PowerupUiContext(crypt_value, None)

        graveyard_stage_limit = 960.0
        return _PowerupUiContext(stage_timer, graveyard_stage_limit)

    @staticmethod
    def _format_ui_stage_time(raw_stage_timer: float, stage_time: float) -> str:
        if raw_stage_timer <= stage_time:
            value = max(0.0, stage_time - raw_stage_timer)
            prefix = ""
        else:
            value = raw_stage_timer - stage_time
            prefix = "+"
        total_seconds = max(0, int(value))
        return f"{prefix}{total_seconds // 60:02d}:{total_seconds % 60:02d}"

    @with_lock
    def track_expected_key_procs(self, chests_bought: int, keys_count: int) -> None:
        chests_bought = max(0, int(chests_bought))
        keys_count = max(0, int(keys_count))
        self._keys_count = keys_count

        if self._expected_chests_bought is None:
            self._expected_chests_bought = chests_bought
            self._expected_keys_count = keys_count
            self._expected_available = chests_bought == 0
            return

        if chests_bought < self._expected_chests_bought:
            self._expected_key_procs = 0.0
            self._expected_tracked_opens = 0
            self._expected_chests_bought = chests_bought
            self._expected_keys_count = keys_count
            self._expected_available = chests_bought == 0
            self._expected_detected_run_reset = True
            return

        delta = chests_bought - self._expected_chests_bought
        if delta > 0:
            # A key dropped by a chest can proc on that same chest, so the
            # post-open stack is the best observable probability sample.
            self._expected_key_procs += delta * self.key_proc_chance(keys_count)
            self._expected_tracked_opens += delta

        self._expected_chests_bought = chests_bought
        self._expected_keys_count = keys_count

    @with_lock
    def get_chest_stats(self) -> ChestStatsSnapshot:
        return self._get_chest_stats_unlocked()

    def _get_chest_stats_unlocked(self) -> ChestStatsSnapshot:
        opened_by_num = {
            stage_num: self._chests_opened_by_stage.get(stage_num, 0)
            for stage_num in sorted(self._chests_total_by_stage)
        }
        total_by_num = {
            stage_num: self._chests_total_by_stage.get(stage_num, 0)
            for stage_num in sorted(self._chests_total_by_stage)
        }
        return ChestStatsSnapshot(
            current_opened=self._chests_opened,
            current_total=self._chests_total,
            keys_count=self._keys_count,
            paid=self._paid_chest_opens,
            key_procs=self._key_chest_procs,
            free_chests=self._free_chest_opens,
            opened_by_stage=opened_by_num,
            total_by_stage=total_by_num,
            counters_available=self._chest_counters_available,
            expected_key_procs=self._expected_key_procs,
            expected_tracked_opens=self._expected_tracked_opens,
            expected_available=self._expected_available,
            total_opened_minimum=self._total_opened_minimum,
            total_opened_is_minimum=self._total_opened_is_minimum,
        )

    @with_lock
    def get_chests_and_keys(self) -> tuple[int, int, int, int, dict[int, int], dict[int, int]]:
        stats = self._get_chest_stats_unlocked()
        return (
            stats.current_opened,
            stats.current_total,
            stats.keys_count,
            stats.key_procs,
            stats.opened_by_stage,
            stats.total_by_stage,
        )

    @with_lock
    def status(self) -> str:
        now = self.clock()
        return self._status_unlocked(now)

    def _status_unlocked(self, now: float) -> str:
        if not self.snapshots:
            return "no_game" if self._last_no_game_at is not None else "waiting"
        if self._last_no_game_at is not None:
            return "no_game"
        if self._last_update_at is None or now - self._last_update_at > self.stale_after_seconds:
            return "stale"
        return "live"

    def _mark_feature_success_unlocked(self, feature: str, now: float) -> None:
        previous = self._feature_status.get(feature, FeatureStatus(FeatureAvailability.NEVER_LOADED))
        self._feature_status[feature] = FeatureStatus(
            availability=FeatureAvailability.FRESH,
            last_success_at=now,
            failure_count=previous.failure_count,
        )

    def _feature_status_snapshot_unlocked(self, now: float) -> dict[str, FeatureStatus]:
        statuses: dict[str, FeatureStatus] = {}
        for feature, status in self._feature_status.items():
            availability = status.availability
            if (
                availability is FeatureAvailability.FRESH
                and status.last_success_at is not None
                and now - status.last_success_at > self.stale_after_seconds
            ):
                availability = FeatureAvailability.STALE
            statuses[feature] = FeatureStatus(
                availability=availability,
                last_success_at=status.last_success_at,
                last_error=status.last_error,
                failure_count=status.failure_count,
            )
        return statuses

    def _mark_feature_failure_unlocked(self, feature: str, now: float, error: str) -> None:
        previous = self._feature_status.get(feature, FeatureStatus(FeatureAvailability.NEVER_LOADED))
        availability = (
            FeatureAvailability.STALE
            if previous.last_success_at is not None
            else FeatureAvailability.UNAVAILABLE
        )
        self._feature_status[feature] = FeatureStatus(
            availability=availability,
            last_success_at=previous.last_success_at,
            last_error=error,
            failure_count=previous.failure_count + 1,
        )

    def _reset_for_new_run(self) -> None:
        self.run_id = uuid4().hex
        self._lifecycle = RunLifecycle.ACTIVE
        self.snapshots.clear()
        self._recent_kills_history.clear()
        self._reset_ui_kps_unlocked()
        self.current_stage_index = 1
        self._chests_opened = 0
        self._chests_total = 46
        self._keys_count = 0
        self._paid_chest_opens = 0
        self._key_chest_procs = 0
        self._free_chest_opens = None
        self._chest_counters_available = False
        self._chest_history_incomplete = False
        self._total_opened_minimum = None
        self._total_opened_is_minimum = False
        if self._expected_detected_run_reset:
            self._expected_detected_run_reset = False
        else:
            self._expected_key_procs = 0.0
            self._expected_tracked_opens = 0
            self._expected_chests_bought = None
            self._expected_keys_count = None
            self._expected_available = False
        self._stage_ptrs_seen = []
        self._stage_numbers_by_ptr = {}
        self._chests_opened_by_stage = {}
        self._chests_total_by_stage = {}
        self._reset_current_run_item_baseline()
        self._reset_chaos_tracking()
        self._powerups_snapshot = PowerupsSnapshot()
        self._cached_stage_summary = None
        self._graveyard_final_swarm_timer_is_zero = False

    def _reset_tracking_only(self) -> None:
        self._reset_current_run_item_baseline()
        self._tracked_events = []
        self._tracked_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._combo_run_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._graveyard_final_swarm_timer_is_zero = False

    def _reset_current_run_item_baseline(self, *, reset_combo_counts: bool = True) -> None:
        self._previous_item_counts = None
        if reset_combo_counts:
            self._combo_run_counts = {rule.id: 0 for rule in self.tracked_item_rules}

    def _reset_chaos_tracking(self) -> None:
        self._chaos_tome_level = None
        self._chaos_modifier_baselines = {}
        self._chaos_totals = {}
        self._chaos_ambiguous_rolls = 0
        self._chaos_available_rolls = 0
        self._chaos_unbudgeted_candidates = {}

    def _reset_ui_kps_unlocked(self) -> None:
        self._ui_kps_baseline = None
        self._ui_kps_value = None

    def _average_kps_for_window_unlocked(self, window_seconds: float) -> int | None:
        if len(self._recent_kills_history) < 2:
            return None

        newest_time, newest_kills = self._recent_kills_history[-1]
        cutoff = newest_time - float(window_seconds)
        oldest_time, oldest_kills = self._recent_kills_history[0]
        for sample_time, sample_kills in self._recent_kills_history:
            if sample_time >= cutoff:
                oldest_time, oldest_kills = sample_time, sample_kills
                break

        time_delta = newest_time - oldest_time
        if time_delta <= 0:
            return None

        kills_delta = newest_kills - oldest_kills
        return int(round(kills_delta / time_delta))

    def _track_ui_kps_unlocked(self, game_time_seconds: float, current_kills: int) -> None:
        baseline = self._ui_kps_baseline
        current_sample = (float(game_time_seconds), int(current_kills))
        if baseline is None:
            self._ui_kps_baseline = current_sample
            return

        baseline_time, baseline_kills = baseline
        time_delta = float(game_time_seconds) - baseline_time
        if time_delta <= 0:
            return
        if time_delta < 0.9:
            return
        if time_delta > 1.2:
            self._ui_kps_baseline = current_sample
            return

        self._ui_kps_value = max(0, int(current_kills) - baseline_kills)
        self._ui_kps_baseline = current_sample

    def _record_chaos_modifier_deltas(
        self,
        permanent_modifiers: dict[int, tuple[Any, ...]],
    ) -> None:
        for stat_id, modifiers in (permanent_modifiers or {}).items():
            stat_id = int(stat_id)
            values = tuple(modifiers or ())
            old_values = self._chaos_modifier_baselines.get(stat_id, ())
            new_values = tuple(float(getattr(m, "value", 0.0)) for m in values)
            
            new_baseline = list(old_values)
            
            # Check existing indices for stacked modifiers
            for i in range(min(len(old_values), len(new_values))):
                delta = new_values[i] - old_values[i]
                if abs(delta) > 0.001:
                    matched_rolls = self._looks_like_chaos_value(stat_id, delta)
                    if matched_rolls > 0:
                        rolls_to_process = min(self._chaos_available_rolls, matched_rolls)
                        if rolls_to_process > 0:
                            self._add_chaos_total_by_value(
                                stat_id,
                                values[i],
                                delta * (rolls_to_process / matched_rolls),
                                rolls=rolls_to_process,
                            )
                            self._chaos_available_rolls -= rolls_to_process
                            new_baseline[i] = new_values[i]
                            self._chaos_unbudgeted_candidates.pop((stat_id, i), None)
                        elif self._should_commit_unbudgeted_candidate(stat_id, i, new_values[i]):
                            new_baseline[i] = new_values[i]
                    else:
                        new_baseline[i] = new_values[i]
                        self._chaos_unbudgeted_candidates.pop((stat_id, i), None)
            
            # Check new indices for spawned modifiers
            if len(new_values) > len(old_values):
                for i in range(len(old_values), len(new_values)):
                    val = new_values[i]
                    matched_rolls = self._looks_like_chaos_value(stat_id, val)
                    if matched_rolls > 0:
                        rolls_to_process = min(self._chaos_available_rolls, matched_rolls)
                        if rolls_to_process > 0:
                            self._add_chaos_total_by_value(
                                stat_id,
                                values[i],
                                val * (rolls_to_process / matched_rolls),
                                rolls=rolls_to_process,
                            )
                            self._chaos_available_rolls -= rolls_to_process
                            new_baseline.append(val)
                            self._chaos_unbudgeted_candidates.pop((stat_id, i), None)
                        elif self._should_commit_unbudgeted_candidate(stat_id, i, val):
                            new_baseline.append(val)
                        else:
                            break
                    else:
                        new_baseline.append(val)
                        self._chaos_unbudgeted_candidates.pop((stat_id, i), None)
            
            self._chaos_modifier_baselines[stat_id] = tuple(new_baseline)

    @staticmethod
    def _looks_like_chaos_value(stat_id: int, value: float) -> int:
        numeric = abs(value)
        if numeric <= 0:
            return 0

        fingerprints = CHAOS_FINGERPRINTS.get(stat_id)
        if not fingerprints:
            return 0

        # Check if it matches exactly N rolls of any fingerprint
        for fp in fingerprints:
            n = round(numeric / fp)
            if n > 0 and abs(numeric - fp * n) <= 0.002 * n:
                return n

        return 0

    def _should_commit_unbudgeted_candidate(self, stat_id: int, index: int, value: float) -> bool:
        key = (stat_id, index)
        previous = self._chaos_unbudgeted_candidates.get(key)
        if previous is not None and abs(previous[0] - value) <= 0.001:
            samples = previous[1] + 1
        else:
            samples = 1

        if samples >= CHAOS_UNBUDGETED_BASELINE_SAMPLES:
            self._chaos_unbudgeted_candidates.pop(key, None)
            return True

        self._chaos_unbudgeted_candidates[key] = (value, samples)
        return False

    def _add_chaos_total_by_value(
        self,
        stat_id: int,
        modifier: Any,
        delta: float,
        *,
        rolls: int = 1,
    ) -> None:
        rolls = max(1, int(rolls))
        existing = self._chaos_totals.get(stat_id)
        if existing is None:
            self._chaos_totals[stat_id] = ChaosTomeStatTotal(
                stat_id=stat_id,
                label=str(getattr(modifier, "label", f"Stat {stat_id}")),
                value=delta,
                value_format=getattr(modifier, "value_format", None),
                rolls=rolls,
            )
            return
        self._chaos_totals[stat_id] = ChaosTomeStatTotal(
            stat_id=existing.stat_id,
            label=existing.label,
            value=existing.value + delta,
            value_format=existing.value_format,
            rolls=existing.rolls + rolls,
        )

    def _should_reset_for_snapshot(self, snapshot: LiveRunSnapshot) -> bool:
        previous = self.snapshots[-1] if self.snapshots else None
        if previous is None:
            return True
        if not self._is_active_snapshot(previous):
            return True

        previous_time = previous.game_time_seconds
        current_time = snapshot.game_time_seconds
        if previous_time is not None and current_time is not None:
            if current_time + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS < previous_time:
                return True

        previous_seed = previous.map_seed
        current_seed = snapshot.map_seed
        seed_changed = (
            previous_seed is not None
            and current_seed is not None
            and int(previous_seed) != int(current_seed)
        )
        if seed_changed and current_time is not None:
            return current_time <= PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
        return False

    @staticmethod
    def _is_active_snapshot(snapshot: LiveRunSnapshot) -> bool:
        if snapshot.game_time_seconds is not None and snapshot.game_time_seconds > 0:
            return True
        if bool(int(snapshot.stage_ptr or 0) or int(snapshot.map_seed or 0)):
            return True
        if snapshot.mob_kills is not None and snapshot.mob_kills > 0:
            return True
        if snapshot.player_level is not None and snapshot.player_level > 1:
            return True
        if snapshot.items or snapshot.weapons or snapshot.tomes:
            return True
        return False

    def _process_item_deltas(self, snapshot: LiveRunSnapshot) -> None:
        if not snapshot.items_available:
            return
        current_counts = run_summary.item_counts(snapshot.items)
        if self._previous_item_counts is None:
            self._previous_item_counts = dict(current_counts)
            self._process_initial_item_counts(snapshot, current_counts)
            self._process_combo_item_rules(
                snapshot=snapshot,
                current_counts=current_counts,
                stage_index=self.current_stage_index,
            )
            return

        for item_name, current_count in current_counts.items():
            gained_count = max(0, current_count - self._previous_item_counts.get(item_name, 0))
            if gained_count <= 0:
                continue
            self._process_item_gain(
                item_name=item_name,
                gained_count=gained_count,
                snapshot=snapshot,
                stage_index=self.current_stage_index,
            )
        self._previous_item_counts = {
            item_name: max(current_counts.get(item_name, 0), self._previous_item_counts.get(item_name, 0))
            for item_name in set(current_counts) | set(self._previous_item_counts)
        }
        self._process_combo_item_rules(
            snapshot=snapshot,
            current_counts=current_counts,
            stage_index=self.current_stage_index,
        )

    def _process_initial_item_counts(
        self,
        snapshot: LiveRunSnapshot,
        counts: dict[str, int],
    ) -> None:
        if not counts:
            return
        is_clearly_early = (
            self.current_stage_index == 1
            and snapshot.game_time_seconds is not None
            and float(snapshot.game_time_seconds) <= 10.0
        )
        initial_stage_index = max(
            self.current_stage_index,
            1 if self._snapshot_looks_like_first_stage(snapshot) else 2,
        )
        for item_name, count in counts.items():
            if count <= 0:
                continue
            self._process_item_gain(
                item_name=item_name,
                gained_count=count,
                snapshot=snapshot,
                stage_index=initial_stage_index,
                initial_map_one_only=not is_clearly_early,
            )

    def _process_item_gain(
        self,
        *,
        item_name: str,
        gained_count: int,
        snapshot: LiveRunSnapshot,
        stage_index: int,
        initial_map_one_only: bool = False,
    ) -> None:
        for rule in self.tracked_item_rules:
            if len(rule.item_names) > 1:
                continue
            if initial_map_one_only and rule.mode != "map_1_only":
                continue
            if not self._rule_matches_item(rule, item_name):
                continue
            eligible_count = self._eligible_count_for_rule(
                rule,
                gained_count=gained_count,
                game_time_seconds=snapshot.game_time_seconds,
                stage_index=stage_index,
            )
            if eligible_count <= 0:
                continue
            self._tracked_counts[rule.id] = self._tracked_counts.get(rule.id, 0) + eligible_count
            event = TrackedItemEvent(
                rule_id=rule.id,
                item_name=item_name,
                gained_count=eligible_count,
                game_time_seconds=snapshot.game_time_seconds,
                stage_index=stage_index,
                map_seed=snapshot.map_seed,
                captured_at=snapshot.captured_at,
            )
            self._tracked_events.append(event)

    @staticmethod
    def _snapshot_looks_like_first_stage(snapshot: LiveRunSnapshot) -> bool:
        if snapshot.game_time_seconds is None or snapshot.stage_time_seconds is None:
            return True
        return (
            float(snapshot.stage_time_seconds)
            + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
            >= float(snapshot.game_time_seconds)
        )

    def _process_combo_item_rules(
        self,
        *,
        snapshot: LiveRunSnapshot,
        current_counts: dict[str, int],
        stage_index: int,
    ) -> None:
        folded_counts = {
            _fold_item_match_name(item_name): max(0, int(count))
            for item_name, count in current_counts.items()
        }
        for rule in self.tracked_item_rules:
            if len(rule.item_names) <= 1:
                continue
            if self._eligible_count_for_rule(
                rule,
                gained_count=1,
                game_time_seconds=snapshot.game_time_seconds,
                stage_index=stage_index,
            ) <= 0:
                continue
            combo_count = self._combo_count_for_rule(rule, folded_counts, folded=True)
            if combo_count <= 0:
                continue
            combo_count = 1
            already_counted_this_run = self._combo_run_counts.get(rule.id, 0)
            eligible_count = max(0, combo_count - already_counted_this_run)
            if eligible_count <= 0:
                continue
            total_count = self._tracked_counts.get(rule.id, 0)
            if rule.mode == "first_n" and rule.max_copies is not None:
                remaining = max(0, int(rule.max_copies) - total_count)
                eligible_count = min(eligible_count, remaining)
            if eligible_count <= 0:
                continue
            self._tracked_counts[rule.id] = total_count + eligible_count
            self._combo_run_counts[rule.id] = already_counted_this_run + eligible_count
            self._tracked_events.append(
                TrackedItemEvent(
                    rule_id=rule.id,
                    item_name=" + ".join(rule.item_names),
                    gained_count=eligible_count,
                    game_time_seconds=snapshot.game_time_seconds,
                    stage_index=stage_index,
                    map_seed=snapshot.map_seed,
                    captured_at=snapshot.captured_at,
                )
            )

    @staticmethod
    def _combo_count_for_rule(
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
                _fold_item_match_name(item_name): max(0, int(count))
                for item_name, count in counts.items()
            }
        return min(
            folded_counts.get(_fold_item_match_name(item_name), 0)
            for item_name in rule.item_names
        )

    def _eligible_count_for_rule(
        self,
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
            remaining = max(0, int(max_copies) - self._tracked_counts.get(rule.id, 0))
            eligible_count = min(eligible_count, remaining)
        return eligible_count

    @staticmethod
    def _rule_matches_item(rule: TrackedItemRule, item_name: str) -> bool:
        folded_item = _fold_item_match_name(item_name)
        return folded_item in {_fold_item_match_name(name) for name in rule.item_names}


def _fold_item_match_name(value: str) -> str:
    display_name = run_summary.normalize_item_name_for_display(str(value))
    canonical_name = run_summary.normalize_item_name_for_rarity(display_name)
    return "".join(char.lower() for char in canonical_name if char.isalnum())
