"""The live run tracker: the shell that owns the state its package computes.

``live_run_tracker.py``, top-level, until step 27c. Step 13 split the
internals out into this package -- ``chaos``, ``chests``, ``combat``,
``items``, ``powerups``, ``snapshots`` -- and left the shell behind because
the roadmap believed the move would touch ~117 sites. It touches **nine**
module-level import statements: that number counted ``self.live_run_tracker``
attribute accesses, which a file move does not touch at all.

Inside ``core/tracker/`` rather than beside it as ``core/live_run_tracker.py``:
it already imports six modules from this package and nothing in the package
imports it back, so ``__init__`` (empty) -> ``live_run`` -> siblings is a
chain with no cycle. Merging it into ``core/tracker/__init__.py`` would have
made ``from core.tracker import chaos`` on line 19 a self-import -- legal, and
exactly the kind of thing that works until it does not.

Two of the nine sites had no debt entry and no plan built from the registry
would have found them: ``gui_overlay.py`` and ``tracked_item_rules.py`` are
themselves top-level, so the import-direction checker assigns their edges no
direction and never reported them.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import time
from typing import Any, Callable, Iterable
from uuid import uuid4

import copy
import threading
from functools import wraps

from core import run_summary
from core.run_summary import PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
from core.stats.types import (
    DisabledItemsReadResult,
    DisabledItemsReadStatus,
)
from core.tracker import chaos, chests, combat, items, powerups
from core.tracker.chaos import _ChaosTomeState
from core.tracker.chests import _ChestState
from core.tracker.combat import _CombatState
from core.tracker.items import _TrackedItemState
from core.tracker.powerups import _PowerupState
from core.tracker.snapshots import (
    LiveRunSnapshot,
    TrackedItemRule,
    FeatureAvailability,
    RunLifecycle,
    FeatureStatus,
    RuntimeStateSnapshot,
    FastStageTimerContext,
    ChestStatsSnapshot,
    PowerupsSnapshot,
    PowerupMapContext,
)

FAST_STAGE_TRANSITION_CONFIRMATION_SAMPLES = 2


def with_lock(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with getattr(self, "_lock"):
            return method(self, *args, **kwargs)
    return wrapper



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
    fast_stage_boundaries: list[LiveRunSnapshot] = field(default_factory=list)
    pending_fast_stage_index: int | None = None
    pending_fast_stage_samples: int = 0
    pending_fast_stage_boundary: LiveRunSnapshot | None = None
    # The game updates its raw stage index ~1 s before it resets the stage
    # timer, so the sample that detects an index change can still carry the
    # previous map's timer.  While True, the pending boundary holds that stale
    # timer and must not be committed until a reset is observed.
    pending_fast_stage_awaiting_timer_reset: bool = False
    # The slow-tick half of the same desync.  ``update`` stores each read
    # verbatim, so a snapshot can land with the advanced raw index and the
    # previous map's timer, and one tick later that stored sample is the
    # ``previous_snapshot`` a stage-4 timer collapse is measured against.
    # Holds the stage_time captured at detection while the reset is awaited;
    # ``None`` once observed.
    slow_stage_timer_reset_pending_from: float | None = None


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

class LiveRunTracker:
    _STATE_FIELDS = {
        **{name: "_run_state" for name in (
            "run_id", "_lifecycle", "snapshots", "current_stage_index",
            "_last_update_at", "_last_failed_at", "_last_no_game_at",
            "_cached_stage_summary", "_disabled_items_cache", "_fast_stage_boundaries",
            "_pending_fast_stage_index", "_pending_fast_stage_samples",
            "_pending_fast_stage_boundary", "_pending_fast_stage_awaiting_timer_reset",
            "_slow_stage_timer_reset_pending_from",
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
            "tracked_item_rules", "_previous_item_counts", "_pending_item_increases", "_tracked_events",
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
            next_stage_index = min(
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
            next_stage_index = self._suppress_desync_stage_four_unlocked(next_stage_index)
            self.current_stage_index = next_stage_index
            self._update_slow_stage_desync_unlocked(previous_snapshot, snapshot)

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
            combat.reset(self._combat_state)
            self._fast_stage_timer_context = FastStageTimerContext()

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
        items.set_rules(
            self._tracked_item_state,
            rules,
            latest_snapshot=self._latest_snapshot_unlocked(),
        )

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
        chaos.update(
            self._chaos_state,
            chaos_level=chaos_level,
            permanent_modifiers=permanent_modifiers,
        )

    @with_lock
    def chaos_tome_summary_parts(self) -> list[str]:
        return chaos.summary_parts(self._chaos_state)

    @with_lock
    def chaos_tome_snapshot(self):
        return chaos.snapshot(self._chaos_state)

    @with_lock
    def chaos_tome_level(self) -> int | None:
        return self._chaos_tome_level

    @with_lock
    def chaos_tome_ambiguous_rolls(self) -> int:
        return self._chaos_ambiguous_rolls

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
            snapshots = self._stage_summary_timeline_unlocked()
            fast_snapshot = self._fast_stage_summary_snapshot_unlocked()
            if fast_snapshot is not None:
                snapshots += (fast_snapshot,)
            self._cached_stage_summary = run_summary.build_stage_summary(snapshots)
        return copy.deepcopy(self._cached_stage_summary)

    @staticmethod
    def _stage_summary_snapshot_sort_key(snapshot: LiveRunSnapshot) -> tuple[bool, float, float]:
        game_time = snapshot.game_time_seconds
        return (
            game_time is None,
            float("inf") if game_time is None else float(game_time),
            float(snapshot.captured_at),
        )

    def _stage_summary_timeline_unlocked(self) -> tuple[LiveRunSnapshot, ...]:
        timeline = [*self.snapshots, *self._fast_stage_boundaries]
        timeline.sort(key=self._stage_summary_snapshot_sort_key)
        return tuple(timeline)

    def _latest_stage_summary_snapshot_unlocked(self) -> LiveRunSnapshot | None:
        timeline = self._stage_summary_timeline_unlocked()
        return timeline[-1] if timeline else None

    def _suppress_desync_stage_four_unlocked(self, next_stage_index: int) -> int:
        """Drop a stage-4 promotion measured against a stale stage timer.

        Stage 4 is virtual -- same ``stage_ptr``, same raw ``stage_index``, only
        the timer collapses -- so the detector is a pure timer comparison.  While
        the slow tick is holding a sample whose timer still belongs to the
        previous map, that comparison reads the *real* reset as the collapse and
        promotes within a second of "Moving to Stage 3".  Genuine stage 4 is
        unaffected: it happens well after the reset has been observed and the
        hold has cleared.
        """
        if (
            next_stage_index == 4
            and self.current_stage_index == 3
            and self._slow_stage_timer_reset_pending_from is not None
        ):
            return 3
        return next_stage_index

    def _update_slow_stage_desync_unlocked(self, previous_snapshot, snapshot) -> None:
        current_stage_time = getattr(snapshot, "stage_time_seconds", None)
        pending_from = self._slow_stage_timer_reset_pending_from
        if pending_from is not None:
            # Stage timers only count up, so a value below the one captured at
            # detection is the reset itself, relative to itself -- no threshold.
            if current_stage_time is not None and float(current_stage_time) < pending_from:
                self._slow_stage_timer_reset_pending_from = None
            return
        previous_stage_time = getattr(previous_snapshot, "stage_time_seconds", None)
        if (
            run_summary.is_explicit_raw_stage_transition(previous_snapshot, snapshot)
            and current_stage_time is not None
            and previous_stage_time is not None
            and float(current_stage_time) >= float(previous_stage_time)
            # A sample already at a fresh-stage value has reset, whatever the
            # previous one read; it also sits below the threshold the collapse
            # detector requires of its ``previous_stage_time``, so it cannot be
            # the false positive being guarded against.
            and not run_summary.is_stage_transition_boundary_snapshot(snapshot)
        ):
            # Raw index advanced but the timer kept counting the old map: this
            # stored sample carries a stale stage_time.
            self._slow_stage_timer_reset_pending_from = float(current_stage_time)

    def _fast_stage_summary_snapshot_unlocked(
        self,
        *,
        include_unconfirmed_stage_context: bool = False,
    ) -> LiveRunSnapshot | None:
        """Project fresh runtime values without exposing an unconfirmed transition."""
        latest_snapshot = self._latest_stage_summary_snapshot_unlocked()
        if latest_snapshot is None:
            return None
        changes: dict[str, Any] = {"items_available": False}

        if self._recent_kills_history:
            latest_game_time = latest_snapshot.game_time_seconds
            fast_game_time, fast_kills = self._recent_kills_history[-1]
            if latest_game_time is not None and fast_game_time >= float(latest_game_time):
                if (
                    fast_game_time != float(latest_game_time)
                    or latest_snapshot.mob_kills is None
                    or fast_kills != int(latest_snapshot.mob_kills)
                ):
                    changes.update(
                        captured_at=float(self.clock()),
                        game_time_seconds=float(fast_game_time),
                        mob_kills=int(fast_kills),
                    )

        stage_context = self._fresh_fast_stage_timer_context_unlocked()
        if include_unconfirmed_stage_context and stage_context is not None:
            changes.update(
                stage_timer_seconds=stage_context.stage_timer_seconds,
                stage_time_seconds=stage_context.stage_timer_seconds,
                stage_duration_seconds=stage_context.stage_duration_seconds,
                stage_index=stage_context.stage_index,
            )

        if len(changes) == 1:
            return None
        # Interactable totals belong to the slow tick's game_data read; a fast
        # projection has no way to refresh them and must not carry them forward.
        # Stale ``chests_total``/``pots_total`` was the trigger for a bogus
        # Stage 3 -> Stage 4 promotion right after a raw 1 -> 2 transition
        # (fast_snapshot inherited the previous map's low totals and
        # ``looks_like_stage_four_from_map_activity`` flipped on them).
        changes.setdefault("chests_total", None)
        changes.setdefault("pots_total", None)
        return replace(latest_snapshot, **changes)

    def _tracked_item_rows_unlocked(self) -> list[dict[str, Any]]:
        return self._tracked_item_rows_for_rules_unlocked(self.tracked_item_rules)

    def _tracked_item_rows_for_rules_unlocked(self, rules: Iterable[TrackedItemRule]) -> list[dict[str, Any]]:
        return items.rows_for_rules(self._tracked_item_state, rules)

    @with_lock
    def track_kills(self, game_time_seconds: float | None, current_kills: int | None) -> None:
        if game_time_seconds is None or current_kills is None:
            return
        self._mark_feature_success_unlocked("combat", self.clock())
        combat.track_kills(self._combat_state, game_time_seconds, current_kills)
        # Every branch past the None guard invalidated the cache before the
        # split (including the paused-game early return), so clearing it here
        # unconditionally is the same behaviour without the feature module
        # needing to reach into run state.
        self._cached_stage_summary = None

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
        return combat.current_run_avg_kps(self._combat_state)

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
            self._pending_fast_stage_index = None
            self._pending_fast_stage_samples = 0
            self._pending_fast_stage_boundary = None
            self._pending_fast_stage_awaiting_timer_reset = False
            self._cached_stage_summary = None
            return
        previous_fast_timer = self._fast_stage_timer_context.stage_timer_seconds
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
        fast_snapshot = self._fast_stage_summary_snapshot_unlocked(
            include_unconfirmed_stage_context=True,
        )
        latest_snapshot = self._latest_stage_summary_snapshot_unlocked()
        if fast_snapshot is not None and latest_snapshot is not None:
            next_stage_index = min(
                run_summary.resolve_next_stage_index(
                    self.current_stage_index,
                    latest_snapshot,
                    fast_snapshot,
                ),
                4,
            )
            # The fast tick measures against the same stored timeline, so a
            # slow-tick sample holding a stale timer feeds a bogus stage-4
            # collapse here too -- and this path is exempt from the
            # ``awaiting_timer_reset`` hold, since a 3 -> 4 promotion carries no
            # raw index advance to detect.
            next_stage_index = self._suppress_desync_stage_four_unlocked(next_stage_index)
            if next_stage_index > self.current_stage_index:
                current_timer = float(stage_timer_seconds)
                if self._pending_fast_stage_index == next_stage_index:
                    self._pending_fast_stage_samples += 1
                    if self._pending_fast_stage_awaiting_timer_reset:
                        pending_boundary = self._pending_fast_stage_boundary
                        detection_timer = (
                            None
                            if pending_boundary is None
                            else pending_boundary.stage_time_seconds
                        )
                        # Stage timers only count up, so a value below the one
                        # captured at detection means the reset happened in
                        # between.  Adopt this post-reset sample as the boundary.
                        if detection_timer is None or current_timer < float(detection_timer):
                            self._pending_fast_stage_boundary = fast_snapshot
                            self._pending_fast_stage_awaiting_timer_reset = False
                else:
                    self._pending_fast_stage_index = next_stage_index
                    self._pending_fast_stage_samples = 1
                    self._pending_fast_stage_boundary = fast_snapshot
                    # The game advances the raw stage index ~1 s before it
                    # resets the stage timer.  If the detecting sample's timer
                    # still continues the previous stage's timer, the boundary
                    # holds the wrong stage_time and one tick later the real
                    # reset would read as a bogus stage-4 collapse.  Hold the
                    # commit until the reset is observed.  Heuristic stage-4
                    # promotions (raw index unchanged) are exempt: there the
                    # timer movement itself is the detection signal.
                    reference_timer = previous_fast_timer
                    if reference_timer is None:
                        reference_timer = latest_snapshot.stage_time_seconds
                    self._pending_fast_stage_awaiting_timer_reset = (
                        run_summary.is_explicit_raw_stage_transition(
                            latest_snapshot, fast_snapshot
                        )
                        and reference_timer is not None
                        and current_timer >= float(reference_timer)
                    )
                if (
                    self._pending_fast_stage_samples >= FAST_STAGE_TRANSITION_CONFIRMATION_SAMPLES
                    and not self._pending_fast_stage_awaiting_timer_reset
                ):
                    boundary = self._pending_fast_stage_boundary or fast_snapshot
                    self._fast_stage_boundaries.append(boundary)
                    self.current_stage_index = next_stage_index
                    self._pending_fast_stage_index = None
                    self._pending_fast_stage_samples = 0
                    self._pending_fast_stage_boundary = None
                    self._pending_fast_stage_awaiting_timer_reset = False
            else:
                self._pending_fast_stage_index = None
                self._pending_fast_stage_samples = 0
                self._pending_fast_stage_boundary = None
                self._pending_fast_stage_awaiting_timer_reset = False
        self._cached_stage_summary = None

    @with_lock
    def fast_stage_timer_context(self) -> FastStageTimerContext | None:
        return self._fresh_fast_stage_timer_context_unlocked()

    @with_lock
    def graveyard_main_map_events_active(self) -> bool:
        return self._graveyard_main_map_events_active_unlocked()

    def _graveyard_main_map_events_active_unlocked(self) -> bool:
        return powerups.graveyard_main_map_events_active(
            self._powerup_state, self.clock()
        )

    def _latest_snapshot_unlocked(self) -> LiveRunSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def _fresh_fast_stage_timer_context_unlocked(self) -> FastStageTimerContext | None:
        return powerups.fresh_fast_stage_timer_context(
            self._powerup_state, self.clock()
        )

    def _fresh_powerups_snapshot_unlocked(self) -> PowerupsSnapshot:
        return powerups.fresh_snapshot(self._powerup_state, self.clock())

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
        powerups.set_map_context(self._powerup_state, context, self.clock)

    def _fresh_powerup_map_context_unlocked(self) -> PowerupMapContext | None:
        return powerups.fresh_map_context(self._powerup_state, self.clock())

    @with_lock
    def update_powerups(
        self,
        snapshot: Any,
        *,
        map_context: PowerupMapContext | None = None,
    ) -> bool:
        if map_context is not None:
            powerups.set_map_context(self._powerup_state, map_context, self.clock)

        failure_reason = powerups.check_health(snapshot)
        if failure_reason is not None:
            self._mark_feature_failure_unlocked("powerups", self.clock(), failure_reason)
            return False

        self._mark_feature_success_unlocked("powerups", self.clock())
        powerups.apply_snapshot(self._powerup_state, snapshot, clock=self.clock)
        return True

    @with_lock
    def clear_powerups(self) -> None:
        powerups.clear(self._powerup_state)

    @with_lock
    def powerups_snapshot(self) -> PowerupsSnapshot:
        return self._fresh_powerups_snapshot_unlocked()

    @with_lock
    def format_powerups_summary(self, *, include_left_word: bool = True) -> str:
        return powerups.format_summary(
            self._fresh_powerups_snapshot_unlocked(),
            include_left_word=include_left_word,
        )

    @with_lock
    def powerups_summary_text(self, *, include_left_word: bool = True) -> str:
        return powerups.summary_text(
            self._fresh_powerups_snapshot_unlocked(),
            include_left_word=include_left_word,
        )

    @with_lock
    def update_chests_and_keys(self, chests_opened: int, chests_total: int, keys_count: int) -> None:
        self._mark_feature_success_unlocked("progression", self.clock())
        chests.update_chests_and_keys(
            self._chest_state,
            chests_opened,
            chests_total,
            keys_count,
            latest_snapshot=self._latest_snapshot_unlocked(),
        )

    @with_lock
    def update_chest_counters(self, chests_bought: int, chests_purchased: int) -> bool:
        self._mark_feature_success_unlocked("progression", self.clock())
        return chests.update_chest_counters(
            self._chest_state, chests_bought, chests_purchased
        )

    # Called class-qualified from projections/formatting.py, so it has to stay
    # resolvable on LiveRunTracker even though the implementation moved.
    key_proc_chance = staticmethod(chests.key_proc_chance)

    @with_lock
    def track_expected_key_procs(self, chests_bought: int, keys_count: int) -> None:
        chests.track_expected_key_procs(self._chest_state, chests_bought, keys_count)

    @with_lock
    def get_chest_stats(self) -> ChestStatsSnapshot:
        return self._get_chest_stats_unlocked()

    def _get_chest_stats_unlocked(self) -> ChestStatsSnapshot:
        return chests.get_chest_stats(self._chest_state)

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
        self._fast_stage_boundaries.clear()
        self._fast_stage_timer_context = FastStageTimerContext()
        self._pending_fast_stage_index = None
        self._pending_fast_stage_samples = 0
        self._pending_fast_stage_boundary = None
        self._pending_fast_stage_awaiting_timer_reset = False
        self._slow_stage_timer_reset_pending_from = None
        combat.reset(self._combat_state)
        self.current_stage_index = 1
        chests.reset(self._chest_state)
        self._reset_current_run_item_baseline()
        self._reset_chaos_tracking()
        self._powerups_snapshot = PowerupsSnapshot()
        self._powerup_map_context = PowerupMapContext()
        self._cached_stage_summary = None
        self._graveyard_final_swarm_timer_is_zero = False

    def _reset_tracking_only(self) -> None:
        self._reset_current_run_item_baseline()
        self._tracked_events = []
        self._tracked_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._combo_run_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._graveyard_final_swarm_timer_is_zero = False

    def _reset_current_run_item_baseline(self, *, reset_combo_counts: bool = True) -> None:
        items.reset_baseline(
            self._tracked_item_state, reset_combo_counts=reset_combo_counts
        )

    def _reset_chaos_tracking(self) -> None:
        chaos.reset(self._chaos_state)

    def _reset_ui_kps_unlocked(self) -> None:
        combat.reset_ui_kps(self._combat_state)

    def _average_kps_for_window_unlocked(self, window_seconds: float) -> int | None:
        return combat.average_kps_for_window(self._combat_state, window_seconds)

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
        items.process_item_deltas(
            self._tracked_item_state,
            snapshot,
            current_stage_index=self.current_stage_index,
        )
