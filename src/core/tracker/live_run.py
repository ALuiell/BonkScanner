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
from core.tracker import chaos, chests, combat, items, loot, passives, powerups, shrines
from core.tracker.chaos import _ChaosTomeState
from core.tracker.chests import _ChestState
from core.tracker.combat import _CombatState
from core.tracker.items import _TrackedItemState
from core.tracker.loot import _LootState
from core.tracker.powerups import _PowerupState
from core.tracker.shrines import _ShrineState
from core.tracker.passives import _CharacterPassiveState
from core.tracker.snapshots import (
    ItemLossEvent,
    LiveRunSnapshot,
    LootStatsSnapshot,
    TrackedItemRule,
    FeatureAvailability,
    RunLifecycle,
    FeatureStatus,
    RuntimeStateSnapshot,
    FastStageTimerContext,
    ChestStatsSnapshot,
    PowerupsSnapshot,
    PowerupMapContext,
    FastRunTimer,
    FastItemCooldowns,
    FastItems,
    FastLuck,
    FastSize,
)

FAST_STAGE_TRANSITION_CONFIRMATION_SAMPLES = 2

# The run clock's freshness bound. Set equal to
# `powerups.FAST_STAGE_TIMER_TTL_SECONDS` (2.0) rather than to
# `POWERUPS_SNAPSHOT_TTL_SECONDS` (1.5) because the stage timer is this fact's
# true sibling: both are clocks read by a fast refresh task on the same driver
# cadence, and both must survive a missed tick without blanking the card. The
# driver is configurable down to 100 ms and up to 500 ms (config.py:784-793),
# so 2.0 s is four missed ticks of margin at the slowest configured interval --
# long enough that normal jitter never blanks the clock, short enough that a
# genuinely dead read stops the display rather than showing a frozen time as
# if it were live.
FAST_RUN_TIMER_TTL_SECONDS = 2.0

# The fast inventory's freshness bound. Wider than the run clock's because the
# passive-items task runs at 1 s rather than on the 500 ms driver cadence, and
# because the cost of a stale value here is different: a stale clock shows a
# wrong time, a stale inventory would credit items to a stage boundary they
# were not observed at. Three missed ticks of margin, after which the boundary
# falls back to carrying no inventory at all -- which is what it did before the
# fast lane existed, so expiry degrades to the previous behaviour rather than
# to a wrong one.
FAST_ITEMS_TTL_SECONDS = 3.0

# Luck's freshness bound. Equal to the inventory's, and for the reason the run
# clock's is equal to the stage timer's: these two are read by the *same task*
# in the *same pass*, so a bound that expired one before the other would let a
# gain be projected against a Luck the pass that observed it did not carry.
FAST_LUCK_TTL_SECONDS = FAST_ITEMS_TTL_SECONDS
FAST_SIZE_TTL_SECONDS = 3.0

# Item cooldowns' freshness bound. Same pass as the inventory and Luck, so the
# same bound, for the same reason.
#
# What this bound does *not* do is worth stating, because the obvious reading of
# "TTL" is wrong here: it retires a reading whose *pass failed*, and nothing
# else. On the death screen every read keeps succeeding against a frozen clock,
# so the reading stays perpetually fresh and perpetually wrong -- 256
# consecutive successful reads over 26 s of wall-clock, measured. Only
# ``RunLifecycle`` distinguishes that from a pause, which is byte-identical.
FAST_ITEM_COOLDOWNS_TTL_SECONDS = FAST_ITEMS_TTL_SECONDS

# Reconstructing Dice's first 255 level-specific rolls is deliberately moved
# off the refresh/UI thread once the cold history is large enough to be
# noticeable. Incremental updates below this boundary stay synchronous and
# retain their existing sub-frame latency.
PERMANENT_SOURCE_BACKGROUND_RECOVERY_MIN_LEVEL = 64


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
    # Published by every successful RUN_TIMER read, independently of whether
    # the MOB_KILLS read beside it succeeded (step_28_plan.md section 12.2).
    fast_run_timer: FastRunTimer = field(default_factory=FastRunTimer)
    # Published by every successful fast-lane PASSIVE_ITEMS read. Consumed by
    # the stage-summary projection so a boundary can close on the inventory as
    # it stood at the transition rather than on the last 10 s snapshot's.
    fast_items: FastItems = field(default_factory=FastItems)
    # Published by the same fast-lane pass that publishes ``fast_items``. Kept
    # beside it rather than inside it because a failed Luck read must not
    # withhold the inventory, nor the reverse.
    fast_luck: FastLuck = field(default_factory=FastLuck)
    fast_size: FastSize = field(default_factory=FastSize)
    # Published by that same pass. Holds the readings and the game clock they
    # were measured against as one object, because the countdown is their
    # difference and pairing them across passes is the bug this prevents.
    fast_item_cooldowns: FastItemCooldowns = field(default_factory=FastItemCooldowns)


@dataclass
class _AvailabilityState:
    feature_status: dict[str, FeatureStatus] = field(default_factory=dict)


@dataclass(frozen=True)
class PermanentSourceRecoveryToken:
    generation: int
    run_id: str | None
    passive_identity: tuple[int, int, str, int]


@dataclass(frozen=True)
class PermanentSourceRecoveryResult:
    """Detached Dice/Chaos states computed without touching a live tracker."""

    passive_identity: tuple[int, int, str, int]
    character_passive_state: _CharacterPassiveState
    chaos_tome_state: _ChaosTomeState


def _update_permanent_source_states(
    character_passive_state: _CharacterPassiveState,
    chaos_tome_state: _ChaosTomeState,
    reading,
    *,
    chaos_level: int | None,
    permanent_modifiers: dict[int, tuple[Any, ...]],
    reserved_modifier_ptrs: frozenset[int],
) -> None:
    """Attribute one immutable sample into detached or tracker-owned states."""
    previous_chaos_level = chaos_tome_state.chaos_tome_level
    chaos_budget_rising = bool(
        chaos_level is not None
        and (
            previous_chaos_level is None
            and int(chaos_level) > 0
            or previous_chaos_level is not None
            and int(chaos_level) > int(previous_chaos_level)
        )
    )
    passives.update(
        character_passive_state,
        reading,
        reserved_modifier_ptrs=reserved_modifier_ptrs,
        avoid_chaos_collisions=chaos_budget_rising,
    )
    claimed = (
        passives.claimed_modifier_ptrs(character_passive_state)
        | passives.contested_modifier_ptrs(character_passive_state)
        | reserved_modifier_ptrs
    )
    filtered = {
        int(stat_id): tuple(
            modifier
            for modifier in modifiers
            if int(getattr(modifier, "object_ptr", 0) or 0) not in claimed
        )
        for stat_id, modifiers in (permanent_modifiers or {}).items()
    }
    chaos.update(
        chaos_tome_state,
        chaos_level=chaos_level,
        permanent_modifiers=filtered,
    )


def build_permanent_source_recovery(
    reading,
    *,
    chaos_level: int | None,
    permanent_modifiers: dict[int, tuple[Any, ...]],
    reserved_modifier_ptrs: frozenset[int] = frozenset(),
    base: PermanentSourceRecoveryResult | None = None,
) -> PermanentSourceRecoveryResult:
    """Build a cold or catch-up Dice/Chaos result entirely off-tracker."""
    if base is None:
        character_passive_state = _CharacterPassiveState()
        chaos_tome_state = _ChaosTomeState()
    else:
        character_passive_state = copy.deepcopy(base.character_passive_state)
        chaos_tome_state = copy.deepcopy(base.chaos_tome_state)
    _update_permanent_source_states(
        character_passive_state,
        chaos_tome_state,
        reading,
        chaos_level=chaos_level,
        permanent_modifiers=permanent_modifiers,
        reserved_modifier_ptrs=reserved_modifier_ptrs,
    )
    return PermanentSourceRecoveryResult(
        passive_identity=passives.reading_identity_key(reading),
        character_passive_state=character_passive_state,
        chaos_tome_state=chaos_tome_state,
    )


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
            "_slow_stage_timer_reset_pending_from", "_fast_run_timer",
            "_fast_items", "_fast_luck", "_fast_size", "_fast_item_cooldowns",
        )},
        **{name: "_combat_state" for name in (
            "_recent_kills_history", "_ui_kps_second", "_ui_kps_value",
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
            "tracked_item_rules", "_previous_item_counts", "_pending_item_increases",
            "_pending_item_decreases", "_tracked_events",
            "_tracked_counts", "_combo_run_counts", "_last_item_losses",
            "_last_item_gains",
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
        reconnect_grace_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_snapshots = max(1, int(max_snapshots))
        self.stale_after_seconds = max(0.1, float(stale_after_seconds))
        self.reconnect_grace_seconds = max(0.0, float(reconnect_grace_seconds))
        self.clock = clock
        self._run_state = _RunState(snapshots=deque(maxlen=self.max_snapshots))
        self._combat_state = _CombatState()
        self._chest_state = _ChestState()
        self._chaos_state = _ChaosTomeState()
        self._shrine_state = _ShrineState()
        self._character_passive_state = _CharacterPassiveState()
        self._powerup_state = _PowerupState()
        self._tracked_item_state = _TrackedItemState()
        self._loot_state = _LootState()
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
                "shrines",
                "character_passive",
                "expected_chests",
                "stage_timer",
            )
        })
        self.tracked_item_rules = tuple(tracked_item_rules)
        self._tracked_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._combo_run_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._permanent_source_generation = 0
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
            self._fast_run_timer = FastRunTimer()
            self._fast_items = FastItems()
            self._fast_luck = FastLuck()
            self._fast_size = FastSize()
            self._fast_item_cooldowns = FastItemCooldowns()
            self._cached_stage_summary = None

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
    def update_charge_shrines(
        self,
        reading,
        *,
        wrench_stacks: int | None,
    ) -> None:
        now = self.clock()
        self._mark_feature_success_unlocked("shrines", now)
        shrines.update(
            self._shrine_state,
            reading,
            wrench_stacks=wrench_stacks,
        )

    @with_lock
    def charge_shrine_snapshot(self):
        return shrines.snapshot(self._shrine_state)

    @with_lock
    def update_character_passive(self, reading) -> None:
        self._mark_feature_success_unlocked("character_passive", self.clock())
        passives.update(
            self._character_passive_state,
            reading,
            reserved_modifier_ptrs=frozenset(self._shrine_state.seen_log_ptrs),
        )

    @with_lock
    def update_permanent_sources(
        self,
        reading,
        *,
        chaos_level: int | None,
        permanent_modifiers: dict[int, tuple[Any, ...]],
    ) -> None:
        """Attribute Dice first, then hide its stable pointers from Chaos.

        Exact shrine pointers are always reserved. When both source budgets
        rise together, values valid for one Chaos roll remain unresolved on
        the Dice side instead of being awarded by task ordering.
        """
        self._mark_feature_success_unlocked("character_passive", self.clock())
        self._mark_feature_success_unlocked("chaos_tome", self.clock())
        _update_permanent_source_states(
            self._character_passive_state,
            self._chaos_state,
            reading,
            chaos_level=chaos_level,
            permanent_modifiers=permanent_modifiers,
            reserved_modifier_ptrs=frozenset(self._shrine_state.seen_log_ptrs),
        )

    @with_lock
    def needs_permanent_source_recovery(self, reading) -> bool:
        if not passives.is_gamba_reading(reading):
            return False
        current_level = max(0, int(reading.gamba_current_level or 0))
        if current_level < PERMANENT_SOURCE_BACKGROUND_RECOVERY_MIN_LEVEL:
            return False
        return (
            self._character_passive_state.identity_key
            != passives.reading_identity_key(reading)
            or not self._character_passive_state.gamba.initialized
        )

    @with_lock
    def begin_permanent_source_recovery(
        self,
        reading,
    ) -> tuple[PermanentSourceRecoveryToken, frozenset[int]]:
        """Publish `updating` and capture the validation/reservation boundary."""
        identity = passives.reading_identity_key(reading)
        passives.mark_recovering(self._character_passive_state, reading)
        self._mark_feature_success_unlocked("character_passive", self.clock())
        return (
            PermanentSourceRecoveryToken(
                generation=self._permanent_source_generation,
                run_id=self.run_id,
                passive_identity=identity,
            ),
            frozenset(self._shrine_state.seen_log_ptrs),
        )

    @with_lock
    def apply_permanent_source_recovery(
        self,
        token: PermanentSourceRecoveryToken,
        result: PermanentSourceRecoveryResult,
        reading,
    ) -> bool:
        """Atomically publish a detached result if its run still owns it."""
        identity = passives.reading_identity_key(reading)
        if (
            token.generation != self._permanent_source_generation
            or token.run_id != self.run_id
            or token.passive_identity != identity
            or result.passive_identity != identity
        ):
            return False
        self._character_passive_state = result.character_passive_state
        self._chaos_state = result.chaos_tome_state
        self._mark_feature_success_unlocked("character_passive", self.clock())
        self._mark_feature_success_unlocked("chaos_tome", self.clock())
        return True

    @with_lock
    def character_passive_snapshot(self):
        return passives.snapshot(self._character_passive_state)

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
            loot_stats=self._get_loot_stats_unlocked(),
            kps={
                "current": self._ui_kps_value,
                "minute_avg": self._average_kps_for_window_unlocked(60.0),
                "five_minute_avg": self._average_kps_for_window_unlocked(300.0),
                "run_avg": self._current_run_avg_kps_unlocked(),
            },
            feature_status=self._feature_status_snapshot_unlocked(now),
            chaos_tome=self.chaos_tome_snapshot(),
            shrines=shrines.snapshot(self._shrine_state),
            character_passive=passives.snapshot(self._character_passive_state),
            powerups=self._fresh_powerups_snapshot_unlocked(),
            powerups_recent=self._recent_powerups_snapshot_unlocked(),
            powerup_map_context=copy.deepcopy(map_context),
            fast_stage_timer=copy.deepcopy(self._fresh_fast_stage_timer_context_unlocked()),
            graveyard_main_map_events_active=self._graveyard_main_map_events_active_unlocked(),
            luck=self._fresh_fast_luck_unlocked(),
            size=self._fresh_fast_size_unlocked(),
            fast_items=self._fresh_fast_items_unlocked(),
            item_cooldowns=self._fresh_item_cooldowns_unlocked(),
            run_timer_seconds=self._fresh_fast_run_timer_unlocked(),
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
        # ``items_available: False`` is the default and not a change: a fast
        # projection had no way to refresh the inventory, so it had to withhold
        # it rather than carry a 10 s stale list into a stage bucket. The fast
        # lane now supplies one, and a boundary snapshot that carries the
        # inventory as it stood at the transition is what closes a stage on its
        # own items instead of the next stage's first read.
        has_fresh_value = False
        fast_items = self._fresh_fast_items_unlocked()
        if fast_items is not None:
            changes.update(items=fast_items, items_available=True)
            has_fresh_value = True

        # The run clock comes from the dedicated fast run timer, the kill count
        # from combat state. Before step 28c both came from
        # `_recent_kills_history[-1]`, which meant a failed kills read froze the
        # Stage Summary clock even though the timer beside it had been read
        # successfully -- the defect this slice closes (plan section 12.2).
        fast_game_time = self._fresh_fast_run_timer_unlocked()
        fast_kills = self._recent_kills_history[-1][1] if self._recent_kills_history else None
        if fast_game_time is not None:
            latest_game_time = latest_snapshot.game_time_seconds
            if latest_game_time is not None and fast_game_time >= float(latest_game_time):
                kills_are_newer = fast_kills is not None and (
                    latest_snapshot.mob_kills is None
                    or int(fast_kills) != int(latest_snapshot.mob_kills)
                )
                if fast_game_time != float(latest_game_time) or kills_are_newer:
                    changes.update(
                        captured_at=float(self.clock()),
                        game_time_seconds=float(fast_game_time),
                    )
                    if fast_kills is not None:
                        changes.update(mob_kills=int(fast_kills))
                    has_fresh_value = True

        stage_context = self._fresh_fast_stage_timer_context_unlocked()
        if include_unconfirmed_stage_context and stage_context is not None:
            changes.update(
                stage_timer_seconds=stage_context.stage_timer_seconds,
                stage_time_seconds=stage_context.stage_timer_seconds,
                stage_duration_seconds=stage_context.stage_duration_seconds,
                stage_index=stage_context.stage_index,
            )
            has_fresh_value = True

        if not has_fresh_value:
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
    def update_fast_run_timer(self, run_timer_seconds: float | None) -> None:
        """Publish the run clock from one successful ``RUN_TIMER`` source read.

        Called on every pass where the timer read succeeded, regardless of what
        the kills read beside it did (step_28_plan.md section 12.2). ``None``
        clears the clock, matching ``update_fast_stage_timer``'s handling of an
        unreadable stage timer: a dead read stops the fast display rather than
        leaving a frozen time looking live.

        No ``(timer, unknown_kills)`` sample is invented for
        ``_recent_kills_history`` -- that deque holds observed kill counts and
        nothing else.
        """
        if run_timer_seconds is None:
            self._fast_run_timer = FastRunTimer()
            self._cached_stage_summary = None
            return
        self._fast_run_timer = FastRunTimer(
            captured_at=self.clock(),
            run_timer_seconds=float(run_timer_seconds),
        )
        self._cached_stage_summary = None

    @with_lock
    def update_items(self, items: tuple[str, ...] | None) -> bool:
        """Fast-lane item pass: item deltas only, from one ``PASSIVE_ITEMS`` read.

        Deliberately *not* ``update()``. That method appends to the snapshot
        deque, advances ``current_stage_index``, resets the stage-summary cache
        and marks five features live -- all of which belong to the full 10 s
        snapshot and none of which this read has the inputs to decide. This
        joins the existing family of narrow fast-lane entry points
        (``update_fast_run_timer``, ``track_kills``, ``update_powerups``,
        ``track_expected_key_procs``, ``update_chaos_tome``).

        Returns whether the read was applied, so the task can report a skipped
        pass without inventing a failure.
        """
        # The run clock first, before any of the guards below can return.
        #
        # `observe_run_position` carries two jobs, and only one of them needs an
        # item: a clock that has gone backwards is a new match, and this lane
        # sees that once a second. Reaching it only through `_process_item_deltas`
        # meant the loot state learned about a new run either when the player
        # picked something up or when the 10 s snapshot came round -- whichever
        # was sooner. Until then the Luck widget's expected frame kept showing
        # the *previous* run's verdict, so a player who ended a run on
        # "missed run start" began the next one still reading it. Passing no
        # inventory (`items_available=False`) is what keeps this to the clock
        # arm: an empty read here is not evidence of an empty inventory, and
        # deciding measurability off one is the single direction of error the
        # gate exists to prevent.
        #
        # `_fresh_fast_run_timer_unlocked` is `None` when the combat pass is not
        # running -- it is what publishes the clock, and the Luck widget alone
        # does not demand it -- and a `None` clock decides nothing. That case
        # falls back to the 10 s snapshot exactly as it did before, which is the
        # right shape for it: this is strictly an improvement where the clock is
        # there, never a new dependency on it.
        loot.observe_run_position(
            self._loot_state,
            stage_index=self.current_stage_index,
            game_time_seconds=self._fresh_fast_run_timer_unlocked(),
            item_count=None,
            items_available=False,
        )
        # Transient-empty protection, the same rule `LiveSnapshotStore.merge_items`
        # applies on the slow path: the game exposes an empty inventory
        # dictionary for a single read while it rebuilds it in place. Credited
        # here it would drop `current_count` below the confirmed count and
        # silently discard a pending gain. An empty read is never news -- a
        # genuinely empty inventory has no deltas to detect -- so dropping it
        # costs nothing and the slow path still seeds the baseline.
        latest = self._latest_snapshot_unlocked()
        if latest is None or not self._is_active_snapshot(latest):
            # No run baseline yet. The slow path owns run start, including the
            # initial-inventory candidates `process_item_deltas` seeds on its
            # first call; starting that here would race it.
            return False
        if not items:
            if items is not None and self._item_baseline_is_empty_unlocked():
                # A read that succeeded and found nothing. It cannot move the
                # baseline (see below), but it is exactly the evidence the loot
                # gate needs, and this lane is the only one that sees it once a
                # second -- see `loot.note_empty_inventory_reading`.
                loot.note_empty_inventory_reading(
                    self._loot_state, stage_index=self.current_stage_index
                )
            return False

        run_timer_seconds = self._fresh_fast_run_timer_unlocked()
        latest_time = latest.game_time_seconds
        if run_timer_seconds is not None and latest_time is not None:
            if (
                float(run_timer_seconds) + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
                < float(latest_time)
            ):
                # The run clock went backwards: a new match started and the slow
                # path has not noticed yet. Its `_should_reset_for_snapshot`
                # owns that decision. Crediting here would attribute the new
                # run's starting inventory to the previous run.
                return False

        changes: dict[str, Any] = {
            "items": tuple(items),
            "items_available": True,
            "captured_at": float(self.clock()),
        }
        if run_timer_seconds is not None:
            # Item *events* carry `game_time_seconds`, and `before_time` rules
            # compare against it. A 10 s stale run time would misjudge those.
            changes["game_time_seconds"] = float(run_timer_seconds)
        self._fast_items = FastItems(
            captured_at=float(self.clock()),
            items=tuple(items),
        )
        self._process_item_deltas(replace(latest, **changes))
        self._cached_stage_summary = None
        return True

    @with_lock
    def update_fast_luck(self, luck: float | None) -> None:
        """Publish Luck from the fast loot pass.

        ``None`` clears the reading rather than storing a null one: an absent
        Luck and a Luck of zero are different facts, and the rarity model
        produces a perfectly valid distribution from zero. Clearing lets the
        consumer fall back to the 10 s snapshot's copy instead of rendering a
        failed read as a real one.
        """
        if luck is None:
            self._fast_luck = FastLuck()
            return
        self._fast_luck = FastLuck(captured_at=self.clock(), luck=float(luck))

    @with_lock
    def update_banishes(self, banishes: tuple[str, ...] | None) -> bool:
        """Fold the fast lane's persistent banish set into Loot Rarity.

        This is deliberately separate from ``update_items``: banished items
        never enter the inventory and must not participate in its two-read gain
        confirmation or spend any inventory-source exclusion.
        """
        latest = self._latest_snapshot_unlocked()
        if latest is None or not self._is_active_snapshot(latest) or banishes is None:
            return False
        loot.observe_run_position(
            self._loot_state,
            stage_index=self.current_stage_index,
            game_time_seconds=self._fresh_fast_run_timer_unlocked(),
            item_count=None,
            items_available=False,
        )
        loot.process_banishes(
            self._loot_state,
            tuple(banishes),
            luck=self._pass_luck_unlocked(latest),
            captured_at=self.clock(),
        )
        return True

    @with_lock
    def fast_luck(self) -> float | None:
        """The fast lane's Luck, or ``None`` when there is no fresh reading.

        A named getter beside ``get_loot_stats`` so a card that wants the chance
        row does not have to build a whole ``runtime_snapshot()`` -- that
        deep-copies the latest snapshot, which is not a price a repaint should
        pay for one float.
        """
        return self._fresh_fast_luck_unlocked()

    @with_lock
    def update_fast_size(self, size: float | None) -> None:
        if size is None:
            self._fast_size = FastSize()
            return
        self._fast_size = FastSize(captured_at=self.clock(), size=float(size))

    @with_lock
    def update_item_cooldowns(self, snapshot: Any | None) -> None:
        """Publish timed-item cooldowns from the fast loot pass.

        ``None`` clears rather than storing an empty reading, for the same
        reason ``update_fast_luck`` does: a pass that failed and an inventory
        holding no timed item are different facts, and only the second one may
        render as "nothing to show". Clearing lets the TTL retire the last good
        value instead of a failed read overwriting it with a plausible blank.
        """
        if snapshot is None:
            self._fast_item_cooldowns = FastItemCooldowns()
            return
        self._fast_item_cooldowns = FastItemCooldowns(
            captured_at=self.clock(), snapshot=snapshot
        )

    @with_lock
    def item_cooldowns(self) -> Any | None:
        """The fast lane's cooldown reading, or ``None`` when it is not fresh.

        A named getter beside ``fast_luck`` so a repaint does not have to build
        a whole ``runtime_snapshot()`` for it -- that deep-copies the latest
        snapshot, which no widget should pay for a countdown.
        """
        return self._fresh_item_cooldowns_unlocked()

    def _fresh_item_cooldowns_unlocked(self) -> Any | None:
        reading = self._fast_item_cooldowns
        if reading.captured_at <= 0 or reading.snapshot is None:
            return None
        if self.clock() - reading.captured_at > FAST_ITEM_COOLDOWNS_TTL_SECONDS:
            return None
        return reading.snapshot

    def _fresh_fast_luck_unlocked(self) -> float | None:
        fast_luck = self._fast_luck
        if fast_luck.captured_at <= 0 or fast_luck.luck is None:
            return None
        if self.clock() - fast_luck.captured_at > FAST_LUCK_TTL_SECONDS:
            return None
        return fast_luck.luck

    def _fresh_fast_size_unlocked(self) -> float | None:
        fast_size = self._fast_size
        if fast_size.captured_at <= 0 or fast_size.size is None:
            return None
        if self.clock() - fast_size.captured_at > FAST_SIZE_TTL_SECONDS:
            return None
        return fast_size.size

    @with_lock
    def last_item_losses(self) -> tuple[ItemLossEvent, ...]:
        """The item losses confirmed by the most recent item pass.

        Both entry points into ``_process_item_deltas`` -- the 1 s fast lane and
        the 10 s snapshot -- replace this, so a consumer reads it in the pass it
        was written by rather than treating it as a queue.
        """
        return self._last_item_losses

    def _item_baseline_is_empty_unlocked(self) -> bool:
        # A method rather than a direct `items.baseline_is_empty(...)` call at
        # the use site: `update_items`'s own parameter is named `items` and
        # shadows the module there.
        return items.baseline_is_empty(self._tracked_item_state)

    def _fresh_fast_items_unlocked(self) -> tuple[str, ...] | None:
        fast_items = self._fast_items
        if fast_items.captured_at <= 0 or fast_items.items is None:
            return None
        if self.clock() - fast_items.captured_at > FAST_ITEMS_TTL_SECONDS:
            return None
        return fast_items.items

    def _fresh_fast_run_timer_unlocked(self) -> float | None:
        timer = self._fast_run_timer
        if timer.captured_at <= 0 or timer.run_timer_seconds is None:
            return None
        if self.clock() - timer.captured_at > FAST_RUN_TIMER_TTL_SECONDS:
            return None
        return timer.run_timer_seconds

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
        is_final_boss_stage: bool = False,
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
            # Stage 4 on the fast lane comes from the game's own flag and from
            # nothing else.
            #
            # The heuristics cannot be trusted *here* specifically. Their one
            # defence against an ordinary stage change is that a real stage
            # boundary loads a new ``stage_ptr`` while the boss room reuses the
            # old one -- but ``_fast_stage_summary_snapshot_unlocked`` builds the
            # fast sample with ``replace(latest_snapshot, ...)``, so it *inherits*
            # that pointer and the comparison is always "same ptr". The guard is
            # structurally dead on this path. A fresh fast timer measured against
            # a slow snapshot that is merely old then reads as a collapse, which
            # is a live-observed false Stage 4 on the 2 -> 3 transition.
            #
            # The slow lane keeps them: there both sides are real snapshots
            # carrying real pointers, so the boundary check does its job.
            if self.current_stage_index == 3:
                next_stage_index = 4 if is_final_boss_stage else min(next_stage_index, 3)
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

    def _recent_powerups_snapshot_unlocked(self) -> PowerupsSnapshot:
        return powerups.recent_snapshot(self._powerup_state, self.clock())

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

    # A game restart is a *silence*, not an error, and it is the common case:
    # the process goes away for a few seconds and comes back. Reporting `stale`
    # the instant the 5 s window lapses made the OBS overlay swap a widget for a
    # status card mid-scene for one or two polls -- the visual break the overlay
    # status audit is about. `reconnecting` is the quiet middle: the payload is
    # known to be frozen, but the surface is expected to keep showing the last
    # good frame rather than announce anything. Only past the grace window does
    # the state become `stale`, which is the one worth showing and logging.
    def _status_unlocked(self, now: float) -> str:
        if not self.snapshots:
            return "no_game" if self._last_no_game_at is not None else "waiting"
        if self._last_no_game_at is not None:
            return "no_game"
        if self._last_update_at is None:
            return "stale"
        silence = now - self._last_update_at
        if silence <= self.stale_after_seconds:
            return "live"
        if silence <= self.stale_after_seconds + self.reconnect_grace_seconds:
            return "reconnecting"
        return "stale"

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
        self._permanent_source_generation += 1
        self.run_id = uuid4().hex
        self._lifecycle = RunLifecycle.ACTIVE
        self.snapshots.clear()
        self._fast_stage_boundaries.clear()
        self._fast_stage_timer_context = FastStageTimerContext()
        self._fast_run_timer = FastRunTimer()
        self._fast_items = FastItems()
        self._fast_luck = FastLuck()
        self._fast_item_cooldowns = FastItemCooldowns()
        self._pending_fast_stage_index = None
        self._pending_fast_stage_samples = 0
        self._pending_fast_stage_boundary = None
        self._pending_fast_stage_awaiting_timer_reset = False
        self._slow_stage_timer_reset_pending_from = None
        combat.reset(self._combat_state)
        self.current_stage_index = 1
        chests.reset(self._chest_state)
        loot.reset(self._loot_state)
        self._reset_current_run_item_baseline()
        self._reset_chaos_tracking()
        shrines.reset(self._shrine_state)
        passives.reset(self._character_passive_state)
        # Drops the per-effect observation history along with the snapshot:
        # continuity across a run reset is exactly the thing it must not claim.
        powerups.clear(self._powerup_state)
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

    def _process_item_deltas(self, snapshot: LiveRunSnapshot) -> tuple[ItemLossEvent, ...]:
        pass_luck = self._pass_luck_unlocked(snapshot)
        losses = items.process_item_deltas(
            self._tracked_item_state,
            snapshot,
            current_stage_index=self.current_stage_index,
            luck=pass_luck,
        )
        # Losses before gains: a decrease opens the debt that a gain in the same
        # pass may settle. The craft output takes seconds to reach the inventory
        # so the two practically never share a pass, but the order is the one
        # the design states and costs nothing to honour.
        loot.observe_run_position(
            self._loot_state,
            stage_index=self.current_stage_index,
            game_time_seconds=snapshot.game_time_seconds,
            # The inventory as this pass read it. An empty one on the first map
            # means no roll has been missed however late the app attached, so it
            # is measurable -- see `observe_run_position`. `items_available`
            # comes with it because an empty tuple from a failed read is not an
            # empty inventory.
            item_count=len(snapshot.items or ()),
            items_available=bool(snapshot.items_available),
        )
        loot.note_map_identity(
            self._loot_state,
            stage_ptr=snapshot.stage_ptr,
            map_seed=snapshot.map_seed,
        )
        loot.process_banishes(
            self._loot_state,
            snapshot.banishes,
            luck=pass_luck,
            captured_at=snapshot.captured_at,
        )
        loot.process_item_losses(self._loot_state, losses)
        loot.process_item_gains(self._loot_state, self._last_item_gains)
        return losses

    def _pass_luck_unlocked(self, snapshot: LiveRunSnapshot) -> float | None:
        """Luck as this pass read it, falling back to the 10 s snapshot's copy.

        The fast reading is the one that matters -- it is published by the same
        ``RefreshTickContext`` that supplied the inventory, which is what makes
        a gain and its Luck coherent by construction rather than by matching
        timestamps. The fallback is not a second-best sample of the same fact so
        much as the only one available on a pass the fast lane did not run
        (the item task disabled, or a failed ``LUCK`` read); it is up to 10 s
        old, and at that age the rarity probabilities have still barely moved.
        """
        fast_luck = self._fresh_fast_luck_unlocked()
        if fast_luck is not None:
            return fast_luck
        stats = snapshot.stats if isinstance(snapshot.stats, dict) else {}
        return getattr(stats.get("Luck"), "value", None)

    @with_lock
    def update_loot_interactables(self, counters: dict[str, int]) -> None:
        """Publish ``InteractablesStatus`` ``numUsed`` from the fast loot pass.

        Read in the same pass as the inventory, and folded *before* it: a Moai
        increment excludes the gain that follows it and the merchant's the one
        before, and at the 1 s cadence both collapse to "this tick or the next".
        """
        loot.update_interactable_counters(
            self._loot_state, counters, captured_at=self.clock()
        )

    @with_lock
    def get_loot_stats(self) -> LootStatsSnapshot:
        return self._get_loot_stats_unlocked()

    def _get_loot_stats_unlocked(self) -> LootStatsSnapshot:
        return loot.get_loot_stats(self._loot_state)
