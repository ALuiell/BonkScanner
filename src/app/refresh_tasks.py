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

**What this service owns: two fields, decided by counting.**
``_player_stats_refresh_status_text`` and ``_last_fast_kps_game_time_seconds``
had every reader and writer inside this file -- nothing in ``src/`` else touches
either -- so they move in, exactly as the two reconnect streaks moved into
``PlayerStatsMemory``. Both keep their old spellings and both are initialised to
the value the ``getattr`` default used to supply, so the pre-first-write read is
unchanged. ``_refresh_coordinator`` does **not** move: it stays behind
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

from typing import TYPE_CHECKING, Any, Callable

from app import config
from app.player_stats_memory import player_stats_memory
from app.read_sources import (
    MOB_KILLS,
    OWNER_STATS,
    PLAYER_STATS_CLIENT,
    RUN_TIMER,
    read_memory_source,
    source_health_recorded,
)
from app.refresh_coordinator import RefreshCoordinator, RefreshTask, RefreshTickContext
from app.run_lifecycle import run_lifecycle
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
    # Registered first, and deliberately so: ``tick`` runs tasks in registration
    # order, and ``full_player_snapshot`` below reads the status text this task
    # writes. Before the timers were collapsed this ordering was implicit -- the
    # 10 s callback ran the recording sync and then called ``tick``.
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
            run=lambda _context: owner.refresh_live_player_stats_now(
                status_text=service._player_stats_refresh_status_text
            ),
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
    return (
        in_game_overlay_widget_enabled("luck_rarity")
        or in_game_overlay_widget_enabled("stats")
        or in_game_overlay_widget_enabled("event_timer")
    )


def overlay_requires_player_snapshot(owner) -> bool:
    return any(
        overlay_widget_refresh_active(owner, widget_id)
        for widget_id in ("stage_summary", "tracked_items", "stats", "banishes")
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

    Twelve collaborators, all callables. ``_memory``/``_lifecycle``/``_view``/
    ``_capture`` return the sibling services; ``_widget_refresh_active`` is the
    module function above with its ``owner`` already bound; the rest are the
    owner's tracker, predicates and the one overlay command.
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
        refresh_required: Callable[[], bool],
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
        self._refresh_required = refresh_required

        # Owned state. Both initialised to the value the ``getattr`` default on
        # the app used to supply, so the read before the first write is
        # unchanged. Nothing outside this file ever touched either name.
        self._player_stats_refresh_status_text = "Live player stats"
        self._last_fast_kps_game_time_seconds: float | None = None

    def _refresh_recording_lifecycle_task(self, _context: RefreshTickContext) -> bool:
        """Recording auto-start/auto-stop/pause handling, formerly the body of the
        10 s Qt timer callback.

        It is a task rather than a side effect of the surviving 500 ms driver so
        that it owns its own cadence. Step 8 kept that at the inherited 10 s to
        stay a pure refactor; step 8b then moved it to 1 s on its own merits,
        which is what having a task made possible.
        """
        recording_state_action = self._capture().sync_run_state()
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

    def _mark_fast_feature_failed(self, feature: str, error: Exception) -> None:
        marker = getattr(self._tracker(), "mark_feature_failed", None)
        if callable(marker):
            try:
                marker(feature, error)
            except Exception:
                pass

    def _refresh_powerups_task(self, context: RefreshTickContext) -> bool:
        try:
            snapshot = self._fast_task_client(context).get_powerup_tracking_snapshot(
                self._fast_task_owner_stats(context)
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
            chests_bought, keys_count = self._fast_task_client(context).get_expected_chest_inputs(
                self._fast_task_owner_stats(context)
            )
            self._memory().record_memory_success()
            self._tracker().track_expected_key_procs(chests_bought, keys_count)
            self._mark_fast_feature_available("expected_chests")
            return True
        except Exception as exc:
            self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("expected_chests", exc)
            return False

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
            self._mark_fast_feature_available("combat")
            previous_game_time = self._last_fast_kps_game_time_seconds
            if (
                run_timer_seconds is not None
                and previous_game_time is not None
                and abs(float(run_timer_seconds) - float(previous_game_time)) < 0.001
            ):
                return True
            mob_kills = read_memory_source(
                context,
                MOB_KILLS,
                client.get_killed_mobs,
                on_success=self._memory().record_memory_success,
                on_failure=self._memory().record_memory_failure,
            )
            self._tracker().track_kills(run_timer_seconds, mob_kills)
            self._last_fast_kps_game_time_seconds = run_timer_seconds
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
                self._view().set_stage_summary_rows(
                    self._tracker().stage_summary_rows(),
                )
            if (
                self._widget_refresh_active("kps")
                or self._widget_refresh_active("stage_summary")
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
            if not source_health_recorded(exc):
                self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("combat", exc)
            return False

    def _refresh_event_timer_task(self, context: RefreshTickContext) -> bool:
        update_fast_stage_timer = getattr(self._tracker(), "update_fast_stage_timer", None)
        if not callable(update_fast_stage_timer):
            return True
        try:
            stage_timer_seconds, stage_index, stage_duration_seconds = (
                self._fast_task_client(context).get_stage_timer_context()
            )
            self._memory().record_memory_success()
            update_fast_stage_timer(
                stage_timer_seconds=stage_timer_seconds,
                stage_index=stage_index,
                stage_duration_seconds=stage_duration_seconds,
            )
            self._mark_fast_feature_available("stage_timer")
            # Same guard, same reason: see `_refresh_fast_kps_task` above.
            if self._tab_active() and not self._pinned():
                self._view().set_stage_summary_rows(
                    self._tracker().stage_summary_rows(),
                )
            if self._widget_refresh_active("stage_summary"):
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

    def _refresh_chaos_tome_task(self, context: RefreshTickContext) -> bool:
        try:
            chaos_level, permanent_modifiers = self._fast_task_client(
                context
            ).get_chaos_tracking_state(self._fast_task_owner_stats(context))
            self._memory().record_memory_success()
            self._tracker().update_chaos_tome(
                chaos_level=chaos_level,
                permanent_modifiers=permanent_modifiers if chaos_level is not None else {},
            )
            return True
        except Exception as exc:
            self._memory().record_memory_failure(exc)
            self._mark_fast_feature_failed("chaos_tome", exc)
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
        ):
            return True
        if (
            self._widget_refresh_active("kps")
            or self._widget_refresh_active("stage_summary")
        ):
            return True
        if self._twitch_stage_summary_refresh_active():
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
        # Unguarded, exactly as before: these two sites always called the
        # predicate directly and let it propagate.
        if self._tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("chests")

    def _should_refresh_full_player_snapshot(self) -> bool:
        return self._lifecycle().is_active_run() or self._refresh_required()

    def _should_refresh_chaos_tome(self) -> bool:
        if self._lifecycle().completed_run:
            return False
        if self._tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("chaos")

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
            or self._widget_refresh_active("stage_summary")
        )

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
        refresh_required=lambda: player_stats_refresh_required(owner),
    )
    if coordinator is not None:
        coordinator.refresh_tasks = service
    else:
        owner.__dict__["_refresh_tasks"] = service
    return service
