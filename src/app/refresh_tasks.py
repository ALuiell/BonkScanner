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

``ensure_refresh_coordinator``, ``overlay_widget_refresh_active`` and the two
``record_player_stats_memory_*`` helpers are plain functions, not mixin
methods: each also has callers outside this module (the timer driver,
``_overlay_requires_player_snapshot``, and five memory-read call sites --
all of which step 14c moved on to ``app/player_stats_refresh.py`` and
``app/player_stats_memory.py``). A mixin method reachable only via the shared
``self`` would show up as a new hidden cross-mixin read the moment its
caller and its definition live in different files -- passing the owner
explicitly avoids that without changing behaviour.

Everything else here (the six ``_should_refresh_*``/``_refresh_*_task``
pairs and their private helpers) has no caller outside this module, so it
stays as ``RefreshTasksMixin`` methods, mixed into ``MegabonkApp`` alongside
the other seven GUI mixins -- unlike steps 1-5's moves, this one still reads
the shared ``self`` it always did. Explicit dependency injection for *this*
code is step 11's job (``AppCoordinator``), not this one's.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app import config
from app.refresh_coordinator import RefreshCoordinator, RefreshTask, RefreshTickContext
from gui_shared import _set_text
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from projections import formatting

if TYPE_CHECKING:
    from infra.memory.player_stats_client import PlayerStatsClient


PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD = 3

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
            run=owner._refresh_recording_lifecycle_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="full_player_snapshot",
            interval_ms=PLAYER_STATS_REFRESH_MS,
            required=owner._should_refresh_full_player_snapshot,
            run=lambda _context: owner.refresh_live_player_stats_now(
                status_text=getattr(
                    owner,
                    "_player_stats_refresh_status_text",
                    "Live player stats",
                )
            ),
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="combat_metrics",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=owner._should_refresh_fast_kps,
            run=owner._refresh_combat_metrics_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="powerups",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=owner._should_refresh_powerup_tracker,
            run=owner._refresh_powerups_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="expected_chest_inputs",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=owner._should_refresh_expected_chest_inputs,
            run=owner._refresh_expected_chest_inputs_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="event_timer",
            interval_ms=1_000,
            required=owner._should_refresh_fast_stage_timer,
            run=owner._refresh_event_timer_task,
        )
    )
    coordinator.register(
        RefreshTask(
            task_id="chaos_tome",
            interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
            required=owner._should_refresh_chaos_tome,
            run=owner._refresh_chaos_tome_task,
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


def record_player_stats_memory_success(owner) -> None:
    owner._player_stats_memory_error_streak = 0


def record_player_stats_memory_failure(owner, error: Exception) -> None:
    if not isinstance(error, (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError)):
        return
    streak = int(getattr(owner, "_player_stats_memory_error_streak", 0)) + 1
    owner._player_stats_memory_error_streak = streak
    if streak < PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD:
        return
    try:
        owner.close_player_stats_client()
    finally:
        owner._player_stats_memory_error_streak = 0


class RefreshTasksMixin:
    def _refresh_recording_lifecycle_task(self, _context: RefreshTickContext) -> bool:
        """Recording auto-start/auto-stop/pause handling, formerly the body of the
        10 s Qt timer callback.

        It is a task rather than a side effect of the surviving 500 ms driver so
        that it owns its own cadence. Step 8 kept that at the inherited 10 s to
        stay a pure refactor; step 8b then moved it to 1 s on its own merits,
        which is what having a task made possible.
        """
        recording_state_action = self._sync_player_stats_recording_run_state()
        self._player_stats_refresh_status_text = (
            "Live player stats"
            if recording_state_action != "stopped"
            else "Live player stats (recording auto-stopped after run end)"
        )
        return True

    def _fast_task_client(self, context: RefreshTickContext) -> PlayerStatsClient:
        return context.get_or_create("player_stats_client", self._get_player_stats_client)

    def _fast_task_owner_stats(self, context: RefreshTickContext) -> int:
        return context.get_or_create(
            "owner_stats",
            lambda: self._fast_task_client(context).resolve_owner_stats(),
        )

    def _mark_fast_feature_available(self, feature: str) -> None:
        marker = getattr(self.live_run_tracker, "mark_feature_available", None)
        if callable(marker):
            try:
                marker(feature)
            except Exception:
                pass

    def _mark_fast_feature_failed(self, feature: str, error: Exception) -> None:
        marker = getattr(self.live_run_tracker, "mark_feature_failed", None)
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
            record_player_stats_memory_success(self)
            accepted = self.live_run_tracker.update_powerups(snapshot)
            self._refresh_live_powerups_label()
            return accepted is not False
        except Exception as exc:
            record_player_stats_memory_failure(self, exc)
            self._mark_fast_feature_failed("powerups", exc)
            self._refresh_live_powerups_label()
            return False

    def _refresh_expected_chest_inputs_task(self, context: RefreshTickContext) -> bool:
        try:
            chests_bought, keys_count = self._fast_task_client(context).get_expected_chest_inputs(
                self._fast_task_owner_stats(context)
            )
            record_player_stats_memory_success(self)
            self.live_run_tracker.track_expected_key_procs(chests_bought, keys_count)
            self._mark_fast_feature_available("expected_chests")
            return True
        except Exception as exc:
            record_player_stats_memory_failure(self, exc)
            self._mark_fast_feature_failed("expected_chests", exc)
            return False

    def _refresh_combat_metrics_task(self, context: RefreshTickContext) -> bool:
        try:
            client = self._fast_task_client(context)
            run_timer_seconds = client.get_run_timer()
            record_player_stats_memory_success(self)
            self._mark_fast_feature_available("combat")
            previous_game_time = getattr(self, "_last_fast_kps_game_time_seconds", None)
            if (
                run_timer_seconds is not None
                and previous_game_time is not None
                and abs(float(run_timer_seconds) - float(previous_game_time)) < 0.001
            ):
                return True
            mob_kills = client.get_killed_mobs()
            record_player_stats_memory_success(self)
            self.live_run_tracker.track_kills(run_timer_seconds, mob_kills)
            self._last_fast_kps_game_time_seconds = run_timer_seconds
            if self._is_live_stats_tab_active():
                _set_text(
                    self.player_stats_mob_kills_label,
                    formatting.format_mob_kills(mob_kills, self.live_run_tracker.current_ui_kps()),
                )
                self._set_stage_summary_labels(
                    getattr(self, "player_stats_stage_summary_labels", None),
                    self.live_run_tracker.stage_summary_rows(),
                )
            if (
                overlay_widget_refresh_active(self, "kps")
                or overlay_widget_refresh_active(self, "stage_summary")
            ):
                self.update_overlay_state_from_tracker()
            return True
        except Exception as exc:
            record_player_stats_memory_failure(self, exc)
            self._mark_fast_feature_failed("combat", exc)
            return False

    def _refresh_event_timer_task(self, context: RefreshTickContext) -> bool:
        update_fast_stage_timer = getattr(self.live_run_tracker, "update_fast_stage_timer", None)
        if not callable(update_fast_stage_timer):
            return True
        try:
            stage_timer_seconds, stage_index, stage_duration_seconds = (
                self._fast_task_client(context).get_stage_timer_context()
            )
            record_player_stats_memory_success(self)
            update_fast_stage_timer(
                stage_timer_seconds=stage_timer_seconds,
                stage_index=stage_index,
                stage_duration_seconds=stage_duration_seconds,
            )
            self._mark_fast_feature_available("stage_timer")
            if self._is_live_stats_tab_active():
                self._set_stage_summary_labels(
                    getattr(self, "player_stats_stage_summary_labels", None),
                    self.live_run_tracker.stage_summary_rows(),
                )
            if overlay_widget_refresh_active(self, "stage_summary"):
                self.update_overlay_state_from_tracker()
            return True
        except Exception as exc:
            record_player_stats_memory_failure(self, exc)
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
            record_player_stats_memory_success(self)
            self.live_run_tracker.update_chaos_tome(
                chaos_level=chaos_level,
                permanent_modifiers=permanent_modifiers if chaos_level is not None else {},
            )
            return True
        except Exception as exc:
            record_player_stats_memory_failure(self, exc)
            self._mark_fast_feature_failed("chaos_tome", exc)
            return False

    def _should_refresh_powerup_tracker(self) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        is_live_stats_tab_active = getattr(self, "_is_live_stats_tab_active", None)
        if callable(is_live_stats_tab_active):
            try:
                if is_live_stats_tab_active():
                    return True
            except Exception:
                pass
        if (
            self._in_game_overlay_widget_enabled("powerups")
            or self._in_game_overlay_widget_enabled("event_timer")
        ):
            return True
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        commands_cfg = config.TWITCH_BOT.get("commands", {})
        if callable(is_twitch_bot_active):
            try:
                return bool(is_twitch_bot_active() and commands_cfg.get("powerups", True))
            except Exception:
                return False
        return False

    def _should_refresh_fast_kps(self, _now: float | None = None) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        is_live_stats_tab_active = getattr(self, "_is_live_stats_tab_active", None)
        if callable(is_live_stats_tab_active):
            try:
                if is_live_stats_tab_active():
                    return True
            except Exception:
                pass
        if self._is_vod_recording():
            return True
        if (
            self._in_game_overlay_widget_enabled("kps")
            or self._in_game_overlay_widget_enabled("stage_summary")
        ):
            return True
        if (
            overlay_widget_refresh_active(self, "kps")
            or overlay_widget_refresh_active(self, "stage_summary")
        ):
            return True
        if self._twitch_stage_summary_refresh_active():
            return True
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        commands_cfg = config.TWITCH_BOT.get("commands", {})
        if callable(is_twitch_bot_active):
            try:
                return bool(is_twitch_bot_active() and commands_cfg.get("kps", True))
            except Exception:
                return False
        return False

    def _should_refresh_expected_chest_inputs(self) -> bool:
        core_run_active = getattr(self, "_core_run_active", None)
        if callable(core_run_active) and core_run_active():
            return True
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        if self._is_live_stats_tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("chests")

    def _should_refresh_full_player_snapshot(self) -> bool:
        core_run_active = getattr(self, "_core_run_active", None)
        return bool(callable(core_run_active) and core_run_active()) or self._player_stats_refresh_required()

    def _core_run_active(self) -> bool:
        state = getattr(self, "_core_runtime_game_state", None)
        return bool(state is not None and state.is_active_run)

    def _should_refresh_chaos_tome(self) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        if self._is_live_stats_tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("chaos")

    def _twitch_command_refresh_active(self, command: str) -> bool:
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        if not callable(is_twitch_bot_active):
            return False
        try:
            if not is_twitch_bot_active():
                return False
        except Exception:
            return False
        commands = config.TWITCH_BOT.get("commands", {})
        default = config.DEFAULT_TWITCH_BOT["commands"].get(command, False)
        return bool(commands.get(command, default))

    def _is_vod_recording(self) -> bool:
        recorder = getattr(self, "player_stats_vod_recorder", None)
        return bool(recorder is not None and getattr(recorder, "is_recording", False))

    def _should_refresh_fast_stage_timer(self) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        is_live_stats_tab_active = getattr(self, "_is_live_stats_tab_active", None)
        if callable(is_live_stats_tab_active):
            try:
                if is_live_stats_tab_active():
                    return True
            except Exception:
                pass
        if self._is_vod_recording() or self._twitch_stage_summary_refresh_active():
            return True
        return (
            self._in_game_overlay_widget_enabled("event_timer")
            or self._in_game_overlay_widget_enabled("stage_summary")
            or overlay_widget_refresh_active(self, "stage_summary")
        )

    def _twitch_stage_summary_refresh_active(self) -> bool:
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        if not callable(is_twitch_bot_active):
            return False
        try:
            if not is_twitch_bot_active():
                return False
        except Exception:
            return False
        commands = config.TWITCH_BOT.get("commands", {})
        stages_enabled = bool(
            commands.get("stages", config.DEFAULT_TWITCH_BOT["commands"].get("stages", False))
        )
        return stages_enabled or bool(config.TWITCH_BOT.get("stage_announcements", True))
