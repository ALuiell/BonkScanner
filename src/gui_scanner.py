"""The scan worker, its cancellation, and the Session Stats tab.

Step 25 took `ScannerMixin` off `MegabonkApp`. This object owns the whole scan
lifecycle -- the worker thread, both events, the two run flags, the session
counters and the tab that displays them -- and that concentration is the point
of the step rather than a side effect of it.

Cancellation is two `threading.Event`s and one predicate:

* `stop_event` ends the run. One writer, always.
* `scan_event` gates it. Two writers: this class, and the pause/resume hotkey
  -- which is `toggle_scan_event` below, moved here from `RunControlMixin`
  because it writes `is_running` and reads `is_ready_to_start` and
  `scanner_thread`, i.e. four pieces of scan lifecycle and nothing else.
* `_scan_abort_requested()` is `stop_event.is_set() or not scan_event.is_set()`.
  Before step 25 that expression was also written out by hand in three other
  places -- twice inside `wait_for_game_window_focus` and once in the loop's
  `abort_condition` lambda. `RunControl` now asks this predicate through a
  port, so there is one definition of "the scan was cancelled".

The worker remains `daemon=True` for process-level resilience, but shutdown now
joins it after setting both events.  Python 3.12 can abort during interpreter
finalization when a daemon thread is still executing Python or writing an
exception, so "the loop was asked to stop" is not a sufficient lifecycle
boundary. Every blocking call takes the abort predicate; the soft wait is only
diagnostic and the final join guarantees the interpreter never inherits it.
"""
from __future__ import annotations

import datetime
import threading
import time
from typing import Any, Callable

from app import config
from infra.crash_journal import log_runtime_event
from app.map_scoring import calculate_map_score, evaluate_candidate, format_stats
from ui.tabs.session_stats import SessionStatsTab
from app.player_stats_view import player_stats_view
from app.template_filters import TemplateRuntimeFilters
# Top-level, not deferred into the builder. `gui_dialogs` imports nothing from
# here, so there is no cycle to dodge, and a function-body import is invisible
# to pyflakes and to every test that does not take that branch -- which is how
# step 21 shipped a startup crash.
from ui.dialogs import ObsRecordingReminderDialog, RerollWarningDialog
from gui_run_control import RunControl
from infra.memory.game_data_client import GameDataClient
from core.template_colors import (
    DEFAULT_TEMPLATE_COLOR,
    template_color_hex,
    template_color_tag,
)
from core.template_conditions import format_template_conditions
from ui.styles import _set_widget_style_role
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from core.run_control import RunControlError
from core.runtime_stats import adapt_map_stats


class Scanner:
    _TOTAL_REROLLS_FLUSH_INTERVAL = 15.0

    def __init__(
        self,
        coordinator: Any,
        *,
        run_control: RunControl,
        filters: TemplateRuntimeFilters,
        schedule: Callable[[int, Callable[[], None]], None],
        can_log: Callable[[], bool],
        log_box: Callable[[], Any],
        status_label: Callable[[], Any],
        toggle_btn: Callable[[], Any],
        add_tab: Callable[[Any, str], None],
        refresh_session_stats_snapshot: Callable[[], None],
        refresh_session_tracked_item_stats_ui: Callable[[], None],
        open_tracked_item_settings_dialog: Callable[[], None],
        is_recording: Callable[[], bool],
        refresh_timeline: Callable[[], None],
        is_shutting_down: Callable[[], bool],
        reroll_warning_dialog: Callable[[], Any],
        obs_reminder_dialog: Callable[[], Any],
    ) -> None:
        self._coordinator = coordinator
        self._run_control = run_control
        self._filters = filters
        self._schedule = schedule
        self._can_log = can_log
        self._log_box = log_box
        self._status_label = status_label
        self._toggle_btn = toggle_btn
        self._add_tab = add_tab
        self._refresh_session_stats_snapshot = refresh_session_stats_snapshot
        self._refresh_session_tracked_item_stats_ui = refresh_session_tracked_item_stats_ui
        self._open_tracked_item_settings_dialog = open_tracked_item_settings_dialog
        self._is_recording = is_recording
        self._refresh_timeline = refresh_timeline
        self._is_shutting_down = is_shutting_down
        self._reroll_warning_dialog = reroll_warning_dialog
        self._obs_reminder_dialog = obs_reminder_dialog

        # Scan lifecycle. All seven were slots on the shared `MegabonkApp`
        # namespace; `gui_app.__init__` no longer declares any of them.
        self.stop_event = threading.Event()
        self.scan_event = threading.Event()
        self.scanner_thread: threading.Thread | None = None
        self.is_running = False
        self.is_ready_to_start = False
        self.pause_reason: str | None = None
        self._restart_lock = threading.Lock()
        self.obs_recording_reminder_shown = False

        # Session counters, read by the tab below and by `SessionStats`.
        self.session_start_time = None
        self.session_rerolls = 0
        self.best_map_stats = None
        self.best_map_score = -1
        self.worst_map_stats = None
        self.worst_map_score = float("inf")

        self._total_rerolls_dirty = False
        self._total_rerolls_last_flush = time.monotonic()
        self._total_rerolls_lock = threading.Lock()

        # Session Stats tab. `None` until `build_session_stats_tab` runs, the
        # same contract `gui_app` held for these ten slots -- `gui_layout`
        # builds the tab well after the component is constructed, and the
        # overlay reads two of them through ports that must tolerate that.
        self.tab_stats = None
        # The tab is a view object now (`ui/tabs/session_stats.py`); the eleven
        # widget slots that were here are its. `stats_avg_layout` survives as a
        # plain flag because two callers outside this file -- `gui_app`'s
        # `refresh_stats` port and `tests/support/template_filters` -- use it to
        # ask "has the tab been built yet", and that question is still real.
        self._stats_view = None
        self.stats_avg_layout = None

    # The scan client is `AppCoordinator`'s (step 12b) and `MegabonkApp`
    # exposes the same one (step 25a). This reads and writes the same field on
    # the same coordinator, so "the app's client" and "the scanner's client"
    # are one value, not two that have to be kept in step.
    @property
    def client(self):
        return self._coordinator.client

    @client.setter
    def client(self, value) -> None:
        self._coordinator.client = value

    # Both are `TemplateRuntimeFilters`' fields (step 22b), which is why the
    # scanner needed no edit when they left the shared namespace. They are
    # delegating properties here for the same reason they are on `MegabonkApp`:
    # the reads and writes below are the ones 22b measured, and pointing them
    # at the owner rather than restating `self._filters.x` at each site keeps
    # this file honest about who holds the value.
    @property
    def active_templates(self):
        return self._filters.active_templates

    @active_templates.setter
    def active_templates(self, value) -> None:
        self._filters.active_templates = value

    @property
    def template_stats(self):
        return self._filters.template_stats

    @template_stats.setter
    def template_stats(self, value) -> None:
        self._filters.template_stats = value

    def is_scanning(self) -> bool:
        return self.scanner_thread is not None and self.scanner_thread.is_alive()

    def _flush_total_rerolls(self, *, force: bool = False) -> None:
        with self._total_rerolls_lock:
            if not self._total_rerolls_dirty:
                return
            now = time.monotonic()
            if not force and now - self._total_rerolls_last_flush < self._TOTAL_REROLLS_FLUSH_INTERVAL:
                return
            try:
                config.save_config(config.user_config)
            except Exception as exc:
                self.log(f"[-] Could not save Total Rerolls: {exc}", tag="warning")
                return
            self._total_rerolls_dirty = False
            self._total_rerolls_last_flush = now

    def _scan_abort_requested(self) -> bool:
        return self.stop_event.is_set() or not self.scan_event.is_set()

    def handle_player_movement(self) -> None:
        """Pause an active scan after W/A/S/D/Space in the game window.

        The keyboard hook calls this independently of the scanner worker.  Do
        not gate it on map readiness: at fast reset speeds, most of the useful
        safety window is while the worker is still waiting for the next map.
        Sharing the restart lock with :meth:`reroll_map` makes movement and the
        final reset decision atomic with respect to one another.
        """
        if not getattr(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", True):
            return

        with self._restart_lock:
            if (
                not self.is_running
                or not self.scan_event.is_set()
                or not self.is_scanning()
            ):
                return
            self.is_running = False
            self.pause_reason = "player_movement"
            self.scan_event.clear()

        self.log("[SAFETY] Player movement detected. Auto-reroll paused.", tag="warning")
        self._schedule(0, self.update_status_ui)

    def shutdown(self) -> None:
        """The scanner's two steps of `MegabonkApp.on_closing`.

        Setting both events is what releases the worker: `stop_event` ends the
        `while`, `scan_event` unblocks the `wait()` it may be parked in. The
        flush is forced because the 15s throttle would otherwise drop a reroll
        count on the way out.
        """
        self.stop_event.set()
        self.scan_event.set()
        self._flush_total_rerolls(force=True)
        worker = self.scanner_thread
        if worker is None or worker is threading.current_thread():
            return
        is_alive = getattr(worker, "is_alive", None)
        join = getattr(worker, "join", None)
        if not callable(is_alive) or not callable(join) or not is_alive():
            return
        started_at = time.monotonic()
        join(timeout=12.0)
        alive_after = bool(is_alive())
        log_runtime_event(
            "scanner.worker.wait",
            running=alive_after,
            elapsed_ms=round((time.monotonic() - started_at) * 1000),
        )
        if alive_after:
            log_runtime_event("scanner.worker.wait_extended")
            join()
            log_runtime_event(
                "scanner.worker.wait_extended_complete",
                running=bool(is_alive()),
                elapsed_ms=round((time.monotonic() - started_at) * 1000),
            )

    def _score_tier_color_tag(self, tier: str) -> str:
        colors = {"Light": "WHITE", "Good": "GREEN", "Perfect": "YELLOW", "Perfect+": "LIGHTRED_EX"}
        return colors.get(tier, DEFAULT_TEMPLATE_COLOR)

    def _log_colored_names(self, prefix: str, names: list[str], color_for_name) -> None:
        colored_parts = [prefix]
        colored_tags = [None]
        for index, name in enumerate(names):
            colored_parts.append(name)
            colored_tags.append(color_for_name(name))
            if index < len(names) - 1:
                colored_parts.append(", ")
                colored_tags.append(None)
        self.log(colored_parts, tag=colored_tags)

    def update_timer(self):
        if self._is_shutting_down():
            return

        elapsed = 0
        rpm = 0.0
        if self.is_scanning() and self.session_start_time:
            elapsed = int(time.time() - self.session_start_time)
            td = datetime.timedelta(seconds=elapsed)
            if elapsed > 0 and self.session_rerolls > 0:
                rpm = (self.session_rerolls / elapsed) * 60
            if self._stats_view is not None:
                self._stats_view.set_session_clock(elapsed_text=str(td), rpm=rpm)

        status_label = self._status_label()
        session_meta = getattr(status_label, "_session_meta_label", None)
        if session_meta is not None:
            hours, remainder = divmod(max(0, elapsed), 3600)
            minutes, seconds = divmod(remainder, 60)
            # Session clock only. RPM was here too and is not any more: it has
            # a full-width line of its own in Session Overview
            # (`stats_rpm_label`), where it is labelled rather than abbreviated,
            # and the header is where the states live rather than the numbers.
            session_meta.setText(
                f"Session {hours:02d}:{minutes:02d}:{seconds:02d}"
            )

        recording = self._is_recording()
        # The header's REC flag, driven from the port that already answers this
        # question -- rather than a second reader of the recorder that could
        # disagree with the timeline strip below it.
        rec_flag = getattr(status_label, "_rec_flag", None)
        if rec_flag is not None:
            rec_flag.set_recording(recording)

        if recording:
            self._refresh_timeline()

        self._flush_total_rerolls()

        self._schedule(1000, self.update_timer)

    def update_status_ui(self):
        status_label = self._status_label()
        toggle_btn = self._toggle_btn()
        if status_label is None or toggle_btn is None:
            return

        if self.is_scanning():
            if self.is_running:
                status_text = "RUNNING"
            elif self.pause_reason == "player_movement":
                status_text = "PAUSED — PLAYER MOVEMENT"
            elif self.pause_reason == "manual":
                status_text = "PAUSED"
            elif self.is_ready_to_start:
                status_text = "ARMED"
            else:
                status_text = "WAITING FOR GAME"
            status_label.setText(status_text)
            _set_widget_style_role(status_label, "statusText", state="running")
            _set_widget_style_role(
                getattr(status_label, "_status_dot", None),
                "statusDot",
                state="running",
            )
            toggle_btn.setText("Stop Scanner")
            _set_widget_style_role(toggle_btn, "stopScanner")
        else:
            status_label.setText("IDLE")
            _set_widget_style_role(status_label, "statusText", state="idle")
            _set_widget_style_role(
                getattr(status_label, "_status_dot", None),
                "statusDot",
                state="idle",
            )
            toggle_btn.setText("Start Scanner")
            _set_widget_style_role(toggle_btn, "primary")

    def _append_log(self, message, tag=None):
        """Hand the line to the Logs panel, message and tag unchanged.

        The colour resolution that used to live here is gone, and with it the
        bug it carried: it looked a scalar tag up in `COLOR_MAP`, which is a
        palette with no `WARNING`, `SUCCESS` or `ERROR` key, so every tagged
        line in the app rendered in the same default grey. Deciding what a tag
        means is the view's now -- see `ui/log_view.parse_log_entry`, which
        keeps the scalar (severity) and list (per-part palette colour) forms
        apart instead of resolving both through one lookup.
        """
        log_box = self._log_box()
        if log_box is None:
            return
        log_box.append_log(message, tag)

    # Fire-and-forget by design, and silent when it cannot post. The guard used
    # to read `hasattr(self, "_invoker")` on the shared namespace; it is a port
    # now, but the shape is deliberately unchanged -- a logger that loses its
    # invoker does not raise, it stops writing, and the only symptom is an empty
    # Logs panel. That is step 19's failure mode, so the trace drives `log`
    # through the real widget and one of the mutations takes the invoker away.
    def log(self, message, tag=None):
        if not self._can_log():
            return
        self._schedule(0, lambda m=message, t=tag: self._append_log(m, t))

    def toggle_scan_event(self):
        """Pause/resume, from the scan hotkey. Was `RunControlMixin`'s."""
        if not self.is_scanning():
            self.log(f"[WAIT] Press Start first, then press {config.HOTKEY.upper()} in game to begin scanning.", tag="warning")
            self.update_status_ui()
            return

        if not self.is_ready_to_start:
            self.log("[WAIT] Scanner is still connecting to the game. Try the hotkey again once it is ARMED.", tag="warning")
            self.update_status_ui()
            return

        if self.is_running:
            self.is_running = False
            self.pause_reason = "manual"
            self.scan_event.clear()
            self.log("[*] Scan paused. Press the scan hotkey again to resume.")
        else:
            self.is_running = True
            self.pause_reason = None
            self.scan_event.set()
            self.log("[*] Scan started. Looking for selected target...")
            # A movement key may already be held when scanning is resumed, so
            # there may be no new key-down edge for the hook to deliver.
            if self._run_control.is_player_movement_pressed():
                self.handle_player_movement()
        self.update_status_ui()

    def _sync_reset_hold_duration(self) -> None:
        """Re-check the game's quick-reset threshold before the worker starts.

        `app.config` reads it once at import, which is often before the game is
        running -- and the game rewrites its own config on exit. Starting a scan
        is the last moment we can notice that the hold went stale, and the run
        control provider reads `config.RESET_HOLD_DURATION` through a lambda, so
        the corrected value applies to the very next reroll.
        """
        notice = config.reset_hold_duration_notice(config.refresh_reset_hold_duration())
        if notice is not None:
            self.log(notice, tag="warning")

    def toggle_main_loop(self):
        if not self.is_scanning():
            if (
                getattr(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", True)
                and not self._run_control.player_movement_guard_available
            ):
                self.log(
                    "[SAFETY] Player-movement guard is unavailable. Auto-reroll was not started.",
                    tag="error",
                )
                self.update_status_ui()
                return
            if not config.user_config.get("SKIP_REROLL_WARNING", False):
                dialog = self._reroll_warning_dialog()
                dialog.exec()
                if not dialog.result:
                    return
                if dialog.dont_show_again:
                    config.user_config["SKIP_REROLL_WARNING"] = True
                    config.save_config(config.user_config)

            if (
                getattr(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False)
                and not self.obs_recording_reminder_shown
            ):
                self.obs_recording_reminder_shown = True
                dialog = self._obs_reminder_dialog()
                dialog.exec()

            self.log(f"\n[*] Starting auto-reroll monitor in {config.EVALUATION_MODE.upper()} mode...")

            if config.EVALUATION_MODE == "templates":
                self.active_templates = self._filters.selected_template_names()
                if not self.active_templates:
                    self.log("[-] Error: You must select at least one template!", tag="error")
                    return
                # Renamed off `template_color_tag` when that became the shared
                # helper this module now imports; a local of the same name
                # would shadow it for the whole function.
                def _color_tag_for_profile(name: str) -> str:
                    for template in config.TEMPLATES:
                        if template["name"] == name:
                            return template_color_tag(template)
                    return DEFAULT_TEMPLATE_COLOR

                self._log_colored_names("[*] Active profiles: ", self.active_templates, _color_tag_for_profile)
                self.template_stats = {name: {"rerolls_since_last": 0, "history": []} for name in self.active_templates}
            else:
                active_tiers = config.SCORES_SYSTEM.get("active_tiers", [])
                if not active_tiers:
                    self.log("[-] Error: No active tiers selected in Scores mode!", tag="error")
                    return
                self._log_colored_names("[*] Active Tiers: ", active_tiers, self._score_tier_color_tag)
                self.template_stats = {name: {"rerolls_since_last": 0, "history": []} for name in active_tiers}

            self._sync_reset_hold_duration()

            self.session_start_time = time.time()
            self.session_rerolls = 0
            self.best_map_stats = None
            self.best_map_score = -1
            self.worst_map_stats = None
            self.worst_map_score = float("inf")
            self.refresh_stats_ui()

            self.is_running = False
            self.is_ready_to_start = False
            self.pause_reason = None
            self.scan_event.clear()
            self.stop_event.clear()
            self.scanner_thread = threading.Thread(
                target=self.background_loop,
                name="BonkScannerWorker",
                daemon=True,
            )
            self.scanner_thread.start()
            self._filters.sync()
            self.update_status_ui()
        else:
            # The stop path is `shutdown()`'s two events plus the forced flush,
            # so it is the same call: one definition of "release the worker".
            self.shutdown()
            self.is_running = False
            self.is_ready_to_start = False
            self.pause_reason = None
            self.log("\n[*] Stopping auto-reroll monitor...")
            self._schedule(500, self.update_status_ui)

    def refresh_stats_ui(self):
        # Both were `hasattr`-guarded on the shared namespace, for app doubles
        # that carried neither. They are ports now and always present; each one
        # already answers "no owner" internally on the app side, which is where
        # that decision belongs.
        self._refresh_session_stats_snapshot()
        view = self._stats_view
        if view is None:
            return
        view.set_counters(
            rerolls=self.session_rerolls,
            seeds_found=self._session_seed_count(),
            all_time_rerolls=config.TOTAL_REROLLS,
        )
        self._refresh_session_tracked_item_stats_ui()
        view.set_map_highlights(
            best_stats=self.best_map_stats,
            worst_stats=self.worst_map_stats,
            active_templates=self.active_templates,
        )
        view.set_average_rows(self._average_reroll_rows())

    def _session_seed_count(self) -> int:
        """How many seeds the session has found.

        Read off `template_stats` the same way `SessionStats.found_seed_count`
        does, rather than through that object: the scanner owns this dict and
        already holds it, and the KPI must not depend on whether the session
        stats snapshot has been refreshed yet this tick.
        """
        total = 0
        for data in self.template_stats.values():
            if not isinstance(data, dict):
                continue
            history = data.get("history")
            if isinstance(history, (list, tuple)):
                total += len(history)
        return total

    def _average_reroll_rows(self) -> list[tuple]:
        """`(name, colour, average, found)` per active target, ready to render.

        The colour rule is the one the old labels used: a template's own colour
        in templates mode, the tier's colour in scores mode. It stays here
        because both sources are `config`, which the view does not read.
        """
        rows = []
        for name, data in self.template_stats.items():
            color_tag = "BLUE"
            if config.EVALUATION_MODE == "templates":
                for template in config.TEMPLATES:
                    if template["name"] == name:
                        color_tag = template_color_tag(template)
                        break
            else:
                color_tag = self._score_tier_color_tag(name)
            history = data.get("history") or ()
            average = (sum(history) / len(history)) if history else 0.0
            rows.append(
                (
                    name,
                    template_color_hex(color_tag),
                    average,
                    len(history),
                )
            )
        return rows

    def log_reroll_stats(self):
        self.session_rerolls += 1
        config.TOTAL_REROLLS += 1
        config.user_config["TOTAL_REROLLS"] = config.TOTAL_REROLLS
        self._total_rerolls_dirty = True
        self._flush_total_rerolls()

        for name in list(self.template_stats):
            self.template_stats[name]["rerolls_since_last"] += 1

        # Integrations read this thread-safe session snapshot instead of UI
        # state, so it must be updated independently of the throttled repaint.
        self._refresh_session_stats_snapshot()

        if self.session_rerolls % 5 == 0:
            self._schedule(0, self.refresh_stats_ui)

    def log_target_found(self, template_name: str):
        if template_name in self.template_stats:
            data = self.template_stats[template_name]
            attempts = data["rerolls_since_last"] if data["rerolls_since_last"] > 0 else 1
            data["history"].append(attempts)
            data["rerolls_since_last"] = 0
        self._schedule(0, self.refresh_stats_ui)

    def check_best_map(self, stats: dict):
        score = calculate_map_score(stats)
        if score > self.best_map_score:
            self.best_map_score = score
            self.best_map_stats = stats
            self._schedule(0, self.refresh_stats_ui)

    def check_worst_map(self, stats: dict):
        score = calculate_map_score(stats)
        if score < self.worst_map_score:
            self.worst_map_score = score
            self.worst_map_stats = stats
            self._schedule(0, self.refresh_stats_ui)

    def reroll_map(self) -> bool:
        if self._run_control.run_control_provider is None:
            self.log("[-] Run control provider is not available; cannot restart run.", tag="error")
            return False

        with self._restart_lock:
            if self._scan_abort_requested():
                return False

            try:
                self._run_control.run_control_provider.restart_run()
            except RunControlError as exc:
                self.log(f"[-] {exc}", tag="error")
                return False

        self.log_reroll_stats()
        return True

    def close_client(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def _disconnect_stale_scanner_client(self, process_name: str) -> bool:
        attached_process_id = self._run_control.attached_game_process_id()
        foreground_process_id = self._run_control.foreground_game_process_id(process_name)
        if (
            attached_process_id is None
            or foreground_process_id is None
            or attached_process_id == foreground_process_id
        ):
            return False

        self.log(
            f"[*] Game process changed ({attached_process_id} -> {foreground_process_id}). Reconnecting scanner...",
            tag="warning",
        )
        self.close_client()
        self.is_ready_to_start = False
        self._schedule(0, self.update_status_ui)
        return True

    def background_loop(self):
        process_name = config.PROCESS_NAME.strip()
        wait_state = None
        last_state = None
        last_stats = None
        is_first_scan = True

        while not self.stop_event.is_set():
            if self.client is None:
                try:
                    self.client = GameDataClient(process_name=process_name)
                    self.log(f"[+] Game connected! Press '{config.HOTKEY}' to start auto-reroll.", tag="success")
                    self.is_ready_to_start = True
                    self._schedule(0, self.update_status_ui)
                except ProcessNotFoundError:
                    if wait_state != "process":
                        self.log(f"[WAIT] Waiting for process '{process_name}'...", tag="warning")
                        wait_state = "process"
                        self._schedule(0, self.update_status_ui)
                    time.sleep(1)
                    continue
                except ModuleNotFoundError:
                    if wait_state != "module":
                        self.log("[WAIT] Game found. Waiting for it to finish loading...", tag="warning")
                        wait_state = "module"
                        self._schedule(0, self.update_status_ui)
                    time.sleep(1)
                    continue

            was_waiting = not self.scan_event.is_set()
            self.scan_event.wait()
            if was_waiting:
                is_first_scan = True
                last_state = None
                last_stats = None

            if self.stop_event.is_set():
                break

            try:
                focus_was_active = self._run_control.is_game_window_active(process_name)
                if not self._run_control.wait_for_game_window_focus(process_name):
                    continue
                if self._disconnect_stale_scanner_client(process_name):
                    is_first_scan = True
                    wait_state = None
                    last_state = None
                    last_stats = None
                    continue
                if not focus_was_active:
                    is_first_scan = True
                    last_state = None
                    last_stats = None

                try:
                    raw_stats = self.client.wait_for_map_ready(
                        previous_state=last_state,
                        previous_stats=last_stats,
                        require_change=not is_first_scan,
                        abort_condition=lambda: self._scan_abort_requested() or not self._run_control.is_game_window_active(process_name),
                        timeout=10.0,
                    )
                except InterruptedError:
                    continue

                if self._scan_abort_requested():
                    continue
                is_first_scan = False
                # `wait_for_map_ready` captured this state in the same strict
                # sample that confirmed the stats. Re-reading through the
                # optional UI projection can turn a transient memory error into
                # an empty baseline, after which teardown stats look like a new
                # map on the next cycle.
                last_state = getattr(self.client, "last_ready_state", None)
                if last_state is None:
                    last_state = self.client.get_map_generation_state()
                last_stats = raw_stats
                stats = adapt_map_stats(raw_stats)
                eval_context = {
                    "supports_bald_heads": stats.get("Chests", 0) >= 69,
                }

                self.check_best_map(stats)
                self.check_worst_map(stats)
                candidate = evaluate_candidate(stats, self.active_templates, context=eval_context)

                if self._scan_abort_requested():
                    continue

                if candidate is not None:
                    if not self._run_control.wait_for_game_window_focus(process_name):
                        continue
                    if self._scan_abort_requested():
                        continue

                    t_name = candidate.get("name")
                    t_color = template_color_tag(candidate)
                    score_text = (
                        f" (Score: {candidate.get('score', 0):.1f})"
                        if config.EVALUATION_MODE == "scores"
                        else ""
                    )
                    condition_text = (
                        f" ({format_template_conditions(candidate)})"
                        if config.EVALUATION_MODE == "templates"
                        else ""
                    )
                    self.log(
                        [
                            "\n[$$$] TARGET MAP FOUND! Profile: ",
                            f"{t_name}{condition_text}{score_text}",
                        ],
                        tag=["success", t_color],
                    )
                    self.log(f"Map Stats: {format_stats(stats, self.active_templates)}", tag="success")
                    self.log_target_found(t_name)

                    if not self._run_control.handle_confirmed_target_window(process_name):
                        continue

                    self.is_running = False
                    self.pause_reason = None
                    self.scan_event.clear()
                    self._schedule(0, self.update_status_ui)
                    continue
                else:
                    self.log(f"Stats: {format_stats(stats, self.active_templates)}")

                if not self._run_control.wait_for_game_window_focus(process_name):
                    continue

                self.reroll_map()

            except TimeoutError as exc:
                # `wait_for_map_ready` spells out *which* readiness gate never
                # opened -- change_seen/generation_seen separate "the reset key
                # was never accepted by the game" from "the map really is slow
                # to load", and those two have opposite fixes. Logging only the
                # headline threw that away and made the bug unreportable.
                self.log("[-] Map took too long to load.", tag="warning")
                self.log(f"    {exc}", tag="warning")
                self.log(
                    "[*] Retrying the current map without restarting so it cannot be skipped...",
                    tag="warning",
                )
                # A timeout is ambiguous: the reset may have failed, or a new
                # map may already be loaded while one memory field is briefly
                # unreadable. Treat the current map as a first scan again. If
                # it is the old map, it is harmlessly re-evaluated before the
                # next reset; if it is new, it gets the evaluation the timeout
                # could not complete.
                is_first_scan = True
                last_state = None
                last_stats = None
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError) as exc:
                self.is_running = False
                self.is_ready_to_start = False
                self.pause_reason = None
                self.scan_event.clear()
                self.close_client()
                self.log(f"[-] Lost connection to the game. Details: {exc}", tag="error")
                wait_state = None
                last_state = None
                last_stats = None
                self._schedule(0, self.update_status_ui)
                time.sleep(1)
            except Exception as exc:
                self.log(f"[-] Error during execution: {exc}", tag="error")
                time.sleep(1)

        self.close_client()
        self._flush_total_rerolls(force=True)
        self.is_running = False
        self.is_ready_to_start = False
        self.pause_reason = None
        self.scan_event.clear()
        self._schedule(0, self.update_status_ui)

    # `on_closing` and `deferred_update_check` were defined here until step 25b.
    # Both are `MegabonkApp`'s now.
    #
    # `on_closing` is a shutdown *order* over eight owners -- the layout's tab
    # transition, the coordinator's three memory clients, the OBS server, the
    # in-game overlay, the Twitch bot and its auth thread, the VOD recorder, the
    # hotkey manager and the window. Exactly two of those steps were the
    # scanner's, and the rest reached the other seven through ambient `self`,
    # which is nine of this module's 29 hidden reads and every one of the five
    # step-24 delegators. It reads as feature behaviour only because it was
    # written where the events happened to live; it is composition-root
    # lifecycle, which is what step 26 says `MegabonkApp` is for.

    def build_session_stats_tab(self):
        """Construct the Session Stats view and hand it to the tab bar.

        The 80 lines of `QGroupBox` and `QLabel` this replaces are
        `ui/tabs/session_stats.py`'s; what stays here is the numbers and the
        one config-reading decision the view must not make (which colour a
        target gets, which depends on `EVALUATION_MODE`).
        """
        self._stats_view = SessionStatsTab(
            on_open_tracked_item_settings=self._open_tracked_item_settings_dialog,
        )
        self.tab_stats = self._stats_view.build()
        # See the slot's comment: two callers outside this file read it as
        # "the tab exists".
        self.stats_avg_layout = self._stats_view
        self.refresh_stats_ui()
        self._add_tab(self.tab_stats, "Session Stats")

    def set_tracked_item_rows(self, rows) -> None:
        """Render the tracked-item rules. Called by the overlay component.

        It owns `refresh_session_tracked_item_stats_ui` and used to format the
        rows into one string and write it into a label here. The rows carry
        their items and their condition; flattening them was what lost both.
        """
        if self._stats_view is not None:
            self._stats_view.set_tracked_rows(rows)


def build_scanner(
    app: Any,
    coordinator: Any,
    run_control: RunControl,
    filters: TemplateRuntimeFilters,
) -> Scanner:
    """Wire the scanner to its measured owners without giving it the app.

    The four widget ports (`log_box`, `status_label`, `toggle_btn`, `add_tab`)
    are `gui_layout`'s and stay `gui_layout`'s: step 26 owns those, and reading
    them through a lambda here means neither this module nor `gui_layout` gains
    a hidden read for them. The two dialog factories follow steps 22c/23c/24 --
    `gui_dialogs` is top-level debt, so the composition root supplies the
    factory rather than the component importing it.
    """
    return Scanner(
        coordinator,
        run_control=run_control,
        filters=filters,
        schedule=lambda delay_ms, callback: app.after(delay_ms, callback),
        # `__dict__`, not `hasattr`: `MegabonkApp.__getattr__` forwards unknown
        # names to its window, so `hasattr(app, "_invoker")` would consult a
        # widget before deciding the invoker is missing. Same reasoning as the
        # client and template-filter owners above it in `gui_app.py`.
        can_log=lambda: app.__dict__.get("_invoker") is not None,
        log_box=lambda: app.log_box,
        status_label=lambda: app.status_label,
        toggle_btn=lambda: app.toggle_btn,
        add_tab=lambda widget, title: app.tabview.addTab(widget, title),
        refresh_session_stats_snapshot=lambda: app._refresh_session_stats_snapshot(),
        refresh_session_tracked_item_stats_ui=lambda: app.refresh_session_tracked_item_stats_ui(),
        open_tracked_item_settings_dialog=lambda: app.open_session_tracked_item_settings_dialog(),
        is_recording=lambda: bool(app.player_stats_vod_recorder.is_recording),
        refresh_timeline=lambda: player_stats_view(app).refresh_player_stats_timeline_ui(
            update_slider=False
        ),
        is_shutting_down=lambda: bool(app._is_shutting_down),
        reroll_warning_dialog=lambda: RerollWarningDialog(app.window),
        obs_reminder_dialog=lambda: ObsRecordingReminderDialog(app.window),
    )
