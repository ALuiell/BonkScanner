"""Item-rarity loot tracking: pure functions over ``_LootState``.

Same shape as ``chests.py`` -- a mutable state dataclass, module-level
functions, no lock of its own; ``LiveRunTracker`` calls in while holding its
single ``RLock``.

The question this answers is "did the run's rolls land where the game's own
model said they would".  Because a *dropped* chest is invisible to every
counter the game exposes, the count of chest openings cannot drive the maths.
The design is therefore inverted: **every confirmed item gain is a roll**, and
only the three sources that use a different model are excluded.  A newly
banished item is also a roll: it came from a chest but deliberately never
entered the inventory.  No per-item source attribution beyond that persistent
banish ledger is needed, and none is attempted.

Three exclusions, and they are not the same shape as each other:

* **Microwave** -- a confirmed *decrease* opens a **debt** for the consumed
  tier, and the next gain of that tier settles it uncounted.  Deliberately not
  a time window.  The craft finishes in 2-3 s but its output lands on the
  ground, so it reaches the inventory only when the player walks over it: the
  gaps measured live were 8.6 / 12.6 / 9.3 s and were the player being chased
  off by mobs, not craft latency.  There is no upper bound to size a window
  against.  Mis-settling is harmless -- if a chest yields the same tier first,
  the debt settles against the chest item and the craft output is counted
  instead, and since the two carry the same tier the totals are identical
  either way.  Item identity never enters the maths.
* **Moai** -- the counter fires when the choice opens, *before* the grant, so
  the increment excludes the **next** gain.  The player cannot leave the choice
  without taking exactly one item, so this is an untimed, map-scoped queue.
* **Shady Guy** -- the counter fires once trading ends, *after* the item is
  granted, so the increment excludes the **preceding** gain (2 s backward).

``Za Warudo`` never opens a debt.  It breaks and leaves the inventory when the
player is killed and is the only self-consuming item in the game; read as a
craft it would raise a phantom ``LEGENDARY`` debt and silently swallow the next
genuine legendary, so ``actual`` would undercount while ``expected`` did not.

Where a rarity or a Luck reading cannot be resolved the gain is dropped from
**both** sides.  Accumulating expectation for a gain whose tier cannot be
recorded would drift the two numbers apart, which matters more than
completeness.  It is also what makes Corrupt-chest items harmless without a
line of special-case code: they carry ``EItemRarity.Corrupted``, outside our
four tiers, so they fall out on their own.

The measured windows, the disassembly behind the roll, and the reasoning for
each decision above are in ``docs/updates/functional_updates.md``, item 5.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from core.item_metadata import ITEM_RARITY_BY_NAME, normalize_item_name_for_rarity
from core.luck_rarity import LUCK_RARITY_ORDER, calculate_luck_rarity_probabilities
from core.run_summary import PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
from core.tracker.snapshots import ItemGainEvent, ItemLossEvent, LootStatsSnapshot

# The merchant's counter and its item arrive together, so the backward window
# only has to absorb a 1 s poll splitting them across two reads. Moai deliberately
# has no time constant: its choice cannot be left without taking one item.
SHADY_GUY_BACKWARD_WINDOW_SECONDS = 2.0

MOAI_COUNTER_LABEL = "Moais"
SHADY_GUY_COUNTER_LABEL = "Shady Guy"
CHEST_COUNTER_LABEL = "Chests"

# The one item that leaves the inventory without a microwave having eaten it.
# Matched on the canonical rarity name, so every spelling the scanner or the
# metadata table produces folds onto it.
SELF_CONSUMING_ITEM_NAMES = frozenset({"Za Warudo"})

# The same bound `items.initial_item_increase_candidates` uses to decide whether
# an inventory it is seeing for the first time is a run's opening inventory or a
# mid-run attach.  Stated against that function on purpose: the two must agree,
# because it is exactly the items that function absorbs into the baseline that
# make a late-attached run unmeasurable.
#
# Only the *second* of the two arms in `observe_run_position`. An inventory that
# is empty needs no window at all, because that function absorbs nothing from
# one -- it builds a candidate only `if count > 0`.
LATE_ATTACH_GRACE_SECONDS = 10.0

# The backward window spans two polls at the production 1 s cadence, and a gain
# observed inside it is reported one pass after it was seen. Anything the
# window has not claimed by then was never the merchant's.
_RECENT_GAIN_MEMORY = 16


def _zero_actual() -> dict[str, int]:
    return {tier: 0 for tier in LUCK_RARITY_ORDER}


def _zero_expected() -> dict[str, float]:
    return {tier: 0.0 for tier in LUCK_RARITY_ORDER}


@dataclass
class _PendingShadyExclusion:
    """One merchant increment waiting for its preceding inventory gain."""

    opened_at: float


@dataclass
class _RecordedGain:
    """A counted roll, kept only long enough for a backward window to reach it.

    Holds the expectation it contributed rather than recomputing it: a
    retro-exclusion has to remove the *same* numbers it added, and Luck has
    moved on by the time the merchant's counter is read.
    """

    captured_at: float
    tier: str
    expected: dict[str, float]


@dataclass
class _LootState:
    actual: dict[str, int] = field(default_factory=_zero_actual)
    expected: dict[str, float] = field(default_factory=_zero_expected)
    acquisitions: int = 0
    map_chest_opens: int = 0
    available: bool = False
    availability_decided: bool = False
    # Retained evidence: an empty inventory seen on the first map, before the
    # decision is spent. Set only there, and never unset except by a full reset
    # -- see `observe_run_position`.
    observed_empty_first_map: bool = False
    # Consumed tiers awaiting their craft output, oldest first. A queue rather
    # than a set: two crafts of the same tier owe two exclusions.
    tier_debts: list[str] = field(default_factory=list)
    pending_moai_exclusions: int = 0
    pending_shady_exclusions: list[_PendingShadyExclusion] = field(default_factory=list)
    recent_gains: deque[_RecordedGain] = field(
        default_factory=lambda: deque(maxlen=_RECENT_GAIN_MEMORY)
    )
    banish_baseline_initialized: bool = False
    seen_banishes: set[str] = field(default_factory=set)
    counter_values: dict[str, int] = field(default_factory=dict)
    last_counter_read_at: float | None = None
    map_identity: tuple[int, int | None] | None = None
    last_game_time_seconds: float | None = None
    expected_detected_run_reset: bool = False


def _clear_run_totals(state: _LootState) -> None:
    state.actual = _zero_actual()
    state.expected = _zero_expected()
    state.acquisitions = 0
    state.map_chest_opens = 0
    state.available = False
    state.availability_decided = False
    state.observed_empty_first_map = False
    state.tier_debts = []
    state.pending_moai_exclusions = 0
    state.pending_shady_exclusions = []
    state.recent_gains.clear()
    state.banish_baseline_initialized = False
    state.seen_banishes.clear()
    state.counter_values = {}
    state.last_counter_read_at = None
    state.map_identity = None
    state.last_game_time_seconds = None


def reset(state: _LootState) -> None:
    """Start a new run -- unless this module already started it.

    ``expected_detected_run_reset`` is ``_ChestState``'s guard, and it is here
    for the same reason: this module runs on the 1 s lane and the tracker-wide
    reset arrives from the 10 s snapshot, so by the time ``reset`` is called the
    new run may already have real rolls in it. Zeroing twice would wipe them.
    """
    if state.expected_detected_run_reset:
        state.expected_detected_run_reset = False
        return
    _clear_run_totals(state)


def observe_run_position(
    state: _LootState,
    *,
    stage_index: int,
    game_time_seconds: float | None,
    item_count: int | None,
    items_available: bool = True,
) -> None:
    """Fold the run clock the current item pass carries.

    Two jobs. First, a clock that has gone *backwards* is a new match this
    lane has noticed before the snapshot lane did -- start the run here and
    leave the flag for ``reset``. Second, the first pass that actually shows an
    item decides whether the run is measurable at all.

    What makes a run unmeasurable is not lateness itself but the *block of items
    already held* when the app arrives: ``initial_item_increase_candidates``
    folds those into the baseline in one go, which leaves ``actual`` short by
    that block and ``expected`` short by the same rolls. Neither half is
    salvageable, so the answer is "not measurable" rather than a smaller number.

    Which means an **empty inventory on the first map is measurable however late
    it is**. That function builds a candidate only ``if count > 0``, so with
    nothing held there is nothing absorbed and no rolls have been missed --
    there were none to miss. A player who has opened no chest yet is at the
    start of their loot history whatever the run clock says.

    That empty reading cannot be spent as the decision itself, though: the fast
    item lane refuses to publish an empty inventory at all (``update_fast_items``
    bails on ``if not items``), so the *only* lane that can ever report
    ``item_count == 0`` is the slow snapshot lane, up to ten seconds behind. A
    one-shot decision made off that stale zero would be deciding on data that is
    already out of date the moment it arrives. So an empty first-map reading is
    recorded as retained evidence and the count returns without deciding -- the
    decision itself waits for the first pass that actually shows an item, and is
    then made from the evidence:
    ``observed_empty_first_map or (stage_index == 1 and within_grace)``. The
    stage-one constraint lives inside the retained flag, not beside it, because
    the flag is only ever set while on the first map.

    The clock window is the second arm, for the case the first cannot cover:
    attaching a few seconds in with an item already picked up. That one *does*
    lose a roll, and accepting one item of error inside ten seconds is the
    trade the original rule made deliberately.

    A failed read never decides anything either way. An empty ``items`` from a
    failed read is not an empty inventory, and deciding off one would call an
    unmeasurable run measurable -- the one direction of error this gate exists
    to prevent.
    """
    previous = state.last_game_time_seconds
    if (
        previous is not None
        and game_time_seconds is not None
        and float(game_time_seconds) + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
        < float(previous)
    ):
        _clear_run_totals(state)
        state.expected_detected_run_reset = True

    if game_time_seconds is not None:
        state.last_game_time_seconds = float(game_time_seconds)

    if state.availability_decided or not items_available:
        return

    if item_count is None or int(item_count) <= 0:
        if int(stage_index) == 1 and item_count is not None:
            state.observed_empty_first_map = True
        return

    state.availability_decided = True
    within_grace = (
        game_time_seconds is not None
        and float(game_time_seconds) <= LATE_ATTACH_GRACE_SECONDS
    )
    state.available = bool(
        state.observed_empty_first_map or (int(stage_index) == 1 and within_grace)
    )


def note_empty_inventory_reading(state: _LootState, *, stage_index: int) -> None:
    """Record a successfully-read *empty* inventory as measurability evidence.

    The 1 s item lane cannot deliver this through ``observe_run_position``,
    because ``update_items`` refuses to publish an empty inventory at all --
    crediting one would drop the confirmed baseline and silently discard a
    pending gain. That refusal is right for the baseline and was wrong for this
    gate: it left the 10 s snapshot lane as the *only* lane able to record the
    one fact the gate needs.

    Which lost runs the app had watched from the very first second. At attach
    the first inventory read very often fails, and the next slow read is ten
    seconds away; a player who picks something up inside that window is
    condemned with "app missed the run start" even though every pass in between
    read an empty inventory successfully and threw the answer away. The fast
    lane sees the same emptiness once a second, so it is the lane that closes
    the race.

    ``baseline_is_empty`` is the caller's guard against the transient empty
    dictionary the game exposes mid-rebuild: a player who holds items has a
    non-empty baseline, so an empty read against one is the transient and never
    evidence. Marking an unmeasurable run measurable is the one direction of
    error this gate exists to prevent, and that guard is what keeps this
    addition on the safe side of it.
    """
    if state.availability_decided or int(stage_index) != 1:
        return
    state.observed_empty_first_map = True


def note_map_identity(
    state: _LootState,
    *,
    stage_ptr: int,
    map_seed: int | None,
) -> None:
    """Clear outstanding debts when the map is regenerated.

    The one guard the untimed debt needs, and the only one. A craft the player
    never collected is lying on the floor of a stage that no longer exists, and
    carrying its debt forward would make it swallow a legitimate roll on the new
    map. The interactable counters reset at this boundary anyway.
    """
    identity = (int(stage_ptr or 0), None if map_seed is None else int(map_seed))
    if identity == (0, None):
        return
    if state.map_identity is None:
        state.map_identity = identity
        return
    if identity == state.map_identity:
        return
    state.map_identity = identity
    _clear_map_scoped_state(state)


def _clear_map_scoped_state(state: _LootState) -> None:
    state.tier_debts = []
    state.pending_moai_exclusions = 0
    state.pending_shady_exclusions = []
    state.counter_values = {}
    state.last_counter_read_at = None


def update_interactable_counters(
    state: _LootState,
    counters: dict[str, int],
    *,
    captured_at: float,
) -> None:
    """Fold one read of ``InteractablesStatus`` ``numUsed`` values.

    Only rises matter. A counter that drops is the per-map reset, not a
    negative interaction -- and a label seen for the first time has no previous
    value to have risen from, which is what keeps an attach or a fresh map from
    reading the whole standing count as a burst of increments.
    """
    map_generation_seen = False
    previous_counter_read_at = state.last_counter_read_at
    for label, raw_value in counters.items():
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        previous = state.counter_values.get(label)
        state.counter_values[label] = value
        if previous is None:
            continue
        if value < previous:
            # The counters reset together on map generation, and this is the
            # fast signal for it -- `note_map_identity` cannot see a new map
            # until the 10 s snapshot carries one.
            map_generation_seen = True
            continue
        delta = value - previous
        if delta <= 0:
            continue
        if label == CHEST_COUNTER_LABEL:
            state.map_chest_opens += delta
            continue
        if label == MOAI_COUNTER_LABEL:
            _open_moai_exclusions(
                state,
                delta,
                opened_at=captured_at,
                previous_counter_read_at=previous_counter_read_at,
            )
        elif label == SHADY_GUY_COUNTER_LABEL:
            _open_shady_exclusions(state, delta, opened_at=captured_at)

    if map_generation_seen:
        # Not `_clear_map_scoped_state`: the counter baseline this loop just
        # wrote belongs to the *new* map and is what its first increment will
        # be measured from, so it stays.
        state.tier_debts = []
        state.pending_moai_exclusions = 0
        state.pending_shady_exclusions = []

    state.last_counter_read_at = float(captured_at)
    _expire_shady_exclusions(state, captured_at)


def _open_moai_exclusions(
    state: _LootState,
    count: int,
    *,
    opened_at: float,
    previous_counter_read_at: float | None,
) -> None:
    """Reconcile a Moai delta in either observation order.

    Normally the counter is read before the item gain and opens the untimed
    forward exclusion.  After one or more failed counter reads, however, the
    gain may already have been confirmed and scored.  In that case undo the
    most recent scored gain from the unobserved counter interval instead of
    leaving a stale exclusion for an unrelated future chest item.
    """
    for _ in range(max(0, int(count))):
        if (
            previous_counter_read_at is not None
            and _exclude_recorded_gain_since(
                state,
                after=previous_counter_read_at,
                through=opened_at,
            )
        ):
            continue
        state.pending_moai_exclusions += 1


def _open_shady_exclusions(
    state: _LootState,
    count: int,
    *,
    opened_at: float,
) -> None:
    for _ in range(max(0, int(count))):
        if _exclude_recorded_gain(state, opened_at):
            # The merchant's gain was already counted, which happens whenever a
            # pass reports the gain before the counter read lands. Undo it in
            # place rather than parking a window that has nothing left to catch.
            continue
        state.pending_shady_exclusions.append(
            _PendingShadyExclusion(opened_at=float(opened_at))
        )


def _exclude_recorded_gain(state: _LootState, opened_at: float) -> bool:
    """Retro-remove the most recent counted gain inside the backward window."""
    for index in range(len(state.recent_gains) - 1, -1, -1):
        recorded = state.recent_gains[index]
        if recorded.captured_at > opened_at:
            continue
        if opened_at - recorded.captured_at > SHADY_GUY_BACKWARD_WINDOW_SECONDS:
            break
        _remove_recorded_gain(state, index)
        return True
    return False


def _exclude_recorded_gain_since(
    state: _LootState,
    *,
    after: float,
    through: float,
) -> bool:
    """Undo the newest scored gain inside a counter-source observation gap."""
    for index in range(len(state.recent_gains) - 1, -1, -1):
        recorded = state.recent_gains[index]
        if recorded.captured_at > through:
            continue
        # Counter publication precedes item publication inside one pass, so a
        # gain with the same timestamp as the previous counter sample belongs
        # to the interval after that sample and remains eligible.
        if recorded.captured_at < after:
            break
        _remove_recorded_gain(state, index)
        return True
    return False


def _remove_recorded_gain(state: _LootState, index: int) -> None:
    recorded = state.recent_gains[index]
    state.actual[recorded.tier] = max(0, state.actual[recorded.tier] - 1)
    for tier, contribution in recorded.expected.items():
        state.expected[tier] = max(0.0, state.expected[tier] - contribution)
    del state.recent_gains[index]


def _expire_shady_exclusions(state: _LootState, now: float) -> None:
    state.pending_shady_exclusions = [
        pending
        for pending in state.pending_shady_exclusions
        if now <= pending.opened_at + SHADY_GUY_BACKWARD_WINDOW_SECONDS
    ]


def process_item_losses(
    state: _LootState,
    losses: tuple[ItemLossEvent, ...] | list[ItemLossEvent],
) -> None:
    """Open a tier debt for every confirmed loss that a microwave could explain."""
    for loss in losses or ():
        canonical_name = normalize_item_name_for_rarity(str(loss.item_name))
        if canonical_name in SELF_CONSUMING_ITEM_NAMES:
            continue
        tier = ITEM_RARITY_BY_NAME.get(canonical_name)
        if tier not in state.actual:
            continue
        for _ in range(max(0, int(loss.lost_count))):
            state.tier_debts.append(tier)


def process_item_gains(
    state: _LootState,
    gains: tuple[ItemGainEvent, ...] | list[ItemGainEvent],
) -> None:
    """Fold every confirmed gain as one roll per stacked copy."""
    for gain in gains or ():
        canonical_name = normalize_item_name_for_rarity(str(gain.item_name))
        tier = ITEM_RARITY_BY_NAME.get(canonical_name)
        probabilities = calculate_luck_rarity_probabilities(gain.luck)
        for _ in range(max(0, int(gain.gained_count))):
            state.acquisitions += 1
            if tier not in state.actual:
                # No tier: a Corrupt-chest item, or one a game update added
                # after our metadata table was written. Out of both sides, and
                # out of the exclusion machinery too -- an item we cannot score
                # must not spend a window that a scorable one is waiting for.
                continue
            if _settle_inventory_exclusion(state, gain.captured_at):
                continue
            if tier in state.tier_debts:
                # The craft output, or an ordinary roll standing in for it. The
                # design says not to care which: both carry the consumed tier,
                # so the per-tier totals are the same either way.
                state.tier_debts.remove(tier)
                continue
            if probabilities.get(tier) is None:
                # Luck did not resolve, so this roll has no expectation to
                # accumulate. Counting it in `actual` alone would push the two
                # halves apart by exactly one item, which is the drift the
                # ambiguity rule exists to prevent.
                continue
            _record_roll(
                state,
                tier=tier,
                probabilities=probabilities,
                captured_at=gain.captured_at,
                remember_for_shady=True,
            )


def process_banishes(
    state: _LootState,
    banishes: tuple[str, ...] | list[str],
    *,
    luck: float | None,
    captured_at: float,
) -> None:
    """Count newly persistent item banishes as chest rolls.

    The first successful collection is a baseline: when the app attaches during
    a run, the Luck that produced standing banishes is unknowable. Thereafter the
    game only adds unique names to this run-scoped set, so retaining the union is
    both the delta detector and protection against a transient partial read.

    Weapons and tomes share ``LIVE_BANISHES`` with passive items but have no
    entry in the item-rarity table and are ignored. A banish never enters the
    inventory, so it cannot settle a Moai, Shady Guy, or microwave exclusion and
    cannot become a candidate for Shady Guy's backward correction.
    """
    canonical_names = tuple(
        normalize_item_name_for_rarity(str(name)) for name in (banishes or ())
    )
    if not state.banish_baseline_initialized:
        state.seen_banishes.update(canonical_names)
        state.banish_baseline_initialized = True
        return

    for canonical_name in canonical_names:
        if canonical_name in state.seen_banishes:
            continue
        state.seen_banishes.add(canonical_name)
        tier = ITEM_RARITY_BY_NAME.get(canonical_name)
        if tier not in state.actual:
            continue
        # A persistent item-banish delta is just as conclusive as seeing the
        # first inventory item -- but only after an empty first-map inventory
        # has already proved that no earlier rolls were missed.  Without that
        # retained evidence, a late-attached run must remain unavailable even
        # though this particular banish is observable.
        if not state.availability_decided and state.observed_empty_first_map:
            state.available = True
            state.availability_decided = True
        state.acquisitions += 1
        probabilities = calculate_luck_rarity_probabilities(luck)
        if probabilities.get(tier) is None:
            continue
        _record_roll(
            state,
            tier=tier,
            probabilities=probabilities,
            captured_at=captured_at,
            remember_for_shady=False,
        )


def _record_roll(
    state: _LootState,
    *,
    tier: str,
    probabilities: dict[str, float | None],
    captured_at: float,
    remember_for_shady: bool,
) -> None:
    contribution = {
        candidate: (probabilities.get(candidate) or 0.0) / 100.0
        for candidate in LUCK_RARITY_ORDER
    }
    state.actual[tier] += 1
    for candidate, value in contribution.items():
        state.expected[candidate] += value
    if remember_for_shady:
        state.recent_gains.append(
            _RecordedGain(
                captured_at=float(captured_at),
                tier=tier,
                expected=contribution,
            )
        )


def _settle_inventory_exclusion(state: _LootState, captured_at: float) -> bool:
    """Spend one Moai debt or matching Shady Guy backward window."""
    if state.pending_moai_exclusions > 0:
        state.pending_moai_exclusions -= 1
        return True

    for index, pending in enumerate(state.pending_shady_exclusions):
        in_window = (
            captured_at <= pending.opened_at
            and pending.opened_at - captured_at
            <= SHADY_GUY_BACKWARD_WINDOW_SECONDS
        )
        if in_window:
            del state.pending_shady_exclusions[index]
            return True
    return False


def get_loot_stats(state: _LootState) -> LootStatsSnapshot:
    # An unmeasurable run publishes zeros, not the partial totals it has been
    # accumulating. The gate belongs here rather than in each of the four
    # surfaces the design puts this on: one of them forgetting it would show a
    # number that looks like an answer and is not one. The residual counters
    # below are not gated -- they are a log, and they are true either way.
    measurable = state.available
    return LootStatsSnapshot(
        actual=dict(state.actual) if measurable else _zero_actual(),
        expected=dict(state.expected) if measurable else _zero_expected(),
        acquisitions=state.acquisitions,
        map_chest_opens=state.map_chest_opens,
        available=state.available,
        availability_decided=state.availability_decided,
        outstanding_tier_debts=tuple(state.tier_debts),
    )
