"""Refresh-task wiring: the RefreshCoordinator registrations and demand
predicates that decide which fast-tick work actually runs.

Moved out of ``PlayerStatsMixin`` without behaviour change. These predicates
encode domain rules ("is a KPS consumer active") and only lived in a GUI file
because the timer that drives them does -- the GUI keeps thread ownership and
calls ``ensure_refresh_coordinator(self).tick()`` from
``update_player_stats_timer``, which step 14c moved on to
``app/player_stats_refresh.py``.

That driver is now the only one. Every cadence lives in a task's
``interval_ms``: a second 10 s timer used to run the recording lifecycle from
its own callback body, so collapsing the timers without giving that work a
task of its own would have run it 20x more often. Having its own task is what
later let step 8b move it to 1 s on its own merits, without dragging the 10 s
snapshot along.

``ensure_refresh_coordinator`` and ``overlay_widget_refresh_active`` are plain
functions, not mixin methods: each also has callers outside this module (the
timer driver, and the overlay predicate that is now ``overlay_requires_player_
snapshot`` below). A mixin method reachable only via the shared ``self`` would
show up as a new hidden cross-mixin read the moment its caller and its
definition live in different files -- passing the owner explicitly avoids that
without changing behaviour.

Step 20e moved **four more demand predicates in from
``app/player_stats_refresh.py``** for exactly that reason, and the long comment
above ``in_game_overlay_widget_enabled`` records the measurement: that module is
the top of the app import DAG, so each of those names was a read pointing
against the import arrow. They are the same shape as the pair above now.

The two ``record_player_stats_memory_*`` streak recorders and the reconnect
threshold used to live here for that same reason, but they moved to
``app/player_stats_memory.py`` (joining their game-data siblings) to delete the
``player_stats_memory -> refresh_tasks`` import edge, and that is the point: the
service conversion below needs ``refresh_tasks`` to import
``player_stats_memory``, and the old edge would have closed a cycle. Step 20f
then stopped calling the owner-taking ``record_player_stats_memory_*`` adapters
altogether -- the service holds the memory service directly, so it calls
``record_memory_success``/``record_memory_failure`` on it and the adapter import
is gone from this file.

Step 20f converted the rest -- the six ``_should_refresh_*``/``_refresh_*_task``
pairs and their private helpers -- from ``RefreshTasksMixin`` into the
``RefreshTasks`` service below, the sixth of the seven app-side MRO bases and
the last one that had no caller outside this module. Every dependency is an
injected zero-argument callable for the reason ``player_stats_memory.py``'s
header spells out: a mixin method resolves ``self`` late, on every call, and a
constructor argument resolves it once. Step 20 shipped that difference as a bug
twice, so nothing here is captured -- only re-resolved.

**The injected attribute names are deliberately distinct from the other two
services'.** ``PlayerStatsMemory`` and ``VodCapture`` both spell a live-stats-tab
predicate, and when the memory conversion reused ``VodCapture``'s
``_is_live_stats_tab_active`` the cluster scanner reported two services' private
callables as one piece of unowned state. ``_tab_active``/``_twitch_active``/
``_tracker`` and friends below are checked against both.

**What this service owns: one field, decided by counting.**
``_player_stats_refresh_status_text`` had every reader and writer inside this
file -- nothing in ``src/`` else touches it -- so it moved in, exactly as the
two reconnect streaks moved into ``PlayerStatsMemory``. It keeps its old
spelling and is initialised to the value the ``getattr`` default used to
supply, so the pre-first-write read is unchanged. (``_last_fast_kps_game_time_seconds``
moved in the same way and has since been deleted: the game-time KPS rework
keeps its second cursor next to the history it indexes, in ``_CombatState``.)
``_refresh_coordinator`` does **not** move: it stays behind
``ensure_refresh_coordinator`` because the coordinator owns it and a test reads
``app._refresh_coordinator.diagnostics()``.

**The seven ``getattr``/``callable`` demand guards are gone, and dropping them
changed nothing.** Each guarded site kept its ``try``/``except`` and the injected
callable raises ``AttributeError`` on an owner missing the predicate -- which
takes the same branch the ``callable()`` fallthrough took. The two direct,
unguarded call sites (``_should_refresh_expected_chest_inputs`` and
``_should_refresh_chaos_tome``) still propagate, exactly as before.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

from app import config
from app.player_stats_memory import player_stats_memory
from app.read_sources import (
    CHARACTER_PASSIVE_READING,
    CHAOS_TRACKING_STATE,
    EXPECTED_CHEST_INPUTS,
    KPS_GROUP_SPAN_LIMIT_SECONDS,
    LIVE_BANISHES,
    LUCK,
    MOB_KILLS,
    PASSIVE_ITEMS,
    POWERUP_TRACKING_SNAPSHOT,
    SIZE,
    STAGE_TIMER_CONTEXT,
    OWNER_STATS,
    PLAYER_STATS_CLIENT,
    RUN_TIMER,
    SHRINE_TRACKING_STATE,
    read_memory_source,
    source_health_recorded,
)
from app.refresh_coordinator import RefreshCoordinator, RefreshTask, RefreshTickContext
from app.run_lifecycle import run_lifecycle
from core.tracker.snapshots import PowerupMapContext
from core.tracker.live_run import build_permanent_source_recovery
from core import run_summary
from app.player_stats_view import player_stats_view
from app.snapshot_selection import player_stats_snapshot_is_pinned
from app.vod_capture import vod_capture
from projections import formatting

if TYPE_CHECKING:
    from infra.memory.player_stats_client import PlayerStatsClient


# The two refresh cadences, moved here from gui_styles.py in step 17a: this
# module is what turns them into RefreshTask intervals, and is the only consumer
# of both.
PLAYER_STATS_REFRESH_MS = 10_000
# The recording lifecycle used to inherit the 10 s snapshot cadence above; it is
# its own decision (step 8b) because it decides run boundaries, and a boundary
# noticed a whole interval late mis-attributes that interval's kills to the wrong
# stage. Matches CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS, whose state it reads.
RECORDING_LIFECYCLE_REFRESH_MS = 1_000
# Its own decision, not an inherited interval, for the same reason
# RECORDING_LIFECYCLE_REFRESH_MS is: `tracked_items` was the only state in the
# app whose latency was a full PLAYER_STATS_REFRESH_MS *plus* a confirmation
# tick, because `process_item_deltas` credits a raised count only on the next
# read that agrees -- so 10--20 s end to end for the OBS overlay, Session Stats
# and the Twitch commands. Not FAST_TRACKER_INTERVAL_MS (500 ms, user
# configurable down to 100): the item dictionary is a per-entry walk, and 1 s
# buys effectively all of the latency back at a fifth of that read cost.
PASSIVE_ITEMS_REFRESH_MS = 1_000
PERMANENT_SOURCE_RECOVERY_RETRY_SECONDS = 5.0


def _permanent_modifier_key(modifier: Any) -> tuple[int, int, int, float]:
    return (
        int(getattr(modifier, "object_ptr", 0) or 0),
        int(getattr(modifier, "stat_id", -1)),
        int(getattr(modifier, "modify_type", -1)),
        float(getattr(modifier, "value", 0.0)),
    )


@dataclass(frozen=True)
class _PermanentSourceSample:
    reading: Any
    chaos_level: int | None
    permanent_modifiers: dict[int, tuple[Any, ...]]
    key: tuple[Any, ...]

    @classmethod
    def capture(cls, reading, chaos_level, permanent_modifiers):
        frozen_modifiers = {
            int(stat_id): tuple(modifiers)
            for stat_id, modifiers in (permanent_modifiers or {}).items()
        }
        dice_modifiers = tuple(
            _permanent_modifier_key(modifier)
            for modifier in tuple(getattr(reading, "permanent_modifiers", ()))
        )
        modifier_version = dice_modifiers or tuple(
            _permanent_modifier_key(modifier)
            for _stat_id, modifiers in sorted(frozen_modifiers.items())
            for modifier in modifiers
        )
        identity = (
            int(getattr(reading, "character_id", -1)),
            int(getattr(reading, "passive_id", -1)),
            str(getattr(reading, "runtime_class", "")),
            int(getattr(reading, "passive_object_ptr", 0) or 0),
        )
        key = (
            identity,
            int(getattr(reading, "level", 0) or 0),
            int(getattr(reading, "gamba_current_level", 0) or 0),
            None if chaos_level is None else int(chaos_level),
            modifier_version,
        )
        return cls(
            reading=reading,
            chaos_level=None if chaos_level is None else int(chaos_level),
            permanent_modifiers=frozen_modifiers,
            key=key,
        )


class _PermanentSourceRecoveryJob:
    """One daemon calculation polled by the GUI-owned refresh task."""

    def __init__(
        self,
        *,
        tracker,
        token,
        sample: _PermanentSourceSample,
        reserved_modifier_ptrs: frozenset[int],
        base=None,
    ) -> None:
        self.tracker = tracker
        self.token = token
        self.sample = sample
        self.result = None
        self.error: Exception | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(reserved_modifier_ptrs, base),
            name="DicePassiveRecovery",
            daemon=True,
        )
        self._thread.start()

    def _run(self, reserved_modifier_ptrs, base) -> None:
        try:
            self.result = build_permanent_source_recovery(
                self.sample.reading,
                chaos_level=self.sample.chaos_level,
                permanent_modifiers=self.sample.permanent_modifiers,
                reserved_modifier_ptrs=reserved_modifier_ptrs,
                base=base,
            )
        except Exception as exc:
            self.error = exc
        finally:
            self._done.set()

    def done(self) -> bool:
        return self._done.is_set()


def ensure_refresh_coordinator(owner) -> RefreshCoordinator:
    # The AppCoordinator owns this when there is one (step 11). There is not one
    # on an app double built without __init__, which keeps the old attribute.
    app_coordinator = getattr(owner, "coordinator", None)
    if app_coordinator is not None and app_coordinator.refresh_coordinator is not None:
        return app_coordinator.refresh_coordinator
    coordinator = getattr(owner, "_refresh_coordinator", None)
    if coordinator is not None:
        return coordinator
    coordinator = RefreshCoordinator()
    # The tasks are the **service's** bound methods now, not ``owner._refresh_*``.
    # Resolved once here because a RefreshTask holds the callable it was given;
    # the service itself re-resolves every collaborator per call, so nothing is
    # frozen by binding it here.
    service = refresh_tasks(owner)
    # The lifecycle probe must run before every demand predicate and must share
    # the same pass as the tasks that consume its state. Its own one-second
    # cache controls the physical read cadence; interval 1 means only "call the
    # cache on every driver tick", matching the pre-step-28 driver behaviour.
    coordinator.register(
        RefreshTask(
            task_id="run_lifecycle_probe",
            interval_ms=1,
            required=lambda: True,
            run=service._refresh_run_lifecycle_probe_task,
        )
    )
    # Registered immediately after the lifecycle probe, and deliberately before
    # the full snapshot: ``tick`` runs tasks in registration order, and
    # ``full_player_snapshot`` below reads the status text this task writes.
    # Before the timers were collapsed this ordering was implicit -- the 10 s
    # callback ran the recording sync and then called ``tick``.
    coordinator.register(
        RefreshTask(
            task_id="recording_lifecycle",
            # 1 s, not the 10 s snapshot cadence this used to inherit. Seed,
            # stage_index and the run timer are what attribute kills to a stage,
            # so a transition noticed late files up to a full interval of kills
            # made on one map against the next -- corruption of recorded data,
            # not a lagging label. Only safe with step 8b's stage_index guard in
            # place: the 10 s interval was accidentally acting as a settle delay
            # over the loading screen, and the guard replaces it with a
            # deliberate one ("index unreadable -> do not decide").
            interval_ms=RECORDING_LIFECYCLE_REFRESH_MS,
            # Unconditional: this is what auto-stops a recording once the game is
            # gone, so it must keep running when every consumer has lost demand.
            required=lambda: True,
            run=service._refresh_recording_lifecycle_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="full_player_snapshot",
            interval_ms=PLAYER_STATS_REFRESH_MS,
            required=service._should_refresh_full_player_snapshot,
            # ``refresh_live_player_stats_now`` stays ``owner``-resolved: it is
            # genuine ``MegabonkApp`` surface (``gui_layout``/``gui_twitch`` call
            # it), the same finding the ``player_stats_client`` properties got.
            # The status text it passes is the service's field now, initialised
            # to the string this ``getattr`` used to default to.
            run=lambda context: owner.refresh_live_player_stats_now(
                status_text=service._player_stats_refresh_status_text,
                context=context,
            ),
        )
    )
    # Registered after the full snapshot, so on a pass where both are due the
    # snapshot resolves PASSIVE_ITEMS first and this task reads it from the
    # pass cache. Either order shares the one physical read -- registration
    # order only decides which task pays for it.
    coordinator.register(
        RefreshTask(
            task_id="passive_items",
            interval_ms=PASSIVE_ITEMS_REFRESH_MS,
            # Everything the full snapshot demands, plus the Luck widget, which
            # reads this task's `LUCK` source now instead of the snapshot's
            # per-stat walk. Strictly wider than the snapshot's predicate, so
            # the no-gap property the two shared still holds.
            required=service._should_refresh_passive_items,
            run=service._refresh_passive_items_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="combat_metrics",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=service._should_refresh_fast_kps,
            run=service._refresh_combat_metrics_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="powerups",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=service._should_refresh_powerup_tracker,
            run=service._refresh_powerups_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="expected_chest_inputs",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=service._should_refresh_expected_chest_inputs,
            run=service._refresh_expected_chest_inputs_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="event_timer",
            interval_ms=1_000,
            required=service._should_refresh_fast_stage_timer,
            run=service._refresh_event_timer_task,
        )
    )
    coordinator.register(
        RefreshTask(
            # Reserve exact ShrineLogs pointers before the shared permanent
            # modifier lane runs on ticks where both tasks are due.
            task_id="charge_shrines",
            interval_ms=PASSIVE_ITEMS_REFRESH_MS,
            required=service._should_refresh_charge_shrines,
            run=service._refresh_charge_shrines_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="chaos_tome",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=service._should_refresh_chaos_tome,
            run=service._refresh_chaos_tome_task,
        )
    )
    if app_coordinator is not None:
        app_coordinator.refresh_coordinator = coordinator
    else:
        owner._refresh_coordinator = coordinator
    return coordinator


def overlay_widget_refresh_active(owner, widget_id: str) -> bool:
    server = getattr(owner, "overlay_server", None)
    if server is None or not bool(getattr(server, "is_running", False)):
        return False
    overlay = getattr(config, "OVERLAY", {}) or {}
    return any(
        isinstance(widget, dict)
        and str(widget.get("id") or "") == widget_id
        and bool(widget.get("enabled", False))
        for widget in overlay.get("widgets", ()) or ()
    )


# The four predicates below came from ``PlayerStatsRefreshMixin`` in step 20e,
# and the reason is the same one that moved the two memory streak recorders in
# ``1a323e4``: they were filed in the module *above* their only consumer.
#
# ``player_stats_refresh_required`` had **zero** callers in the module that
# defined it and exactly one here (``_should_refresh_full_player_snapshot``).
# ``in_game_overlay_widget_enabled`` was a ``@staticmethod`` with no ``self`` at
# all -- pure ``config`` -- used three times there and **six** times here. The
# other two exist only to feed the first, and one of them is built out of
# ``overlay_widget_refresh_active`` directly above, which has lived here all
# along; the docstring at the top of this file already named
# ``_overlay_requires_player_snapshot`` as the outside caller justifying that
# function's shape.
#
# This is not tidying. ``app/player_stats_refresh.py`` is the top of the app
# import DAG -- it imports this module, ``vod_capture`` and ``run_lifecycle``,
# and nothing in ``app/`` imports it. So every one of these names was a
# ``refresh_tasks -> player_stats_refresh`` read against the import arrow, and
# converting either mixin while they stayed put would have had to close that
# loop through a module-level import. Moving them *down* deletes both state
# edges by construction and leaves exactly one edge between the two modules:
# ``refresh_live_player_stats_now``, a genuine one-operation command that
# ``vod_capture`` already receives as an injected callable.
#
# Module-level ``owner``-taking functions, not methods, for the reason this
# file's docstring gives for its existing pair: a mixin method reachable only
# through the shared ``self`` becomes a new hidden cross-mixin read the moment
# its caller and its definition sit in different files.


def in_game_overlay_widget_enabled(widget_id: str) -> bool:
    # No ``owner`` parameter: this never read ``self``. It was a ``@staticmethod``
    # on a mixin, which is a free function wearing a class for company.
    overlay = getattr(config, "IN_GAME_OVERLAY", {}) or {}
    if not overlay.get("enabled", False):
        return False
    widgets = overlay.get("widgets", {}) or {}
    if not isinstance(widgets, dict):
        return False
    widget_cfg = widgets.get(widget_id, {})
    return isinstance(widget_cfg, dict) and bool(widget_cfg.get("enabled", False))


def in_game_overlay_requires_player_stats_refresh() -> bool:
    # `luck_rarity` is **not** here any more. It demanded the 10 s full snapshot
    # only because Luck was reachable nowhere else; it now rides the narrow
    # `LUCK` source on the `passive_items` task, and leaving it here would keep
    # paying for a full per-stat walk it no longer reads from.
    return (
        in_game_overlay_widget_enabled("stats")
        or in_game_overlay_widget_enabled("event_timer")
        or in_game_overlay_widget_enabled("build_progression")
    )


def in_game_overlay_luck_expected_frame_active() -> bool:
    """True when the in-game Luck Rarity widget is showing its Expected Frame.

    The frame reads the key-proc expectation the ``expected_chest_inputs`` task
    produces (``track_expected_key_procs`` -> ``projection.loot_stats``), so an
    enabled-and-showing frame is a *recipient* of that task -- exactly the way
    the Luck probabilities beside it are recipients of ``passive_items``. Gated
    on ``show_expected`` because with the frame hidden the widget renders from
    Luck alone and this task's output goes unread.
    """
    if not in_game_overlay_widget_enabled("luck_rarity"):
        return False
    widgets = (getattr(config, "IN_GAME_OVERLAY", {}) or {}).get("widgets", {}) or {}
    widget_cfg = widgets.get("luck_rarity", {}) if isinstance(widgets, dict) else {}
    return isinstance(widget_cfg, dict) and bool(widget_cfg.get("show_expected", False))


def overlay_requires_player_snapshot(owner) -> bool:
    return any(
        overlay_widget_refresh_active(owner, widget_id)
        for widget_id in ("stage_summary", "tracked_items", "stats", "banishes", "build_progression")
    )


def player_stats_refresh_required(owner) -> bool:
    return not run_lifecycle(owner).completed_run and (
        owner._is_live_stats_tab_active()
        or owner.player_stats_vod_recorder.is_recording
        or vod_capture(owner).is_recording_armed()
        or bool(getattr(config, "AUTO_START_RECORDING", False))
        or overlay_requires_player_snapshot(owner)
        or in_game_overlay_requires_player_stats_refresh()
        or owner._is_twitch_bot_active()
    )


class RefreshTasks:
    """The fast-tick task bodies and their demand predicates, constructible
    without Qt or ``MegabonkApp``.

    Thirteen collaborators, all callables. ``_memory``/``_lifecycle``/``_view``/
    ``_capture`` return the sibling services; ``_widget_refresh_active`` is the
    module function above with its ``owner`` already bound; the rest are the
    owner's tracker, predicates and the three overlay commands -- one per
    overlay surface, plus the session tracked-items refresh.
    """

    def __init__(
        self,
        *,
        memory: Callable[[], Any],
        lifecycle: Callable[[], Any],
        view: Callable[[], Any],
        capture: Callable[[], Any],
        tracker: Callable[[], Any],
        vod_recorder: Callable[[], Any],
        tab_active: Callable[[], bool],
        twitch_active: Callable[[], bool],
        pinned: Callable[[], bool],
        widget_refresh_active: Callable[[str], bool],
        sync_overlay_state: Callable[[], None],
        sync_in_game_kps: Callable[[], None],
        refresh_session_tracked_items: Callable[[], None],
        refresh_required: Callable[[], bool],
        build_progression_service: Callable[[], Any] | None = None,
        permanent_source_recovery_job_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._memory = memory
        self._lifecycle = lifecycle
        self._view = view
        self._capture = capture
        self._tracker = tracker
        self._vod_recorder = vod_recorder
        self._tab_active = tab_active
        self._twitch_active = twitch_active
        self._pinned = pinned
        self._widget_refresh_active = widget_refresh_active
        self._sync_overlay_state = sync_overlay_state
        self._sync_in_game_kps = sync_in_game_kps
        self._refresh_session_tracked_items = refresh_session_tracked_items
        self._refresh_required = refresh_required
        self._build_progression_service = build_progression_service or (lambda: None)
        self._permanent_source_recovery_job_factory = (
            permanent_source_recovery_job_factory or _PermanentSourceRecoveryJob
        )

        # Owned state. Initialised to the value the ``getattr`` default on the
        # app used to supply, so the read before the first write is unchanged.
        # Nothing outside this file ever touched this name.
        self._player_stats_refresh_status_text = "Live player stats"
        self._permanent_source_recovery_job = None
        self._permanent_source_recovery_latest_sample = None
        self._permanent_source_recovery_retry_at = 0.0

    def _refresh_run_lifecycle_probe_task(self, context: RefreshTickContext) -> bool:
        """Refresh lifecycle state first, inside the shared read pass.

        Demand predicates and every later task consume the state this probe
        publishes. ``RunLifecycle.refresh`` retains the authoritative one-second
        memory-read cache, so running this task on every driver tick changes no
        read cadence.
        """
        self._lifecycle().refresh(context)
        return True

    def _refresh_recording_lifecycle_task(self, context: RefreshTickContext) -> bool:
        """Recording auto-start/auto-stop/pause handling, formerly the body of the
        10 s Qt timer callback.

        It is a task rather than a side effect of the surviving 500 ms driver so
        that it owns its own cadence. Step 8 kept that at the inherited 10 s to
        stay a pure refactor; step 8b then moved it to 1 s on its own merits,
        which is what having a task made possible.
        """
        recorder = self._vod_recorder()
        if (
            self._lifecycle().completed_run
            and recorder is not None
            and recorder.is_recording
        ):
            # The lifecycle task runs before the normal shrine task. Once the
            # run is complete that task is no longer demanded, so fold the
            # terminal counters into the tracker now, while the recorder is
            # still open. The task owns its failure handling; a stale final
            # sample must never prevent the recording from closing.
            self._refresh_charge_shrines_task(context)
        recording_state_action = self._capture().sync_run_state(context)
        self._player_stats_refresh_status_text = (
            "Live player stats"
            if recording_state_action != "stopped"
            else "Live player stats (recording auto-stopped after run end)"
        )
        return True

    def _fast_task_client(self, context: RefreshTickContext) -> PlayerStatsClient:
        return context.get_or_create(
            PLAYER_STATS_CLIENT, self._memory()._get_player_stats_client
        )

    def _fast_task_owner_stats(self, context: RefreshTickContext) -> int:
        return context.get_or_create(
            OWNER_STATS,
            lambda: self._fast_task_client(context).resolve_owner_stats(),
        )

    def _mark_fast_feature_available(self, feature: str) -> None:
        marker = getattr(self._tracker(), "mark_feature_available", None)
        if callable(marker):
            try:
                marker(feature)
            except Exception:
                pass

    def _mark_fast_feature_failed(self, feature: str, error: Exception | str) -> None:
        marker = getattr(self._tracker(), "mark_feature_failed", None)
        if callable(marker):
            try:
                marker(feature, error)
            except Exception:
                pass

    def _refresh_powerups_task(self, context: RefreshTickContext) -> bool:
        try:
            client = self._fast_task_client(context)
            owner_stats = self._fast_task_owner_stats(context)
            snapshot = read_memory_source(
                context,
                POWERUP_TRACKING_SNAPSHOT,
                lambda: client.get_powerup_tracking_snapshot(owner_stats),
            )
            self._memory().record_memory_success()
            accepted = self._tracker().update_powerups(snapshot)
            # The tracker always updates; only the *repaint* is gated. The
            # Powerups card is painted from the snapshot's stats by
            # `display_player_stats`, and `refresh_powerups_card` repaints it
            # from the live tracker -- so unguarded it is the third writer of
            # a panel a pinned scrub owns, alongside the two stage-summary
            # writes. Found by counting the writers rather than by the report.
            if not self._pinned():
                self._view().refresh_powerups_card()
            return accepted is not False
        except Exception as exc:
            self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("powerups", exc)
            if not self._pinned():
                self._view().refresh_powerups_card()
            return False

    def _refresh_expected_chest_inputs_task(self, context: RefreshTickContext) -> bool:
        try:
            client = self._fast_task_client(context)
            owner_stats = self._fast_task_owner_stats(context)
            chests_bought, keys_count = read_memory_source(
                context,
                EXPECTED_CHEST_INPUTS,
                lambda: client.get_expected_chest_inputs(owner_stats),
            )
            self._memory().record_memory_success()
            self._tracker().track_expected_key_procs(chests_bought, keys_count)
            self._mark_fast_feature_available("expected_chests")
            return True
        except Exception as exc:
            self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("expected_chests", exc)
            return False

    def _publish_fast_luck(self, context: RefreshTickContext) -> None:
        """Luck, from the same pass as the inventory.

        Its own narrow ``LUCK`` source rather than ``PLAYER_STATS``, which
        resolves a full per-stat walk this pass has no other use for.

        Failures are swallowed into a cleared reading, exactly as this task
        already swallows a ``PASSIVE_ITEMS`` failure: no health is recorded
        here, because ``get_luck`` reports an unreadable stat as ``None``
        rather than raising, matching what the full snapshot puts in
        ``PlayerStatValue.value`` for the same failure.
        """
        try:
            client = self._fast_task_client(context)
            owner_stats = self._fast_task_owner_stats(context)
            luck = read_memory_source(
                context, LUCK, lambda: client.get_luck(owner_stats)
            )
        except Exception:
            luck = None
        update_fast_luck = getattr(self._tracker(), "update_fast_luck", None)
        if callable(update_fast_luck):
            update_fast_luck(luck)

    def _publish_fast_banishes(self, context: RefreshTickContext) -> None:
        """Persistent chest-item banishes, read with the Luck that scores them.

        The full snapshot remains the health owner for ``LIVE_BANISHES``. This
        second consumer only reduces detection latency from ten seconds to one;
        the pass cache still permits at most one physical read when both tasks
        are due. A failed read publishes nothing, preserving the last successful
        delta baseline rather than turning failure into an empty set.
        """
        try:
            client = self._fast_task_client(context)
            banishes = read_memory_source(
                context, LIVE_BANISHES, client.get_live_banishes
            )
        except Exception:
            return
        update_banishes = getattr(self._tracker(), "update_banishes", None)
        if callable(update_banishes):
            update_banishes(tuple(banishes or ()))

    def _publish_fast_size(self, context: RefreshTickContext) -> None:
        service = self._build_progression_service()
        if not service or not getattr(service, "has_cap_demand", lambda: False)():
            return
        try:
            client = self._fast_task_client(context)
            owner_stats = self._fast_task_owner_stats(context)
            size = read_memory_source(
                context, SIZE, lambda: client.get_size(owner_stats)
            )
        except Exception:
            size = None
        update_fast_size = getattr(self._tracker(), "update_fast_size", None)
        if callable(update_fast_size):
            update_fast_size(size)

    def _publish_item_cooldowns(self, context: RefreshTickContext) -> None:
        """Timed-item cooldowns, from the same pass as the inventory.

        Costs almost nothing on top of that pass: the dictionary walk is
        already paid for and memoised, so this is two float reads for the item
        plus one for ``MyTime.time``, whose static-field chain is cached --
        ~12 us against the ~0.004 ms measured per ``ReadProcessMemory``. That
        is why there is no demand-gating predicate for it and
        ``_should_refresh_passive_items`` is left alone: the cost this feature
        adds is below the threshold at which gating pays for itself.

        **Swallows, and records no health**, matching ``_publish_fast_luck``
        and ``_publish_fast_map_activity`` above. ``PASSIVE_ITEMS`` keeps a
        single health owner; without this a torn cooldown float would be
        reported as an inventory failure and would mark the whole feature
        degraded. Cost is not what demand-gating protects -- failure surface is
        -- and this is how that half is paid instead.

        A failure clears the reading rather than leaving the previous one in
        place, so the TTL retires it on schedule instead of a stale countdown
        outliving the pass that produced it.
        """
        try:
            client = self._fast_task_client(context)
            owner_stats = self._fast_task_owner_stats(context)
            snapshot = client.get_item_cooldowns(owner_stats)
        except Exception:
            snapshot = None
        publish = getattr(self._tracker(), "update_item_cooldowns", None)
        if callable(publish):
            publish(snapshot)

    def _publish_fast_map_activity(self, context: RefreshTickContext) -> None:
        """The interactable counters, from the same pass as the inventory.

        Costs no extra read on a pass where the 10 s snapshot also runs:
        ``get_map_activity_values`` already walks the whole dictionary and
        returns every key, and both consumers resolve the one
        ``MAP_ACTIVITY_VALUES`` key, so the pass cache shares the single
        physical walk.

        **Error policy, decided:** the full snapshot stays the health owner for
        this source. It records health in its own task body rather than through
        ``read_source`` callbacks, so a second consumer does not steal that
        accounting -- whichever task resolves the key first performs the
        physical read, and the snapshot still records its own success or failure
        from the cached result. This task swallows, the way it already does for
        ``PASSIVE_ITEMS``.

        Reading it every second also fixes ``PowerupMapContext`` being absent
        for the first ten seconds of every run: the snapshot publishes it after
        ``update``, which is the call that blanks it on run start, so until the
        *second* snapshot there was no map context at all.
        """
        try:
            activity_values = self._memory().read_map_activity_values(context) or {}
        except Exception:
            return
        if not activity_values:
            # Not an error here. An empty dictionary is legitimate outside a run
            # and means "the chain did not resolve" during one -- and the full
            # snapshot is the consumer that owns that distinction and raises on
            # it. Publishing an empty context would replace a good reading with
            # a blank one.
            return
        # `current` (numUsed), not `max`: the loot tracker's exclusions key on a
        # counter *moving*, which is the only observable the game gives for a
        # Moai pick or a completed merchant trade. Published before the item
        # body below, so an increment is folded ahead of the gain it excludes.
        update_loot_interactables = getattr(
            self._tracker(), "update_loot_interactables", None
        )
        if callable(update_loot_interactables):
            update_loot_interactables(
                {label: int(value.current) for label, value in activity_values.items()}
            )
        update_powerup_map_context = getattr(
            self._tracker(), "update_powerup_map_context", None
        )
        if not callable(update_powerup_map_context):
            return
        update_powerup_map_context(
            PowerupMapContext.from_activity_max(
                {label: int(value.max) for label, value in activity_values.items()},
                # `time.monotonic()`, not `context.started_at`: the freshness
                # window this is measured against is read on the tracker's own
                # clock, and the two are the same clock only by convention. The
                # 10 s snapshot stamps this the same way.
                captured_at=time.monotonic(),
            )
        )

    def _refresh_passive_items_task(self, context: RefreshTickContext) -> bool:
        """Read the whole loot sample -- items, banishes, counters and Luck --
        in one pass.

        Resolved through the named ``PASSIVE_ITEMS`` source, which is the point
        of step 28's composable reads: on a pass where the full snapshot is also
        due, both consumers share **one** physical walk of the item dictionary.
        Nothing is removed from ``refresh_now`` -- it keeps reading and
        publishing items exactly as before, so recordings, VOD capture and the
        Stage Summary inputs are unchanged. This adds a second consumer of an
        existing source; it does not split the existing path. The same holds for
        ``MAP_ACTIVITY_VALUES``.

        The sources are read here rather than by separate tasks because a key
        resolves **once** per ``RefreshTickContext``: items, banishes, counters
        and Luck therefore carry one timestamp and are coherent by construction.
        The "did the counter move before or after this gain" question and the
        "which Luck applied to this roll" question stop existing rather than
        being solved by matching two buffers.

        The other two are published before the item body so that a failing
        inventory read -- the one source here that raises -- does not also
        starve them.
        """
        self._publish_fast_luck(context)
        self._publish_fast_banishes(context)
        self._publish_fast_size(context)
        self._publish_fast_map_activity(context)
        self._publish_item_cooldowns(context)
        try:
            client = self._fast_task_client(context)
            owner_stats = self._fast_task_owner_stats(context)
            items = read_memory_source(
                context,
                PASSIVE_ITEMS,
                lambda: client.get_passive_items(owner_stats),
            )
            # `update_items` owns the transient-empty guard and the run-boundary
            # guard; a skipped pass is not a failure.
            applied = self._tracker().update_items(items)
            # Live Stats renders this same inventory, and it was the one
            # remaining surface still waiting for the 10 s payload -- the
            # tracked-item *rows* got fast the moment the deltas did, but the
            # items panel beside them is painted from `display_player_stats`.
            # Repainting it here costs no read: the task already holds exactly
            # what the panel renders.
            #
            # `not pinned`: the user may have scrubbed the timeline, and these
            # are live values. That is the guard the two fast stage-summary
            # writes were missing in `9c59abd`, which is what "the stage summary
            # flickers" was. Only `applied` is repainted -- a skipped or failed
            # read leaves the last good reading on screen rather than blanking
            # the panel.
            if applied and self._tab_active() and not self._pinned():
                self._view().set_items(items)
            if applied and self._tab_active():
                self._refresh_build_progression_view()
            if applied:
                # Session Stats is one of the three surfaces this whole change
                # exists for, and its panel was repainted only by `refresh_now`
                # on the 10 s path. Unconditional, matching that caller: the
                # panel lives on a different tab from Live Stats, so the Live
                # Stats guards above are not the right gate, and the writer
                # itself no-ops when the label has not been built.
                self._refresh_session_tracked_items()
                # Publish for the widget *this task* changed. Gating the
                # overlay republish on `kps`/`stage_summary` -- the only two
                # conditions the fast tasks had -- meant an overlay running the
                # Tracked Items widget with Stage Summary switched off fell back
                # to the 10 s cadence, which is exactly the surface the fast
                # lane was built for. `stage_summary` is enabled by default, so
                # this was covered by accident rather than by design.
                if (
                    self._widget_refresh_active("tracked_items")
                    or self._widget_refresh_active("build_progression")
                ):
                    self._sync_overlay_state()
            return True
        except Exception:
            # Deliberately no `record_memory_success`/`record_memory_failure`.
            # Memory health and the reconnect streak for PASSIVE_ITEMS belong to
            # the full snapshot, which reads the same source and still runs. A
            # second consumer recording its own successes would reset a streak
            # the primary path is accumulating, and recording its own failures
            # would advance that streak twice for what may be one physical read
            # (step_28_plan.md section 12.5: enrolling a site must not change
            # error policy).
            return False

    def _combat_group_span_seconds(self, context: RefreshTickContext) -> float | None:
        """The measured coherence window across the combat group's members.

        ``max(finished_at) - min(started_at)`` over RUN_TIMER and MOB_KILLS
        (step_28_plan.md section 12.4). ``None`` when either member has no
        metadata, which after the single-resolution-path fix can only mean the
        member was never resolved in this pass.
        """
        run_timer_meta = context.metadata_for(RUN_TIMER)
        mob_kills_meta = context.metadata_for(MOB_KILLS)
        if run_timer_meta is None or mob_kills_meta is None:
            return None
        return max(run_timer_meta.finished_at, mob_kills_meta.finished_at) - min(
            run_timer_meta.started_at, mob_kills_meta.started_at
        )

    def _refresh_combat_metrics_task(self, context: RefreshTickContext) -> bool:
        try:
            client = self._fast_task_client(context)
            run_timer_seconds = read_memory_source(
                context,
                RUN_TIMER,
                client.get_run_timer,
                on_success=self._memory().record_memory_success,
                on_failure=self._memory().record_memory_failure,
            )
            # Every successful timer read publishes the run clock, before
            # anything kills-related can fail. This is the publication path
            # section 12.2 requires: the Stage Summary clock advances from the
            # first pass of a run instead of waiting for the first kill.
            self._tracker().update_fast_run_timer(run_timer_seconds)
            if self._tab_active():
                self._refresh_build_progression_view()
            # The Live Stats run clock, painted from the same read and *before*
            # anything kills-related can fail. Its neighbours in that card were
            # already on this task -- the mob-kills line and the Stage Summary
            # rows below -- while the clock itself waited for the 10 s payload,
            # so one card held two clocks advancing at different rates.
            #
            # Placed here rather than beside those two deliberately, and for the
            # reason step 28c moved the tracker's own fast clock off the kill
            # sample: a failed kills read must not freeze a timer that was read
            # successfully. Withholding the KPS projection below returns early,
            # and this write has already happened by then.
            if self._tab_active() and not self._pinned():
                self._view().set_in_game_time_text(
                    formatting.format_in_game_time(run_timer_seconds)
                )
            # Per-source failure isolation -- the rule this step exists for
            # (plan section 5, "Failure") -- is achieved by *publication
            # order*, not by a second `except` around this read. The timer was
            # already published above, so a raise here unwinds to the task's
            # outer handler with the timer's consumers already served: only the
            # combat/KPS projection is withheld. An inner `try` here would be
            # unreachable-by-observation code, and tamper-testing showed
            # exactly that -- deleting it changed no behaviour and failed no
            # test.
            mob_kills = read_memory_source(
                context,
                MOB_KILLS,
                client.get_killed_mobs,
                on_success=self._memory().record_memory_success,
                on_failure=self._memory().record_memory_failure,
            )
            span_seconds = self._combat_group_span_seconds(context)
            if span_seconds is not None and span_seconds > KPS_GROUP_SPAN_LIMIT_SECONDS:
                # Both facts stay published and reusable; only the pair-derived
                # projection is withheld, because dividing a kill delta by a
                # stretched interval produces a wrong number rather than a
                # stale one (plan section 12.4, last paragraph). The timer has
                # already moved the fast clock above.
                self._mark_fast_feature_failed(
                    "combat",
                    f"combat source span exceeded {KPS_GROUP_SPAN_LIMIT_SECONDS:.3f}s",
                )
                return False
            self._tracker().track_kills(run_timer_seconds, mob_kills)
            self._mark_fast_feature_available("combat")
            # First consumer served, and deliberately ahead of the panel paints
            # below: `track_kills` has just published the instant KPS, and the
            # in-game overlay was reading it off its own 500 ms timer, whose
            # phase is unrelated to this pass's. That second timer was worth up
            # to a whole extra tick of lag against the game's on-screen counter,
            # and it drifted. Gated exactly like the OBS sync below -- the
            # component re-checks the config itself, but a disabled overlay
            # should not cost a cross-component call every pass.
            if in_game_overlay_widget_enabled("kps"):
                self._sync_in_game_kps()
            # `not pinned`: the user may have scrubbed the timeline to an
            # earlier snapshot, and these two writes are live values. The slow
            # refresh tick has honoured the pin since `d7d1350`; these were
            # created by `9c59abd` in the same window and never got the guard,
            # so at this task's fast cadence they repainted live rows over the
            # scrubbed reading about once a second. That was the "stage summary
            # flickers" report of 2026-07-20.
            if self._tab_active() and not self._pinned():
                self._view().set_mob_kills_text(
                    formatting.format_mob_kills(mob_kills, self._tracker().current_ui_kps()),
                )
                # The averages read the same deque `track_kills` just appended
                # to, one line below the instant KPS that has been painted here
                # since step 17. Two readings of one history, and only the top
                # one was live.
                self._view().set_kps_averages_text(
                    formatting.format_kps_averages(
                        self._tracker().current_minute_avg_kps(),
                        self._tracker().current_five_minute_avg_kps(),
                    ),
                )
                self._view().set_stage_summary_rows(
                    self._tracker().stage_summary_rows(),
                )
            if (
                self._widget_refresh_active("kps")
                or self._widget_refresh_active("stage_summary")
                or self._widget_refresh_active("build_progression")
            ):
                self._sync_overlay_state()
            return True
        except Exception as exc:
            # `read_memory_source` already recorded health for a run_timer/
            # mob_kills failure -- recording it again here would advance the
            # reconnect streak twice for one physical read. See
            # `source_health_recorded` and step_28_plan.md section 12.5. Any
            # *other* exception in this task body (client acquisition, tracker,
            # view) never passed through `read_memory_source`, so it still gets
            # recorded here exactly as before.
            if not source_health_recorded(context, exc):
                self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("combat", exc)
            return False

    def _refresh_event_timer_task(self, context: RefreshTickContext) -> bool:
        update_fast_stage_timer = getattr(self._tracker(), "update_fast_stage_timer", None)
        if not callable(update_fast_stage_timer):
            return True
        try:
            stage_timer_seconds, stage_index, stage_duration_seconds = read_memory_source(
                context,
                STAGE_TIMER_CONTEXT,
                self._fast_task_client(context).get_stage_timer_context,
            )
            self._memory().record_memory_success()
            update_fast_stage_timer(
                stage_timer_seconds=stage_timer_seconds,
                stage_index=stage_index,
                stage_duration_seconds=stage_duration_seconds,
                is_final_boss_stage=self._fast_stage_four_flag(context),
            )
            if self._tab_active():
                self._refresh_build_progression_view()
            self._mark_fast_feature_available("stage_timer")
            # Same guard, same reason: see `_refresh_fast_kps_task` above.
            if self._tab_active() and not self._pinned():
                self._view().set_stage_summary_rows(
                    self._tracker().stage_summary_rows(),
                )
            if (
                self._widget_refresh_active("stage_summary")
                or self._widget_refresh_active("build_progression")
            ):
                self._sync_overlay_state()
            return True
        except Exception as exc:
            self._memory().record_memory_failure(exc)
            update_fast_stage_timer(
                stage_timer_seconds=None,
                stage_index=None,
                stage_duration_seconds=None,
            )
            self._mark_fast_feature_failed("stage_timer", exc)
            return False

    def _fast_stage_four_flag(self, context: RefreshTickContext) -> bool:
        """``MapController.isFinalBossStage`` for the fast lane.

        The boss room is exactly where the slow lane has been observed to stall,
        which is what left Stage Summary stuck on Stage 3 for a whole room.  The
        flag costs one byte, so the lane that keeps running during a stall can
        afford to carry the one signal that needs no inference at all.

        Failure returns ``False`` -- "no information", never "not the boss
        room" -- because the tracker consumes it only to promote.
        """
        try:
            state = self._memory().read_player_stats_recording_state(context)
        except Exception:
            return False
        return bool(getattr(state, "is_final_boss_stage", False))

    def _refresh_chaos_tome_task(self, context: RefreshTickContext) -> bool:
        try:
            client = self._fast_task_client(context)
            owner_stats = self._fast_task_owner_stats(context)
            chaos_level, permanent_modifiers = read_memory_source(
                context,
                CHAOS_TRACKING_STATE,
                lambda: client.get_chaos_tracking_state(owner_stats),
            )
            passive_reader = getattr(client, "get_character_passive_reading", None)
            character_passive = (
                read_memory_source(
                    context,
                    CHARACTER_PASSIVE_READING,
                    lambda: passive_reader(
                        owner_stats,
                        permanent_modifiers=permanent_modifiers,
                    ),
                )
                if callable(passive_reader)
                else None
            )
            self._memory().record_memory_success()
            update_sources = getattr(self._tracker(), "update_permanent_sources", None)
            if callable(update_sources) and character_passive is not None:
                source_modifiers = permanent_modifiers if chaos_level is not None else {}
                tracker = self._tracker()
                needs_recovery = getattr(
                    tracker, "needs_permanent_source_recovery", None
                )
                recovery_required = bool(
                    self._permanent_source_recovery_job is not None
                    or callable(needs_recovery)
                    and needs_recovery(character_passive)
                )
                if recovery_required:
                    sample = _PermanentSourceSample.capture(
                        character_passive,
                        chaos_level,
                        source_modifiers,
                    )
                    recovery_required = self._advance_permanent_source_recovery(
                        sample
                    )
                if not recovery_required:
                    update_sources(
                        character_passive,
                        chaos_level=chaos_level,
                        permanent_modifiers=source_modifiers,
                    )
            else:
                self._tracker().update_chaos_tome(
                    chaos_level=chaos_level,
                    permanent_modifiers=(
                        permanent_modifiers if chaos_level is not None else {}
                    ),
                )
            # The card was painted only by the 10 s payload while this task
            # folded a new reading every tick, which is why `!chaos` in chat
            # could report a roll the app's own card had not shown yet. Same
            # `not pinned` guard as every other fast write: these are live
            # values and the user may have scrubbed the timeline.
            if self._tab_active() and not self._pinned():
                self._view().set_chaos_tome_card(self._tracker().chaos_tome_snapshot())
                setter = getattr(self._view(), "set_character_passive_card", None)
                if callable(setter):
                    setter(self._tracker().character_passive_snapshot())
            return True
        except Exception as exc:
            self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("chaos_tome", exc)
            self._mark_fast_feature_failed("character_passive", exc)
            return False

    def _advance_permanent_source_recovery(
        self,
        sample: _PermanentSourceSample,
    ) -> bool:
        """Poll/start Dice cold recovery without waiting in the GUI thread."""
        tracker = self._tracker()
        job = self._permanent_source_recovery_job
        if job is not None:
            self._permanent_source_recovery_latest_sample = sample
            if not job.done():
                return True

            self._permanent_source_recovery_job = None
            latest = self._permanent_source_recovery_latest_sample or sample
            self._permanent_source_recovery_latest_sample = None
            if job.error is not None:
                self._permanent_source_recovery_retry_at = (
                    time.monotonic() + PERMANENT_SOURCE_RECOVERY_RETRY_SECONDS
                )
                self._mark_fast_feature_failed("character_passive", job.error)
                return True

            apply_result = getattr(tracker, "apply_permanent_source_recovery", None)
            applied = bool(
                tracker is job.tracker
                and callable(apply_result)
                and apply_result(job.token, job.result, latest.reading)
            )
            if not applied:
                needs_recovery = getattr(
                    tracker, "needs_permanent_source_recovery", None
                )
                if not callable(needs_recovery) or not needs_recovery(latest.reading):
                    return False
                return self._start_permanent_source_recovery(latest)
            if latest.key != job.sample.key:
                return self._start_permanent_source_recovery(
                    latest,
                    base=job.result,
                )
            self._permanent_source_recovery_retry_at = 0.0
            return True

        needs_recovery = getattr(tracker, "needs_permanent_source_recovery", None)
        if not callable(needs_recovery) or not needs_recovery(sample.reading):
            return False
        if time.monotonic() < self._permanent_source_recovery_retry_at:
            return True
        return self._start_permanent_source_recovery(sample)

    def _start_permanent_source_recovery(
        self,
        sample: _PermanentSourceSample,
        *,
        base=None,
    ) -> bool:
        tracker = self._tracker()
        begin = getattr(tracker, "begin_permanent_source_recovery", None)
        if not callable(begin):
            return False
        token, reserved_modifier_ptrs = begin(sample.reading)
        self._permanent_source_recovery_latest_sample = sample
        self._permanent_source_recovery_job = (
            self._permanent_source_recovery_job_factory(
                tracker=tracker,
                token=token,
                sample=sample,
                reserved_modifier_ptrs=reserved_modifier_ptrs,
                base=base,
            )
        )
        return True

    def _refresh_charge_shrines_task(self, context: RefreshTickContext) -> bool:
        try:
            client = self._fast_task_client(context)
            reading = read_memory_source(
                context,
                SHRINE_TRACKING_STATE,
                client.get_charge_shrine_tracking_state,
            )
            owner_stats = self._fast_task_owner_stats(context)
            held_items = read_memory_source(
                context,
                PASSIVE_ITEMS,
                lambda: client.get_passive_items(owner_stats),
            )
            wrench_stacks = run_summary.item_counts(held_items).get("Wrench", 0)
            self._memory().record_memory_success()
            self._tracker().update_charge_shrines(
                reading,
                wrench_stacks=wrench_stacks,
            )
            self._mark_fast_feature_available("shrines")
            if self._tab_active() and not self._pinned():
                self._view().set_charge_shrine_card(
                    self._tracker().charge_shrine_snapshot()
                )
            return True
        except Exception as exc:
            if not source_health_recorded(context, exc):
                self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("shrines", exc)
            return False

    def _should_refresh_powerup_tracker(self) -> bool:
        if self._lifecycle().completed_run:
            return False
        # The ``try``/``except`` is the guard now. It was always doing the real
        # work: an owner without the predicate raises ``AttributeError`` through
        # the injected callable and lands on exactly the branch the deleted
        # ``callable()`` fallthrough reached.
        try:
            if self._tab_active():
                return True
        except Exception:
            pass
        if (
            in_game_overlay_widget_enabled("powerups")
            or in_game_overlay_widget_enabled("event_timer")
        ):
            return True
        commands_cfg = config.TWITCH_BOT.get("commands", {})
        try:
            return bool(self._twitch_active() and commands_cfg.get("powerups", True))
        except Exception:
            return False

    def _should_refresh_fast_kps(self, _now: float | None = None) -> bool:
        if self._lifecycle().completed_run:
            return False
        try:
            if self._tab_active():
                return True
        except Exception:
            pass
        if self._is_vod_recording():
            return True
        if (
            in_game_overlay_widget_enabled("kps")
            or in_game_overlay_widget_enabled("stage_summary")
            or in_game_overlay_widget_enabled("build_progression")
        ):
            return True
        if (
            self._widget_refresh_active("kps")
            or self._widget_refresh_active("stage_summary")
            or self._widget_refresh_active("build_progression")
        ):
            return True
        if self._twitch_stage_summary_refresh_active():
            return True
        if self._twitch_command_refresh_active("build"):
            return True
        commands_cfg = config.TWITCH_BOT.get("commands", {})
        try:
            return bool(self._twitch_active() and commands_cfg.get("kps", True))
        except Exception:
            return False

    def _should_refresh_expected_chest_inputs(self) -> bool:
        lifecycle = self._lifecycle()
        if lifecycle.is_active_run():
            return True
        if lifecycle.completed_run:
            return False
        # The in-game Luck Rarity Expected Frame reads this task's key-proc
        # expectation. Enabling it (with ``show_expected`` on) makes the widget a
        # recipient of this task, the same arm ``passive_items`` already grants
        # the Luck probabilities beside it -- without it the frame only fills
        # while a run reads as active or the Live Stats tab / a recording happens
        # to be holding this task up, which is the "widget is not a recipient"
        # gap the other overlay widgets closed. Placed below the completed_run
        # gate to match the powerups and KPS widgets (see
        # ``test_completed_run_blocks_all_refresh_demands``).
        if in_game_overlay_luck_expected_frame_active():
            return True
        # Unguarded, exactly as before: these two sites always called the
        # predicate directly and let it propagate.
        if self._tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("chests")

    def _should_refresh_full_player_snapshot(self) -> bool:
        return self._lifecycle().is_active_run() or self._refresh_required()

    def _should_refresh_passive_items(self) -> bool:
        """Everything the full snapshot demands, plus the Luck widget.

        The snapshot's own predicate was this task's predicate too, deliberately:
        it feeds the same tracked-item state recordings consume, so a demand
        window where one runs and the other does not would leave a gap in the
        data rather than merely a stale label. That still holds -- this is
        strictly wider, never narrower, so no such window can open.

        The extra arm is the other half of dropping `luck_rarity` from
        `in_game_overlay_requires_player_stats_refresh`. Luck rides this task
        now, so the widget has to be able to demand *this* task; without the arm
        a user running the Luck widget alone outside an active run would get no
        Luck read at all.
        """
        return (
            self._should_refresh_full_player_snapshot()
            or in_game_overlay_widget_enabled("luck_rarity")
            or self._build_progression_has_cap_demand()
        )

    def _build_progression_has_cap_demand(self) -> bool:
        try:
            service = self._build_progression_service()
            return service is not None and service.has_cap_demand()
        except Exception:
            return False

    def _should_refresh_chaos_tome(self) -> bool:
        if self._lifecycle().completed_run:
            return False
        if self._tab_active() or self._is_vod_recording():
            return True
        return (
            self._twitch_command_refresh_active("chaos")
            or self._twitch_command_refresh_active("dice")
        )

    def _should_refresh_charge_shrines(self) -> bool:
        if self._lifecycle().completed_run:
            return False
        if self._tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("shrines")

    def _twitch_command_refresh_active(self, command: str) -> bool:
        try:
            if not self._twitch_active():
                return False
        except Exception:
            return False
        commands = config.TWITCH_BOT.get("commands", {})
        default = config.DEFAULT_TWITCH_BOT["commands"].get(command, False)
        return bool(commands.get(command, default))

    def _is_vod_recording(self) -> bool:
        # The recorder callable keeps the old ``getattr(..., None)`` tolerance:
        # it is injected as a ``getattr`` with a ``None`` default, so an owner
        # without a recorder still reads as "not recording" rather than raising.
        recorder = self._vod_recorder()
        return bool(recorder is not None and getattr(recorder, "is_recording", False))

    def _should_refresh_fast_stage_timer(self) -> bool:
        if self._lifecycle().completed_run:
            return False
        try:
            if self._tab_active():
                return True
        except Exception:
            pass
        if self._is_vod_recording() or self._twitch_stage_summary_refresh_active():
            return True
        return (
            in_game_overlay_widget_enabled("event_timer")
            or in_game_overlay_widget_enabled("stage_summary")
            or in_game_overlay_widget_enabled("build_progression")
            or self._widget_refresh_active("stage_summary")
            or self._widget_refresh_active("build_progression")
            or self._twitch_command_refresh_active("build")
        )

    def _refresh_build_progression_view(self) -> None:
        refresh = getattr(self._view(), "refresh_build_progression", None)
        if callable(refresh):
            refresh()

    def _twitch_stage_summary_refresh_active(self) -> bool:
        try:
            if not self._twitch_active():
                return False
        except Exception:
            return False
        commands = config.TWITCH_BOT.get("commands", {})
        stages_enabled = bool(
            commands.get("stages", config.DEFAULT_TWITCH_BOT["commands"].get("stages", False))
        )
        return stages_enabled or bool(config.TWITCH_BOT.get("stage_announcements", True))


def refresh_tasks(owner) -> RefreshTasks:
    """Resolve the owner's ``RefreshTasks``, building it on first use.

    The same shape as ``player_stats_memory``, ``vod_capture`` and
    ``run_lifecycle``: the service's dependencies are the owner's sibling
    services, tracker and demand predicates, so ``AppCoordinator`` cannot
    construct it in its own ``__init__``. The coordinator caches it when there is
    one; an app double built with ``object.__new__`` has none and keeps it in
    ``__dict__``.

    ``__dict__``, not ``getattr``: ``MegabonkApp.__getattr__`` forwards unknown
    names to its ``window``, so a ``getattr`` would consult the widget before
    deciding there is no coordinator.

    Every argument is a lambda rather than a bound method or an attribute grab.
    ``self.live_run_tracker`` resolved late, on every call; capturing the tracker
    here would freeze whichever one existed when the service was first touched,
    and ``MegabonkApp`` replaces it per run. Step 20 shipped that difference as a
    bug twice.
    """
    coordinator = owner.__dict__.get("coordinator")
    if coordinator is not None:
        existing = getattr(coordinator, "refresh_tasks", None)
        if existing is not None:
            return existing

    existing = owner.__dict__.get("_refresh_tasks")
    if existing is not None:
        return existing

    service = RefreshTasks(
        memory=lambda: player_stats_memory(owner),
        lifecycle=lambda: run_lifecycle(owner),
        view=lambda: player_stats_view(owner),
        capture=lambda: vod_capture(owner),
        tracker=lambda: owner.live_run_tracker,
        # ``getattr`` with a ``None`` default, preserving ``_is_vod_recording``'s
        # tolerance of an owner that has no recorder attribute at all.
        vod_recorder=lambda: getattr(owner, "player_stats_vod_recorder", None),
        tab_active=lambda: owner._is_live_stats_tab_active(),
        twitch_active=lambda: owner._is_twitch_bot_active(),
        pinned=lambda: player_stats_snapshot_is_pinned(owner),
        widget_refresh_active=lambda widget_id: overlay_widget_refresh_active(owner, widget_id),
        sync_overlay_state=lambda: owner.update_overlay_state_from_tracker(),
        # The in-game overlay's counterpart to `sync_overlay_state`: one command
        # on the other overlay component, resolved through the owner for the
        # same reason.
        sync_in_game_kps=lambda: owner.refresh_in_game_overlay_kps(),
        # The same shape as `sync_overlay_state` above, and resolved through the
        # owner for the same reason: it is one command on a component this
        # service does not otherwise hold.
        refresh_session_tracked_items=lambda: owner.refresh_session_tracked_item_stats_ui(),
        refresh_required=lambda: player_stats_refresh_required(owner),
        build_progression_service=lambda: getattr(owner, "build_progression_service", getattr(getattr(owner, "coordinator", None), "build_progression_service", None)),
    )
    if coordinator is not None:
        coordinator.refresh_tasks = service
    else:
        owner.__dict__["_refresh_tasks"] = service
    return service
