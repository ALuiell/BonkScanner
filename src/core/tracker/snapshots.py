"""Live-run tracker snapshot types: the frozen, read-only views the tracker
publishes to consumers (GUI, projections, worker threads).

Distinct from the tracker's internal mutable feature states (``_RunState``,
``_CombatState``, ...), which stay in ``live_run_tracker.py`` until step 13.
Qt-free and I/O-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.stats.formatters import format_chaos_tome_stat_delta


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
    # ``MapController.isFinalBossStage``: the game naming the boss room outright,
    # rather than the side effects every other stage-4 signal has to infer it
    # from. Consumed as a positive signal only -- ``False`` covers both "not the
    # boss room" and "the read failed", so it may never retract a promotion.
    is_final_boss_stage: bool = False


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
class ItemLossEvent:
    """A *confirmed* drop in one item's count, timestamped from the read that
    observed the drop rather than from the read that confirmed it.

    The mirror image of the gain side's ``TrackedItemEvent``, and published for
    the same reason a gain is: a decrease is a fact about the run, not merely a
    baseline correction. Nothing here interprets it -- the item that left the
    inventory is named, and what that means (a microwave craft, ``Za Warudo``
    breaking) is the consumer's question.
    """

    item_name: str
    lost_count: int
    game_time_seconds: float | None
    stage_index: int
    map_seed: int | None
    captured_at: float


@dataclass(frozen=True)
class _PendingItemIncrease:
    observed_count: int
    snapshot: LiveRunSnapshot
    stage_index: int
    combo_stage_index: int
    initial_map_one_only: bool = False


@dataclass(frozen=True)
class _PendingItemDecrease:
    """A count that has been read *low* once and is not believed yet.

    Deliberately the same shape as ``_PendingItemIncrease`` minus the two
    fields only the rule engine needs. The game rebuilds the item array in
    place, so a single low read is a torn read until a second one agrees --
    exactly the reason increases are held pending, and a decrease applied on
    first sight would turn every torn read into a phantom item loss.
    """

    observed_count: int
    snapshot: LiveRunSnapshot
    stage_index: int


@dataclass(frozen=True)
class ChaosTomeStatTotal:
    stat_id: int
    label: str
    value: float
    value_format: Any
    rolls: int

    @property
    def display_delta(self) -> str:
        return format_chaos_tome_stat_delta(self.label, self.value, self.value_format)


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
    # The same read as ``powerups``, but through a longer grace window. For a
    # consumer with a repaint loop the two are interchangeable; for one that
    # answers a question once -- the Twitch ``!powerups`` command -- they are
    # not, because a single missed tick empties ``powerups`` and an empty
    # snapshot is indistinguishable from "no effects are active".
    powerups_recent: PowerupsSnapshot


@dataclass(frozen=True)
class FastStageTimerContext:
    captured_at: float = 0.0
    stage_timer_seconds: float | None = None
    stage_index: int | None = None
    stage_duration_seconds: float | None = None


@dataclass
class FastRunTimer:
    """The run clock, published by every successful ``RUN_TIMER`` source read.

    Deliberately separate from ``_recent_kills_history``. Before step 28c the
    fast Stage Summary took its ``game_time_seconds`` from
    ``_recent_kills_history[-1]``, so the run clock was published only by the
    kill sample -- and a kills read that failed froze the clock along with it,
    even though the timer beside it had been read successfully. These are two
    different facts and they now have two different homes.
    """

    captured_at: float = 0.0
    run_timer_seconds: float | None = None


@dataclass
class FastItems:
    """The passive inventory, published by the fast-lane ``PASSIVE_ITEMS`` read.

    Separate from the slow snapshot's ``items`` for the same reason
    ``FastRunTimer`` is separate from the kill history: the full snapshot keeps
    reading and publishing items on its own 10 s cadence, and this is a second
    consumer of the same source, not a replacement for the first.

    ``captured_at`` is the tracker clock, and freshness is bounded by
    ``FAST_ITEMS_TTL_SECONDS`` -- a stale inventory must not be projected onto
    a stage boundary as if it had been observed there.
    """

    captured_at: float = 0.0
    items: tuple[str, ...] | None = None


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

    @property
    def expected_complete(self) -> bool:
        """Whether Expected covers every normal chest represented by the counters."""
        return (
            self.counters_available
            and self.expected_available
            and self.expected_tracked_opens == self.normal_opened
        )


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
    # Set only by ``powerups.recent_snapshot``: this read is past the strict
    # TTL but still worth quoting. ``available`` stays False so that nothing
    # painting from the strict accessor changes behaviour; a consumer that
    # must answer *now* checks this to tell a late read from no read at all.
    stale: bool = False


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
