"""VOD capture lifecycle -- arming, auto-start, start, stop, and the periodic
run-state sync that decides when a recording must end on its own.

This is the other half of the line ``app/vod_library.py`` draws: the library
module manages recordings the user already has (load, rename, delete,
reindex); this module decides when one begins and ends. Split out of
``PlayerStatsMixin`` in step 14c.

``_sync_player_stats_recording_run_state`` is what auto-stops a dead recording,
which is why its refresh task is unconditionally required rather than gated on
consumer demand -- see ``app/refresh_tasks.py``.

**Pause is an active run, and the asymmetry here is deliberate.** Core tracking
continues while ``PAUSED_IN_GAME`` but capture does not: ``can_capture_recording``
requires ``IN_GAME`` strictly, and a paused recording reports status
``\"paused\"`` and writes nothing. Do not 'fix' this into symmetry.

This module renders through ``PlayerStatsView`` and ``RecordingsListView``
(``app/player_stats_view.py``),
never through a widget. ``_sync_player_stats_recording_run_state`` used to write
the ``player_stats_status_label`` widget directly -- a Qt write from the app
layer, against a label owned by ``ui/tabs/player_stats/live_stats.py`` -- and
that is now ``view.set_recording_status_text(...)``, implemented by the mixin
that builds the label.
"""
from __future__ import annotations

import time

from app import config
from app.player_stats_view import player_stats_view, recordings_list_view
from app.run_lifecycle import run_lifecycle
from core.game_state import RuntimeGameMode
from core.run_summary import PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS

# Moved here from gui_styles.py in step 17a; this module is its only consumer.
PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS = 20


class VodCaptureMixin:
    def _is_player_stats_recording_armed(self) -> bool:
        auto_recording_enabled = bool(getattr(config, "AUTO_START_RECORDING", False))
        auto_recording_suppressed = bool(
            getattr(self, "player_stats_auto_recording_suppressed", False)
        )
        return bool(getattr(self, "player_stats_recording_armed", False)) or bool(
            auto_recording_enabled and not auto_recording_suppressed
        )

    def toggle_player_stats_recording(self):
        if self.player_stats_vod_recorder.is_recording or self._is_player_stats_recording_armed():
            self.player_stats_recording_armed = False
            self.player_stats_recording_waiting_mode = None
            if bool(getattr(config, "AUTO_START_RECORDING", False)):
                self.player_stats_auto_recording_suppressed = True
            self._stop_player_stats_recording(log_message="[*] Player stats recording stopped.")
        else:
            self.player_stats_recording_armed = True
            self.player_stats_auto_recording_suppressed = False
            state = self._read_player_stats_recording_state_safe()
            seed = state.map_seed if state is not None else None
            stage_ptr = state.current_stage_ptr if state is not None else 0
            stage_index = state.stage_index if state is not None else None
            run_time_seconds = self._read_player_stats_recording_run_timer_safe()
            runtime_state = run_lifecycle(self).state_or_unknown()
            if runtime_state.mode is RuntimeGameMode.IN_GAME:
                vod_path = self._start_player_stats_recording(
                    seed=seed,
                    stage_ptr=stage_ptr,
                    stage_index=stage_index,
                    run_time_seconds=run_time_seconds,
                )
                self.log(f"[*] Player stats recording started: {vod_path.name}", tag="success")
            else:
                self.player_stats_recording_waiting_mode = runtime_state.mode.value
                self.log(
                    "[*] Player stats recording armed; waiting for an active run.",
                    tag="success",
                )
            self.refresh_live_player_stats_now(
                waiting_status_text="Recording stats; waiting for game/player stats...",
                unavailable_status_prefix="Recording stats; player stats unavailable",
            )
            recordings_list_view(self)._refresh_vods_list_if_visible()

        player_stats_view(self).refresh_player_stats_timeline_ui()

    @staticmethod
    def _stage_index_signals_new_run(
        previous_index: int | None,
        current_index: int | None,
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool | None:
        """Decide "same run" vs. "new run" from stage_index direction.

        stage_index is a MapController static-field ordinal that survives the
        loading screen, unlike the run timer this replaced (step 8b): a failed
        timer read used to be treated as "different run" and split a recording
        on an ordinary map transition.

        Returns True to split, False to continue the current recording, or
        None when the index could not be read this tick -- the caller must not
        decide from that, only wait for the next sample.
        """
        if current_index is None:
            return None
        if previous_index is None:
            # No baseline yet (the index was unreadable when this recording
            # started). Adopt it without splitting; there is nothing to compare.
            return False
        if current_index > previous_index:
            return False  # map transition within the same run (e.g. 1 -> 2 -> 3)
        if current_index < previous_index:
            return True  # index reset -- a new run started
        # Unchanged. Live-verified (Graveyard, and the virtual stage-4 boss
        # room): this game never changes stage_ptr or seed without stage_index
        # also moving, except when a new run starts at the same index a
        # finished run held (typically 0). The run timer resetting confirms
        # that case. Missing timer data must not manufacture a split -- that is
        # exactly the failure this guard replaces -- so treat it as "continue".
        if current_run_time_seconds is None or previous_run_time_seconds is None:
            return False
        return (
            current_run_time_seconds + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
            < previous_run_time_seconds
        )

    def _start_player_stats_recording(
        self,
        *,
        seed: int | None = None,
        stage_ptr: int = 0,
        stage_index: int | None = None,
        run_time_seconds: float | None = None,
    ):
        vod_path = self.player_stats_vod_recorder.start(seed=seed)
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_snapshot_pinned = False
        self.player_stats_recording_seed = seed
        self.player_stats_recording_stage_ptr = stage_ptr
        self.player_stats_recording_stage_index = stage_index
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = run_time_seconds
        self.player_stats_recording_waiting_mode = None
        self.player_stats_auto_recording_suppressed = False
        self.player_stats_auto_start_detection_streak = 0
        return vod_path

    def _stop_player_stats_recording(
        self,
        *,
        log_message: str | None = None,
        log_tag: str | None = None,
        refresh_live_stats: bool = True,
    ) -> None:
        self.player_stats_vod_recorder.stop()
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_snapshot_pinned = False
        self.player_stats_recording_seed = None
        self.player_stats_recording_stage_ptr = 0
        self.player_stats_recording_stage_index = None
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = None
        self.player_stats_recording_waiting_mode = None
        self.player_stats_auto_start_detection_streak = 0
        self.close_player_stats_game_data_client()
        if log_message:
            self.log(log_message, tag=log_tag)
        if refresh_live_stats:
            self.refresh_live_player_stats_now()
        recordings_list_view(self)._refresh_vods_list_if_visible()

    def _sync_player_stats_recording_run_state(self) -> str | None:
        # Reuses the lifecycle state the 500 ms driver already refreshes once a
        # second, rather than issuing its own uncached get_runtime_game_state().
        # At this task's old 10 s cadence that extra heavy read was affordable;
        # at 1 s it would be ten times a second, for a mode the cheaper cached
        # reader computes identically (verified exhaustively -- the extra
        # `and not is_game_over` in get_runtime_game_state is unreachable).
        # Only `.mode` is used here, which is all the cached state carries.
        runtime_state = run_lifecycle(self).state_for_refresh()
        lifecycle = run_lifecycle(self)
        if runtime_state.mode is RuntimeGameMode.GAME_OVER:
            lifecycle.set_completed(True)
            # Unguarded, unlike `RunLifecycle.refresh()`, which marks only on
            # the transition. Inherited verbatim: making the two symmetric is a
            # behaviour change and this commit is not one.
            lifecycle.mark_completed_on_tracker()
        if runtime_state.mode is RuntimeGameMode.IN_GAME:
            lifecycle.set_completed(False)
            was_paused = self.player_stats_recording_waiting_mode == RuntimeGameMode.PAUSED_IN_GAME.value
            self.player_stats_recording_waiting_mode = None
            if was_paused and self.player_stats_vod_recorder.is_recording:
                player_stats_view(self).refresh_player_stats_timeline_ui()
                if self._is_live_stats_tab_active():
                    player_stats_view(self).set_recording_status_text("Live player stats (recording)")
            if self._is_player_stats_recording_armed() and not self.player_stats_vod_recorder.is_recording:
                current_state = self._read_player_stats_recording_state_safe()
                current_seed = current_state.map_seed if current_state is not None else None
                current_stage_ptr = (
                    current_state.current_stage_ptr if current_state is not None else 0
                )
                current_stage_index = (
                    getattr(current_state, "stage_index", None) if current_state is not None else None
                )
                current_run_time_seconds = self._read_player_stats_recording_run_timer_safe()
                vod_path = self._start_player_stats_recording(
                    seed=current_seed,
                    stage_ptr=current_stage_ptr,
                    stage_index=current_stage_index,
                    run_time_seconds=current_run_time_seconds,
                )
                self.log(
                    f"[*] Player stats recording started from waiting mode: {vod_path.name}",
                    tag="success",
                )
                player_stats_view(self).refresh_player_stats_timeline_ui()
                return "started"

        if not self.player_stats_vod_recorder.is_recording:
            return None

        if runtime_state.mode is RuntimeGameMode.PAUSED_IN_GAME:
            was_paused = self.player_stats_recording_waiting_mode == runtime_state.mode.value
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            if not was_paused:
                player_stats_view(self).refresh_player_stats_timeline_ui()
                if self._is_live_stats_tab_active():
                    player_stats_view(self).set_recording_status_text("Live player stats (recording paused)")
            return "paused"
        if runtime_state.mode in {RuntimeGameMode.GAME_OVER, RuntimeGameMode.MAIN_MENU}:
            mode_text = "game over" if runtime_state.mode is RuntimeGameMode.GAME_OVER else "main menu"
            should_remain_armed = self._is_player_stats_recording_armed()
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            self._stop_player_stats_recording(
                log_message=f"[*] Player stats recording waiting: {mode_text}.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            if not should_remain_armed:
                self.player_stats_recording_armed = False
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            player_stats_view(self).refresh_player_stats_timeline_ui()
            return "waiting"
        if runtime_state.mode is RuntimeGameMode.UNKNOWN:
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            return None

        now = time.monotonic()
        current_state = self._read_player_stats_recording_state_safe()
        current_seed = current_state.map_seed if current_state is not None else None
        current_stage_ptr = (
            current_state.current_stage_ptr if current_state is not None else 0
        )
        current_stage_index = (
            getattr(current_state, "stage_index", None) if current_state is not None else None
        )
        current_run_time_seconds = self._read_player_stats_recording_run_timer_safe()
        if current_seed is None:
            if self.player_stats_recording_seed_missing_since is None:
                self.player_stats_recording_seed_missing_since = now
                return None
            if now - self.player_stats_recording_seed_missing_since < PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS:
                return None
            self.player_stats_recording_armed = False
            self._stop_player_stats_recording(
                log_message="[*] Player stats recording auto-stopped: run seed disappeared.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            player_stats_view(self).refresh_player_stats_timeline_ui()
            return "stopped"

        self.player_stats_recording_seed_missing_since = None
        if self.player_stats_recording_seed is None:
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_stage_index = current_stage_index
        if (
            current_seed == self.player_stats_recording_seed
            and current_stage_ptr == self.player_stats_recording_stage_ptr
        ):
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        previous_seed = self.player_stats_recording_seed
        previous_run_time_seconds = self.player_stats_recording_run_time_seconds
        decision = self._stage_index_signals_new_run(
            self.player_stats_recording_stage_index,
            current_stage_index,
            previous_run_time_seconds,
            current_run_time_seconds,
        )
        if decision is None:
            # stage_index unreadable this tick. Absence of data is not an
            # answer -- the bug this guard replaces -- so wait for the next
            # sample instead of deciding from it.
            return None
        if not decision:
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_stage_index = current_stage_index
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        self._stop_player_stats_recording(refresh_live_stats=False)
        vod_path = self._start_player_stats_recording(
            seed=current_seed,
            stage_ptr=current_stage_ptr,
            stage_index=current_stage_index,
            run_time_seconds=current_run_time_seconds,
        )
        self.log(
            f"[*] Player stats recording auto-split: seed {previous_seed} -> {current_seed}; new file {vod_path.name}",
            tag="success",
        )
        player_stats_view(self).refresh_player_stats_timeline_ui()
        return "split"

    @staticmethod
    def _looks_like_active_run_for_auto_recording(
        *,
        stats,
        run_timer_seconds: float | None,
        player_level: int | None,
        map_seed: int | None,
        stage_ptr: int,
    ) -> bool:
        if run_timer_seconds is None or float(run_timer_seconds) <= 0:
            return False
        if map_seed is not None:
            return True
        if int(stage_ptr or 0) > 0:
            return True
        if player_level is not None and int(player_level) > 0:
            return True
        return bool(stats)

    def _maybe_auto_start_player_stats_recording(
        self,
        *,
        stats,
        run_timer_seconds: float | None,
        player_level: int | None,
        map_seed: int | None,
        stage_ptr: int,
        stage_index: int | None = None,
    ) -> bool:
        if self.player_stats_vod_recorder.is_recording:
            self.player_stats_auto_start_detection_streak = 0
            return False
        if bool(getattr(self, "player_stats_auto_recording_suppressed", False)):
            self.player_stats_auto_start_detection_streak = 0
            return False
        if not bool(getattr(config, "AUTO_START_RECORDING", False)):
            self.player_stats_auto_start_detection_streak = 0
            return False
        if not self._looks_like_active_run_for_auto_recording(
            stats=stats,
            run_timer_seconds=run_timer_seconds,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
        ):
            self.player_stats_auto_start_detection_streak = 0
            return False

        self.player_stats_auto_start_detection_streak = int(
            getattr(self, "player_stats_auto_start_detection_streak", 0)
        ) + 1
        if self.player_stats_auto_start_detection_streak < 2:
            return False

        vod_path = self._start_player_stats_recording(
            seed=map_seed,
            stage_ptr=stage_ptr,
            stage_index=stage_index,
            run_time_seconds=run_timer_seconds,
        )
        self.log(f"[*] Player stats recording auto-started: {vod_path.name}", tag="success")
        return True
