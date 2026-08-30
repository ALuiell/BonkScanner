"""VOD capture lifecycle -- arming, auto-start, start, stop, and the periodic
run-state sync that decides when a recording must end on its own.

This is the other half of the line ``app/vod_library.py`` draws: the library
module manages recordings the user already has (load, rename, delete,
reindex); this module decides when one begins and ends. Split out of
``PlayerStatsMixin`` in step 14c, and converted from ``VodCaptureMixin`` into
an ordinary constructed service in step 20.

**The last edge of the step-20 fork closes here.** The fork decision was
"(c) for the state, (b) for the one edge that is genuinely a command".
``4f3d9ae`` executed the (c) half by extracting ``RunLifecycle``, which removed
two of the three VodCapture->Refresh edges by construction. The third,
``refresh_live_player_stats_now``, is one semantic operation -- *repaint now* --
and it arrives here as the ``refresh_now`` constructor argument. Refresh
implements it; Refresh->VodCapture stays a direct dependency; the cycle is gone.

``refresh_now`` is a plain callable rather than a one-method ``Protocol``
class. That follows ``RunLifecycle``, three commits old, whose two memory reads
are plain callables for the same reason: a Protocol with a single operation and
a single implementer, injected as a lambda that would not structurally satisfy
it anyway, is ceremony that names nothing the type of the argument does not.

**Every dependency is a callable, and that is not decoration.** A mixin method
reads ``self`` late, on each call; a constructor argument reads it once. Step 20
was bitten by exactly this twice in one commit -- ``clock=time.monotonic`` as a
*default argument* bound the function at import, and capturing the owner's
*bound methods* required both memory readers to exist the moment the service was
first touched. So the recorder, the lifecycle, the two view ports, the log and
the memory reads all arrive as zero-argument callables that re-resolve per call,
which is what ``self.<name>`` did. ``clock`` defaults to ``None`` and becomes
``lambda: time.monotonic()``, so the module-global ``time`` lookup still happens
at call time and ``mock.patch("app.vod_capture.time.monotonic")`` still bites.

**What this service does *not* own: the snapshot buffer.** ``vod_snapshots``,
``selected_snapshot_index`` and ``snapshot_pinned`` stay app state, as
``gui_app.py`` has recorded since step 19 and the roadmap re-confirmed for
``player_stats_selected_snapshot_index`` at ``4b0ed07``. Their readers are the
Live Stats tab and ``gui_layout``, not this module, and the tab *writes* two of
them back through a selection callback -- so moving them in here would put a UI
write into a service whose other nine fields are private recording lifecycle.
All three of this module's writes to them were the same semantic act ("a new
recording file begins, discard the previous one's buffer and selection"), so
they collapse into the single injected ``reset_snapshot_buffer`` command. That
collapse is also what empties the ``--clusters`` unowned-state row: this module
stops *writing* ``player_stats_selected_snapshot_index`` and starts *asking*.

``sync_run_state`` is what auto-stops a dead recording, which is why its refresh
task is unconditionally required rather than gated on consumer demand -- see
``app/refresh_tasks.py``.

**Pause is an active run, and the asymmetry here is deliberate.** Core tracking
continues while ``PAUSED_IN_GAME`` but capture does not: ``can_capture_recording``
requires ``IN_GAME`` strictly, and a paused recording reports status
``"paused"`` and writes nothing. Do not 'fix' this into symmetry.

This module renders through ``PlayerStatsView`` and ``RecordingsListView``
(``app/player_stats_view.py``), never through a widget.
``sync_run_state`` used to write the ``player_stats_status_label`` widget
directly -- a Qt write from the app layer, against a label owned by
``ui/tabs/player_stats/live_stats.py`` -- and that is now
``view.set_recording_status_text(...)``, implemented by the mixin that builds
the label.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app import config
from app.player_stats_memory import player_stats_memory
from app.player_stats_view import player_stats_view, recordings_list_view
from app.run_lifecycle import run_lifecycle as resolve_run_lifecycle
from core.game_state import RuntimeGameMode
from core.run_summary import PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS

# Moved here from gui_styles.py in step 17a; this module is its only consumer.
PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS = 20


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

    A module-level function rather than the ``staticmethod`` it was: it reads
    nothing off the service, and a free function has no class to be orphaned
    from -- the failure mode ``test_componentization_inventory`` ratchets, and
    the one that stranded the Chaos Tome panel for two commits at 14b.
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


class VodCapture:
    """The recording lifecycle, constructible without Qt or ``MegabonkApp``.

    The nine fields below were nine names on the shared ``self``, initialised in
    ``MegabonkApp.__init__``. They keep their old spellings deliberately: the
    differential trace and the mutation harness both anchor on them, and
    renaming state that is not moving between owners would cost a re-proof for
    no gain. The *methods* did lose their ``_player_stats_`` prefixes, because
    three of them are called from outside this module and a service named
    ``VodCapture`` with a private-looking ``_is_player_stats_recording_armed``
    is the half-converted shape this step exists to remove.

    ``player_stats_recording_stage_index`` is the one field that was **not**
    initialised in ``MegabonkApp.__init__`` -- it was only ever assigned by
    start/stop, and every read of it sits behind ``is_recording``, so the
    uninitialised path was unreachable. It is initialised to ``None`` here,
    which is what start and stop already set it to. That is a deliberate,
    tiny widening: on the old shape an unreachable read would have fallen
    through ``MegabonkApp.__getattr__`` to the window and raised.
    """

    def __init__(
        self,
        *,
        recorder: Callable[[], Any],
        read_recording_state: Callable[[], Any],
        read_run_timer: Callable[[], float | None],
        close_game_data_client: Callable[[], None],
        run_lifecycle: Callable[[], Any],
        refresh_now: Callable[..., Any],
        player_stats_view: Callable[[], Any],
        recordings_list_view: Callable[[], Any],
        is_live_stats_tab_active: Callable[[], bool],
        log: Callable[..., None],
        reset_snapshot_buffer: Callable[[], None],
        read_character_identity: Callable[[], tuple[int, str] | None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._recorder = recorder
        self._read_recording_state = read_recording_state
        self._read_run_timer = read_run_timer
        self._close_game_data_client = close_game_data_client
        self._run_lifecycle = run_lifecycle
        self._refresh_now = refresh_now
        self._player_stats_view = player_stats_view
        self._recordings_list_view = recordings_list_view
        self._is_live_stats_tab_active = is_live_stats_tab_active
        self._log = log
        self._reset_snapshot_buffer = reset_snapshot_buffer
        self._read_character_identity = read_character_identity or (lambda: None)
        # Not `clock=time.monotonic` in the signature: a default argument binds
        # the function at import, where the code this replaces looked `time` up
        # on the module every call. Step 20 shipped that bug once already.
        self._clock = clock if clock is not None else (lambda: time.monotonic())

        self.player_stats_recording_armed = False
        self.player_stats_recording_waiting_mode = None
        self.player_stats_auto_recording_suppressed = False
        self.player_stats_recording_seed = None
        self.player_stats_recording_stage_ptr = 0
        self.player_stats_recording_stage_index = None
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = None
        self.player_stats_auto_start_detection_streak = 0

    # -- read-only views the UI needs -------------------------------------

    @property
    def recording_waiting_mode(self):
        """What the Live Stats tab shows while a recording is armed but idle.

        ``gui_layout`` read this off the shared ``self`` behind a ``getattr``
        default. The service always has the field, so the default is gone --
        which is the point: a missing value is now a loud ``AttributeError``
        rather than a silent "not waiting".
        """
        return self.player_stats_recording_waiting_mode

    def is_recording_armed(self) -> bool:
        auto_recording_enabled = bool(getattr(config, "AUTO_START_RECORDING", False))
        return bool(self.player_stats_recording_armed) or bool(
            auto_recording_enabled and not self.player_stats_auto_recording_suppressed
        )

    def clear_auto_recording_suppression(self) -> None:
        """Settings just turned ``AUTO_START_RECORDING`` back on.

        ``gui_dialogs.py`` did this by assigning the flag on the app behind
        ``hasattr(self.master, "player_stats_auto_recording_suppressed")``.
        That site is in no step-20 inventory -- not the brief's, not
        ``--clusters`` (which scans only the five app modules), not
        ``test_view_ports`` (which scans only ``app/``). It is the step-19
        blind spot exactly: after this conversion the ``hasattr`` would have
        gone **quietly false**, and re-enabling auto-start in Settings would
        have silently failed to clear a suppression left by a manual stop --
        no exception, no failing test, no trace difference. The user-visible
        symptom would have been "auto-record is on and does nothing until I
        restart".
        """
        self.player_stats_auto_recording_suppressed = False

    # -- the recording lifecycle ------------------------------------------

    def toggle_recording(self):
        recorder = self._recorder()
        if recorder.is_recording or self.is_recording_armed():
            self.player_stats_recording_armed = False
            self.player_stats_recording_waiting_mode = None
            if bool(getattr(config, "AUTO_START_RECORDING", False)):
                self.player_stats_auto_recording_suppressed = True
            self.stop_recording(log_message="[*] Player stats recording stopped.")
        else:
            self.player_stats_recording_armed = True
            self.player_stats_auto_recording_suppressed = False
            state = self._read_recording_state()
            seed = state.map_seed if state is not None else None
            stage_ptr = state.current_stage_ptr if state is not None else 0
            stage_index = state.stage_index if state is not None else None
            run_time_seconds = self._read_run_timer()
            runtime_state = self._run_lifecycle().state_or_unknown()
            if runtime_state.mode is RuntimeGameMode.IN_GAME:
                try:
                    vod_path = self.start_recording(
                        seed=seed,
                        stage_ptr=stage_ptr,
                        stage_index=stage_index,
                        run_time_seconds=run_time_seconds,
                    )
                except Exception as exc:
                    # This is a Qt button callback. A read-only directory, full
                    # disk, or failed metadata flush must become visible state,
                    # not an exception escaping the signal into Qt.
                    self.player_stats_recording_armed = False
                    self.player_stats_recording_waiting_mode = None
                    self._log(
                        f"Could not start player stats recording: {exc}",
                        tag="error",
                    )
                    self._player_stats_view().set_recording_status_text(
                        f"Could not start recording: {exc}"
                    )
                    self._player_stats_view().refresh_player_stats_timeline_ui()
                    return
                self._log(f"[*] Player stats recording started: {vod_path.name}", tag="success")
            else:
                self.player_stats_recording_waiting_mode = runtime_state.mode.value
                self._log(
                    "[*] Player stats recording armed; waiting for an active run.",
                    tag="success",
                )
            self._refresh_now(
                waiting_status_text="Recording stats; waiting for game/player stats...",
                unavailable_status_prefix="Recording stats; player stats unavailable",
            )
            self._recordings_list_view()._refresh_vods_list_if_visible()

        self._player_stats_view().refresh_player_stats_timeline_ui()

    def start_recording(
        self,
        *,
        seed: int | None = None,
        stage_ptr: int = 0,
        stage_index: int | None = None,
        run_time_seconds: float | None = None,
    ):
        identity = None
        try:
            identity = self._read_character_identity()
        except Exception:
            identity = None
        if identity is None:
            vod_path = self._recorder().start(seed=seed)
        else:
            character_id, character_name = identity
            vod_path = self._recorder().start(
                seed=seed,
                character_id=character_id,
                character_name=character_name,
            )
        self._reset_snapshot_buffer()
        self.player_stats_recording_seed = seed
        self.player_stats_recording_stage_ptr = stage_ptr
        self.player_stats_recording_stage_index = stage_index
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = run_time_seconds
        self.player_stats_recording_waiting_mode = None
        self.player_stats_auto_recording_suppressed = False
        self.player_stats_auto_start_detection_streak = 0
        return vod_path

    def stop_recording(
        self,
        *,
        log_message: str | None = None,
        log_tag: str | None = None,
        refresh_live_stats: bool = True,
        finalize_snapshot: bool = True,
    ) -> None:
        recorder = self._recorder()
        if finalize_snapshot and recorder.is_recording:
            try:
                self._refresh_now(finalize_recording_capture=True)
            except Exception:
                # Stopping must remain reliable even if the process disappears
                # before the last best-effort memory snapshot can be built.
                pass
        stop_error = None
        try:
            recorder.stop()
        except Exception as exc:
            stop_error = exc
            try:
                recorder.is_recording = False
            except Exception:
                pass
        finally:
            # Recorder.stop() can fail while flushing a summary or closing a
            # full/removed file. The logical recording still has to end, or
            # every later refresh keeps treating a broken writer as active.
            self._reset_snapshot_buffer()
            self.player_stats_recording_seed = None
            self.player_stats_recording_stage_ptr = 0
            self.player_stats_recording_stage_index = None
            self.player_stats_recording_seed_missing_since = None
            self.player_stats_recording_run_time_seconds = None
            self.player_stats_recording_waiting_mode = None
            self.player_stats_auto_start_detection_streak = 0
            self._close_game_data_client()
        if stop_error is not None:
            self._log(
                f"Could not finalize player stats recording: {stop_error}",
                tag="error",
            )
        elif log_message:
            self._log(log_message, tag=log_tag)
        if refresh_live_stats:
            self._refresh_now()
            if stop_error is not None:
                self._player_stats_view().set_recording_status_text(
                    f"Recording stopped, but the file could not be finalized: {stop_error}"
                )
        self._recordings_list_view()._refresh_vods_list_if_visible()

    def sync_run_state(self, context=None) -> str | None:
        """``context`` is the current ``RefreshTickContext`` when this runs from
        the ``recording_lifecycle`` task, and ``None`` off-tick.

        It reaches the injected `_read_run_timer` reader, which is called from
        three places: `toggle_recording` (:262, a user action and therefore
        genuinely off-tick, so it keeps passing nothing), and the two
        auto-start paths below, both of which are only ever reached from this
        method and so carry the pass down (section 12.8, 28c commit 2).
        """
        # Reuses the lifecycle state the 500 ms driver already refreshes once a
        # second, rather than issuing its own uncached get_runtime_game_state().
        # At this task's old 10 s cadence that extra heavy read was affordable;
        # at 1 s it would be ten times a second, for a mode the cheaper cached
        # reader computes identically (verified exhaustively -- the extra
        # `and not is_game_over` in get_runtime_game_state is unreachable).
        # Only `.mode` is used here, which is all the cached state carries.
        lifecycle = self._run_lifecycle()
        runtime_state = lifecycle.state_for_refresh(context)
        recorder = self._recorder()
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
            if was_paused and recorder.is_recording:
                self._player_stats_view().refresh_player_stats_timeline_ui()
                if self._is_live_stats_tab_active():
                    self._player_stats_view().set_recording_status_text("Live player stats (recording)")
            if self.is_recording_armed() and not recorder.is_recording:
                current_state = self._read_recording_state(context)
                current_seed = current_state.map_seed if current_state is not None else None
                current_stage_ptr = (
                    current_state.current_stage_ptr if current_state is not None else 0
                )
                current_stage_index = (
                    getattr(current_state, "stage_index", None) if current_state is not None else None
                )
                current_run_time_seconds = self._read_run_timer(context)
                vod_path = self.start_recording(
                    seed=current_seed,
                    stage_ptr=current_stage_ptr,
                    stage_index=current_stage_index,
                    run_time_seconds=current_run_time_seconds,
                )
                self._log(
                    f"[*] Player stats recording started from waiting mode: {vod_path.name}",
                    tag="success",
                )
                self._player_stats_view().refresh_player_stats_timeline_ui()
                return "started"

        if not recorder.is_recording:
            return None

        if runtime_state.mode is RuntimeGameMode.PAUSED_IN_GAME:
            was_paused = self.player_stats_recording_waiting_mode == runtime_state.mode.value
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            if not was_paused:
                self._player_stats_view().refresh_player_stats_timeline_ui()
                if self._is_live_stats_tab_active():
                    self._player_stats_view().set_recording_status_text("Live player stats (recording paused)")
            return "paused"
        if runtime_state.mode in {RuntimeGameMode.GAME_OVER, RuntimeGameMode.MAIN_MENU}:
            mode_text = "game over" if runtime_state.mode is RuntimeGameMode.GAME_OVER else "main menu"
            should_remain_armed = self.is_recording_armed()
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            self.stop_recording(
                log_message=f"[*] Player stats recording waiting: {mode_text}.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            if not should_remain_armed:
                self.player_stats_recording_armed = False
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            self._player_stats_view().refresh_player_stats_timeline_ui()
            return "waiting"
        if runtime_state.mode is RuntimeGameMode.UNKNOWN:
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            return None

        now = self._clock()
        current_state = self._read_recording_state(context)
        current_seed = current_state.map_seed if current_state is not None else None
        current_stage_ptr = (
            current_state.current_stage_ptr if current_state is not None else 0
        )
        current_stage_index = (
            getattr(current_state, "stage_index", None) if current_state is not None else None
        )
        current_run_time_seconds = self._read_run_timer(context)
        if current_seed is None:
            if self.player_stats_recording_seed_missing_since is None:
                self.player_stats_recording_seed_missing_since = now
                return None
            if now - self.player_stats_recording_seed_missing_since < PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS:
                return None
            self.player_stats_recording_armed = False
            self.stop_recording(
                log_message="[*] Player stats recording auto-stopped: run seed disappeared.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            self._player_stats_view().refresh_player_stats_timeline_ui()
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
        decision = _stage_index_signals_new_run(
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

        # The state already belongs to the new run. Capturing it before the
        # split would append the new run's first sample to the old JSONL.
        self.stop_recording(
            refresh_live_stats=False,
            finalize_snapshot=False,
        )
        vod_path = self.start_recording(
            seed=current_seed,
            stage_ptr=current_stage_ptr,
            stage_index=current_stage_index,
            run_time_seconds=current_run_time_seconds,
        )
        self._log(
            f"[*] Player stats recording auto-split: seed {previous_seed} -> {current_seed}; new file {vod_path.name}",
            tag="success",
        )
        self._player_stats_view().refresh_player_stats_timeline_ui()
        return "split"

    def note_run_not_in_game(self) -> None:
        """The run is not IN_GAME this tick, so the auto-start streak restarts.

        Was `app/player_stats_refresh.py` assigning
        `self.player_stats_auto_start_detection_streak = 0` directly. That
        counter is this module's -- every other read and write of it is here,
        and `maybe_auto_start` is the only thing that interprets it -- so the
        refresh tick was reaching across a boundary to reset another feature's
        state.

        Worth noting what the headline metric says about this change: it says
        it made things *worse*. `arch_metrics` scores a write as "owned" and a
        method call as a hidden read, so trading the assignment for this call
        moved `app/player_stats_refresh.py` from 10 to 11. That is the same
        blind spot `test_mixin_attribute_collisions.py` was written for --
        "a collision looks like good hygiene to that metric, because the file
        that reads them also assigns them". Writing another service's state is
        strictly worse than calling its method, and the cluster scan
        (`tools/step20_metrics.py --clusters`) is the measure that says so:
        unowned state 2 -> 1. This conversion takes it to 0.
        """
        self.player_stats_auto_start_detection_streak = 0

    def maybe_auto_start(
        self,
        *,
        stats,
        run_timer_seconds: float | None,
        player_level: int | None,
        map_seed: int | None,
        stage_ptr: int,
        stage_index: int | None = None,
    ) -> bool:
        if self._recorder().is_recording:
            self.player_stats_auto_start_detection_streak = 0
            return False
        if bool(self.player_stats_auto_recording_suppressed):
            self.player_stats_auto_start_detection_streak = 0
            return False
        if not bool(getattr(config, "AUTO_START_RECORDING", False)):
            self.player_stats_auto_start_detection_streak = 0
            return False
        if not _looks_like_active_run_for_auto_recording(
            stats=stats,
            run_timer_seconds=run_timer_seconds,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
        ):
            self.player_stats_auto_start_detection_streak = 0
            return False

        self.player_stats_auto_start_detection_streak = int(
            self.player_stats_auto_start_detection_streak
        ) + 1
        if self.player_stats_auto_start_detection_streak < 2:
            return False

        vod_path = self.start_recording(
            seed=map_seed,
            stage_ptr=stage_ptr,
            stage_index=stage_index,
            run_time_seconds=run_timer_seconds,
        )
        self._log(f"[*] Player stats recording auto-started: {vod_path.name}", tag="success")
        return True


def _reset_owner_snapshot_buffer(owner) -> None:
    """Discard the app-owned snapshot buffer and selection for a new file.

    The owner keeps these three names -- see the class docstring for why they
    did not move -- so the service asks rather than writes.
    """
    owner.player_stats_vod_snapshots = []
    owner.player_stats_selected_snapshot_index = None
    owner.player_stats_snapshot_pinned = False


def _read_owner_character_identity(owner) -> tuple[int, str] | None:
    # Recording can start from the armed/waiting state before the first full
    # snapshot resets the previous run. Read the active process first so a
    # cached Dice snapshot cannot name a new Fox recording. The tracker remains
    # a best-effort fallback for a transient start-time memory failure.
    try:
        memory = player_stats_memory(owner)
        client = memory._get_player_stats_client()
        owner_stats = client.resolve_owner_stats()
        identity_reader = getattr(client, "get_character_identity", None)
        if callable(identity_reader):
            character_id, character_name = identity_reader(owner_stats)
        else:
            reading = client.get_character_passive_reading(owner_stats)
            character_id = reading.character_id
            character_name = reading.character_name
        if int(character_id) >= 0 and str(character_name).strip():
            return int(character_id), str(character_name).strip()
    except Exception:
        pass

    tracker = getattr(owner, "live_run_tracker", None)
    snapshot_reader = getattr(tracker, "character_passive_snapshot", None)
    if callable(snapshot_reader):
        snapshot = snapshot_reader()
        if snapshot is not None and int(getattr(snapshot, "character_id", -1)) >= 0:
            name = str(getattr(snapshot, "character_name", "") or "").strip()
            if name:
                return int(snapshot.character_id), name
    return None


def vod_capture(owner) -> VodCapture:
    """Resolve the owner's ``VodCapture``, building it on first use.

    The same shape as ``run_lifecycle`` in ``app/run_lifecycle.py`` and
    ``ensure_refresh_coordinator`` in ``app/refresh_tasks.py``, and for the same
    reason: the service's dependencies are the owner's memory readers, view
    ports and log, so ``AppCoordinator`` cannot construct it in its own
    ``__init__``. The coordinator caches it when there is one; an app double
    built with ``object.__new__`` has none and keeps it in ``__dict__``.

    ``__dict__``, not ``getattr``: ``MegabonkApp.__getattr__`` forwards unknown
    names to its ``window``, so a ``getattr`` would consult the widget before
    deciding there is no coordinator.

    Every argument below is a lambda rather than a bound method. Grabbing
    ``owner.log`` here would resolve it once, at whatever moment the service is
    first touched; ``self.log(...)`` resolved it on every call. That difference
    is this conversion's most common silent behaviour change and step 20 has
    already shipped it twice.
    """
    coordinator = owner.__dict__.get("coordinator")
    if coordinator is not None:
        existing = getattr(coordinator, "vod_capture", None)
        if existing is not None:
            return existing

    existing = owner.__dict__.get("_vod_capture")
    if existing is not None:
        return existing

    service = VodCapture(
        recorder=lambda: owner.player_stats_vod_recorder,
        read_recording_state=lambda context=None: player_stats_memory(owner)._read_player_stats_recording_state_safe(context),
        read_run_timer=lambda context=None: player_stats_memory(owner)._read_player_stats_recording_run_timer_safe(context),
        close_game_data_client=lambda: player_stats_memory(owner).close_player_stats_game_data_client(),
        run_lifecycle=lambda: resolve_run_lifecycle(owner),
        refresh_now=lambda **kwargs: owner.refresh_live_player_stats_now(**kwargs),
        player_stats_view=lambda: player_stats_view(owner),
        recordings_list_view=lambda: recordings_list_view(owner),
        is_live_stats_tab_active=lambda: owner._is_live_stats_tab_active(),
        log=lambda message, tag=None: owner.log(message, tag=tag),
        reset_snapshot_buffer=lambda: _reset_owner_snapshot_buffer(owner),
        read_character_identity=lambda: _read_owner_character_identity(owner),
    )
    if coordinator is not None:
        coordinator.vod_capture = service
    else:
        owner.__dict__["_vod_capture"] = service
    return service
