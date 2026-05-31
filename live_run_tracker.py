from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable
from uuid import uuid4

import copy
import threading
from functools import wraps

import run_summary
from gui_styles import PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS


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
    damage_sources: tuple[Any, ...] = ()
    damage_sources_available: bool = False
    chests_per_minute: float | None = None
    game_time_seconds: float | None = None
    stage_time_seconds: float | None = None
    mob_kills: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0


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
    def __init__(
        self,
        *,
        tracked_item_rules: Iterable[TrackedItemRule] = DEFAULT_TRACKED_ITEM_RULES,
        max_snapshots: int = 3600,
        stale_after_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.tracked_item_rules = tuple(tracked_item_rules)
        self.max_snapshots = max(1, int(max_snapshots))
        self.stale_after_seconds = max(0.1, float(stale_after_seconds))
        self.clock = clock
        self.run_id: str | None = None
        self.snapshots: deque[LiveRunSnapshot] = deque(maxlen=self.max_snapshots)
        self.current_stage_index = 1
        self._last_update_at: float | None = None
        self._last_failed_at: float | None = None
        self._last_no_game_at: float | None = None
        self._previous_item_counts: dict[str, int] | None = None
        self._tracked_events: list[TrackedItemEvent] = []
        self._tracked_counts: dict[str, int] = {rule.id: 0 for rule in self.tracked_item_rules}
        self._unknown_starting_inventory: dict[str, int] = {rule.id: 0 for rule in self.tracked_item_rules}
        self._cached_stage_summary: list[dict[str, Any]] | None = None
        self._lock = threading.RLock()

    @with_lock
    def update(self, snapshot: LiveRunSnapshot) -> None:
        self._cached_stage_summary = None
        now = self.clock()
        self._last_update_at = now
        self._last_failed_at = None
        self._last_no_game_at = None
        if not self._is_active_snapshot(snapshot):
            if not self.snapshots:
                return
            self.snapshots.append(snapshot)
            return

        if self._should_reset_for_snapshot(snapshot):
            self._reset_for_new_run()

        if self.run_id is None:
            self.run_id = uuid4().hex
            self.current_stage_index = 1

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
        self._process_item_deltas(snapshot)

    @with_lock
    def mark_read_failed(self, *, no_game: bool = False) -> None:
        now = self.clock()
        self._last_failed_at = now
        if no_game:
            self._last_no_game_at = now

    @with_lock
    def set_tracked_item_rules(self, rules: Iterable[TrackedItemRule]) -> None:
        self.tracked_item_rules = tuple(rules)
        snapshots = list(self.snapshots)
        self._reset_tracking_only()
        if not snapshots:
            return
        previous_stage_index = self.current_stage_index
        self.current_stage_index = 1
        self._previous_item_counts = None
        previous_snapshot = None
        for snapshot in snapshots:
            if previous_snapshot is not None and self._is_active_snapshot(snapshot):
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
            self._process_item_deltas(snapshot)
            previous_snapshot = snapshot
        self.current_stage_index = previous_stage_index

    @with_lock
    def stage_summary_rows(self) -> list[dict[str, Any]]:
        """
        Returns a summary of stages in the current run.
        The result is cached to avoid double calculation in the same update tick,
        and returned as a deep copy to prevent mutation bugs by callers.
        """
        if self._cached_stage_summary is None:
            self._cached_stage_summary = run_summary.build_stage_summary(tuple(self.snapshots))
        return copy.deepcopy(self._cached_stage_summary)

    @with_lock
    def tracked_item_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for rule in self.tracked_item_rules:
            rows.append(
                {
                    "id": rule.id,
                    "label": rule.label,
                    "count": int(self._tracked_counts.get(rule.id, 0)),
                    "unknown_starting_inventory": int(self._unknown_starting_inventory.get(rule.id, 0)),
                    "mode": rule.mode,
                }
            )
        return rows

    @with_lock
    def run_identity(self) -> tuple[str | None, int]:
        return self.run_id, self.current_stage_index

    @with_lock
    def latest_snapshot(self) -> LiveRunSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    @with_lock
    def status(self) -> str:
        now = self.clock()
        if not self.snapshots:
            return "no_game" if self._last_no_game_at is not None else "waiting"
        if self._last_no_game_at is not None:
            return "no_game"
        if self._last_update_at is None or now - self._last_update_at > self.stale_after_seconds:
            return "stale"
        return "live"

    def _reset_for_new_run(self) -> None:
        self.run_id = uuid4().hex
        self.snapshots.clear()
        self.current_stage_index = 1
        self._reset_tracking_only()
        self._cached_stage_summary = None

    def _reset_tracking_only(self) -> None:
        self._previous_item_counts = None
        self._tracked_events = []
        self._tracked_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._unknown_starting_inventory = {rule.id: 0 for rule in self.tracked_item_rules}

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
        for item_name, count in counts.items():
            if count <= 0:
                continue
            if is_clearly_early:
                self._process_item_gain(
                    item_name=item_name,
                    gained_count=count,
                    snapshot=snapshot,
                    stage_index=1,
                )
            else:
                self._mark_unknown_starting_inventory(item_name, count)

    def _process_item_gain(
        self,
        *,
        item_name: str,
        gained_count: int,
        snapshot: LiveRunSnapshot,
        stage_index: int,
    ) -> None:
        for rule in self.tracked_item_rules:
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

    def _mark_unknown_starting_inventory(self, item_name: str, count: int) -> None:
        for rule in self.tracked_item_rules:
            if self._rule_matches_item(rule, item_name):
                self._unknown_starting_inventory[rule.id] = (
                    self._unknown_starting_inventory.get(rule.id, 0) + count
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
    return display_name.lower().replace("'", "").replace("’", "").replace("`", "")