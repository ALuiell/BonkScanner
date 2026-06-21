from __future__ import annotations

from collections import deque
from dataclasses import dataclass
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
    stage_time_seconds: float | None = None
    mob_kills: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0
    stage_index: int | None = None


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
    pickup_ui: str
    expires_ui: str
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
    available: bool = False


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

STAT_LABEL_ABBREVIATIONS: dict[str, str] = {
    "Max HP": "HP",
    "HP Regen": "Regen",
    "Overheal": "Overheal",
    "Shield": "Shield",
    "Armor": "Armor",
    "Evasion": "Evasion",
    "Lifesteal": "Lifesteal",
    "Thorns": "Thorns",
    "Damage": "DMG",
    "Crit Chance": "Crit",
    "Crit Damage": "CritDMG",
    "Attack Speed": "AS",
    "Projectile Count": "Proj",
    "Projectile Bounces": "Bounces",
    "Size": "Size",
    "Projectile Speed": "ProjSpeed",
    "Duration": "Dur",
    "Damage to Elites": "EliteDMG",
    "Knockback": "KB",
    "Movement Speed": "MS",
    "Extra Jumps": "Jumps",
    "Jump Height": "JumpHeight",
    "Luck": "Luck",
    "Difficulty": "Diff",
    "Pickup Range": "Pickup",
    "XP Gain": "XP",
    "Gold Gain": "Gold",
    "Elite Spawn Increase": "ESI",
    "Powerup Multiplier": "PM",
    "Powerup Drop Chance": "PDC",
}


def chaos_tome_stat_sort_key(total: Any) -> tuple[int, str]:
    stat_id = int(getattr(total, "stat_id", -1))
    return (CHAOS_TOME_GAME_STAT_ORDER.get(stat_id, 999), str(getattr(total, "label", "")).lower())


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
        self._combo_run_counts: dict[str, int] = {rule.id: 0 for rule in self.tracked_item_rules}
        self._chaos_tome_level: int | None = None
        self._chaos_modifier_baselines: dict[int, tuple[float, ...]] = {}
        self._chaos_totals: dict[int, ChaosTomeStatTotal] = {}
        self._chaos_ambiguous_rolls = 0
        self._chaos_available_rolls = 0
        self._chaos_unbudgeted_candidates: dict[tuple[int, int], tuple[float, int]] = {}
        self._cached_stage_summary: list[dict[str, Any]] | None = None
        self._chests_opened = 0
        self._chests_total = 46
        self._keys_count = 0
        self._paid_chest_opens = 0
        self._key_chest_procs = 0
        self._free_chest_opens: int | None = None
        self._chest_counters_available = False
        self._chest_history_incomplete = False
        self._total_opened_minimum: int | None = None
        self._total_opened_is_minimum = False
        self._expected_key_procs = 0.0
        self._expected_tracked_opens = 0
        self._expected_chests_bought: int | None = None
        self._expected_keys_count: int | None = None
        self._expected_available = False
        self._expected_detected_run_reset = False
        self._stage_ptrs_seen = []
        self._stage_numbers_by_ptr: dict[int, int] = {}
        self._chests_opened_by_stage = {}
        self._chests_total_by_stage = {}
        self._disabled_items_cache: tuple[str, ...] | None = None
        self._powerups_snapshot = PowerupsSnapshot()
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
        if snapshot.disabled_items_available:
            self._disabled_items_cache = snapshot.disabled_items
        self._process_item_deltas(snapshot)

    @with_lock
    def mark_read_failed(self, *, no_game: bool = False) -> None:
        now = self.clock()
        self._last_failed_at = now
        if no_game:
            self._last_no_game_at = now

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
            label = STAT_LABEL_ABBREVIATIONS.get(total.label, total.label)
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
    def run_identity(self) -> tuple[str | None, int]:
        return self.run_id, self.current_stage_index

    @with_lock
    def latest_snapshot(self) -> LiveRunSnapshot | None:
        return self._latest_snapshot_unlocked()

    def _latest_snapshot_unlocked(self) -> LiveRunSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

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
    def update_powerups(self, snapshot: Any) -> None:
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
                    expiration_time = float(getattr(effect, "expiration_time", 0.0))
                    remaining = expiration_time - float(my_time)
                    if remaining <= 0 or not isfinite(remaining):
                        continue
                    base_duration = 12.0 if effect_id == 4 else 15.0
                    duration = base_duration * powerup_multiplier
                    pickup_time = expiration_time - duration
                    raw_pickup = float(stage_timer) + (pickup_time - float(my_time))
                    raw_expiration = float(stage_timer) + (expiration_time - float(my_time))
                    if not isfinite(raw_pickup) or not isfinite(raw_expiration):
                        continue
                except (TypeError, ValueError, OverflowError):
                    continue
                active.append(
                    PowerupEffectState(
                        effect_id=effect_id,
                        name=str(getattr(effect, "name", effect_id)),
                        pickup_ui=self._format_ui_stage_time(raw_pickup, float(stage_time)),
                        expires_ui=self._format_ui_stage_time(raw_expiration, float(stage_time)),
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
            available=True,
        )

    @with_lock
    def clear_powerups(self) -> None:
        self._powerups_snapshot = PowerupsSnapshot()

    @with_lock
    def powerups_snapshot(self) -> PowerupsSnapshot:
        return self._powerups_snapshot

    @with_lock
    def format_powerups_summary(self, *, include_left_word: bool = True) -> str:
        snapshot = self._powerups_snapshot
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
        snapshot = self._powerups_snapshot
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
        if snapshot.active:
            parts = []
            suffix = " left" if include_left_word else ""
            for effect in snapshot.active:
                parts.append(
                    f"{effect.name} {effect.pickup_ui} -> {effect.expires_ui} "
                    f"({self._format_duration_seconds(effect.remaining_seconds)}s{suffix})"
                )
            return " | ".join(parts)
        if (
            snapshot.standard_duration_seconds is None
            or snapshot.clock_duration_seconds is None
        ):
            return "none active"
        return (
            "none active | Durations: "
            f"standard {self._format_duration_seconds(snapshot.standard_duration_seconds)}s, "
            f"clock {self._format_duration_seconds(snapshot.clock_duration_seconds)}s"
        )

    @with_lock
    def update_chests_and_keys(self, chests_opened: int, chests_total: int, keys_count: int) -> None:
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

    def _reset_for_new_run(self) -> None:
        self.run_id = uuid4().hex
        self.snapshots.clear()
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

    def _reset_tracking_only(self) -> None:
        self._reset_current_run_item_baseline()
        self._tracked_events = []
        self._tracked_counts = {rule.id: 0 for rule in self.tracked_item_rules}
        self._combo_run_counts = {rule.id: 0 for rule in self.tracked_item_rules}

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
        initial_stage_index = 1 if self._snapshot_looks_like_first_stage(snapshot) else 2
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
