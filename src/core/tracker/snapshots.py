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
class ItemGainEvent:
    """A *confirmed* rise in one item's count, timestamped -- and *Luck-stamped*
    -- from the read that observed the rise rather than the one that confirmed it.

    The sibling of ``ItemLossEvent``.  ``TrackedItemEvent`` is not this: that one
    is emitted per matching rule and says nothing about an item no rule names,
    whereas the loot tracker treats **every** confirmed gain as a rarity roll.

    ``luck`` is the value read in the same pass as the rise, which is what makes
    ``P(tier | Luck_j)`` answerable at all -- Luck sweeps continuously through a
    run, so a gain matched against the current reading rather than its own would
    accumulate expectation at the wrong point on the curve.  ``None`` means the
    Luck read failed, and a gain with no Luck is dropped from both sides of the
    comparison rather than counted on one.
    """

    item_name: str
    gained_count: int
    luck: float | None
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
    # Luck as it stood in the pass that observed the rise. Carried on the
    # *pending* record rather than resolved at confirmation time: confirmation is
    # a tick later by construction, and by then Luck has moved.
    luck: float | None = None


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
    # The per-tier actual-against-expected summary, computed on the tracker and
    # carried here ready to render. ``projections/`` may import ``core/`` only
    # (§2 layer table), so the OBS projector cannot reach the rarity model or the
    # loot state itself -- it has to be handed the finished numbers.
    loot_stats: LootStatsSnapshot
    kps: dict[str, int | None]
    feature_status: dict[str, FeatureStatus]
    chaos_tome: Any | None
    shrines: Any | None
    character_passive: Any | None
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
    # Luck, from the fast loot pass rather than from ``latest_snapshot.stats``.
    # ``None`` means no fresh read -- never "Luck is zero", which is a real
    # reading the rarity model produces a valid distribution from.
    luck: float | None = None
    size: float | None = None
    # The inventory, from the same 1 s ``PASSIVE_ITEMS`` pass that publishes
    # ``luck``. ``latest_snapshot.items`` is the 10 s snapshot's copy -- the fast
    # lane never appends a snapshot, it publishes here and folds its deltas into
    # the tracked-item state -- so a consumer that wants the inventory *now*
    # reads this and falls back to ``latest_snapshot`` when it is ``None``.
    # ``None`` is "no fresh read", never "the inventory is empty".
    fast_items: tuple[str, ...] | None = None
    # Timed-item cooldowns and the game clock they were read against, from that
    # same 1 s pass. One object rather than two fields precisely so a consumer
    # cannot pair a reading with a clock from a different pass. ``None`` is "no
    # fresh read"; a snapshot with empty ``readings`` is "no timed item held".
    item_cooldowns: Any | None = None
    # Fresh run clock already read by the combat fast lane.  Publishing it on
    # the boundary lets derived consumers share the read instead of polling.
    run_timer_seconds: float | None = None
    # Highest kill total observed by either the full snapshot or the combat
    # fast lane. The counter is monotonic within one run, so this is the fresh
    # value consumers should persist instead of the 10 s snapshot's copy.
    mob_kills: int | None = None


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


@dataclass
class FastLuck:
    """Luck, published by the fast-lane ``LUCK`` read.

    Read in the same pass as ``PASSIVE_ITEMS``, which is the whole point: the
    rarity roll behind an item gain happened at the Luck the player held when
    the gain was observed, and reading both from one ``RefreshTickContext``
    makes that true by construction rather than by matching two timestamps
    afterwards.

    ``luck`` stays ``None`` when the read failed, matching what the full
    snapshot puts in ``PlayerStatValue.value`` for the same failure.
    """

    captured_at: float = 0.0
    luck: float | None = None


@dataclass
class FastSize:
    captured_at: float = 0.0
    size: float | None = None


@dataclass
class FastItemCooldowns:
    """Timed-item cooldowns, published by the fast-lane ``PASSIVE_ITEMS`` read.

    ``snapshot`` carries the readings **and** the ``my_time`` they were taken
    against, together, because the countdown is their difference and sampling
    the two separately would reintroduce the skew the single pass exists to
    remove.

    ``None`` is "no fresh read", never "no cooldowns". An inventory holding no
    timed item produces a snapshot with an empty ``readings`` tuple, which is a
    real answer; a failed pass produces nothing at all and the TTL retires the
    last good one. The two must stay distinguishable or a missed pass renders
    as "this item has no cooldown".

    The TTL does **not** cover a finished run. Measured on the death screen: the
    game clock freezes bit-exact, the item dictionary stays intact, and every
    read keeps succeeding -- so there is no failure for a freshness bound to
    catch, and the countdown would sit frozen forever. Clearing that is
    ``RunLifecycle``'s job, not this one's.
    """

    captured_at: float = 0.0
    snapshot: Any | None = None


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
    expected_initialized: bool = False

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

    @property
    def expected_status(self) -> str:
        """Why Expected is complete or intentionally hidden."""
        if self.expected_complete:
            return "complete"
        if not self.expected_available:
            return "baseline_missed" if self.expected_initialized else "pending"
        if not self.counters_available:
            return "counters_unavailable"
        return "coverage_mismatch"


@dataclass(frozen=True)
class LootStatsSnapshot:
    """Actual against expected rarities for the current run, and nothing else.

    ``available`` is a hard gate, stricter than ``ChestStatsSnapshot``'s: a run
    the app did not watch from its start has *both* halves wrong, because the
    items already held were absorbed into the item baseline as a single silent
    block. Partial numbers are not a degraded version of this answer, they are a
    different and false one.
    """

    actual: dict[str, int]
    expected: dict[str, float]
    # ``acquisitions`` can never be fewer than ``map_chest_opens``: the counters
    # see every chest spawned at map generation and nothing else, so the excess
    # is dropped chests (expected -- three quarters of the recorded sample) plus
    # the three excluded sources. A *shortfall* would mean the model has lost
    # gains, and a runaway excess an item source it does not know about. This is
    # the standing check the design asks to log rather than a displayed figure.
    acquisitions: int
    map_chest_opens: int
    available: bool
    # Distinguishes "decided unmeasurable" from "not decided yet" once
    # ``available`` alone reads the same (``False``) in both -- the difference
    # a waiting-for-first-item message needs from a missed-the-start one.
    availability_decided: bool = False
    outstanding_tier_debts: tuple[str, ...] = ()


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
