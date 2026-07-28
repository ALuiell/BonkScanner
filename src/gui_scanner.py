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

The worker is still `daemon=True` and still not joined, and that is a decision
rather than an omission. It blocks in `scan_event.wait()` and in the client's
own waits; the stop path sets both events, which is what unblocks it, and every
blocking call it makes takes an abort condition. An explicit `join` would add a
shutdown deadline for a thread whose only remaining work after `stop_event` is
to fall out of a `while` -- and `on_closing` runs on the Qt thread, so a join
that did not return would hang the close instead of the process. The trace
asserts the thread is actually dead after both the stop and the shutdown path,
which is the property a join would have been buying.
"""
from __future__ import annotations

import datetime
import html
import threading
import time
from typing import Any, Callable

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app import config
from app.map_scoring import calculate_map_score, evaluate_candidate, format_stats
from app.player_stats_view import player_stats_view
from app.template_filters import TemplateRuntimeFilters
# Top-level, not deferred into the builder. `gui_dialogs` imports nothing from
# here, so there is no cycle to dodge, and a function-body import is invisible
# to pyflakes and to every test that does not take that branch -- which is how
# step 21 shipped a startup crash.
from ui.dialogs import ObsRecordingReminderDialog, RerollWarningDialog
from gui_run_control import RunControl
from infra.memory.game_data_client import GameDataClient
from ui.shared import _apply_button_icon, _make_scroll_section, _set_text
from core.item_metadata import COLOR_MAP
from ui.styles import _session_stats_label_stylesheet, _set_widget_style_role
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
        self.stats_time_label = None
        self.stats_rerolls_label = None
        self.stats_rpm_label = None
        self.stats_best_label = None
        self.stats_worst_label = None
        self.stats_tracked_items_label = None
        self.stats_tracked_items_settings_btn = None
        self.stats_avg_frame = None
        self.stats_avg_layout = None
        self.stats_avg_labels: dict[str, Any] = {}

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

    def _score_tier_color_tag(self, tier: str) -> str:
        colors = {"Light": "WHITE", "Good": "GREEN", "Perfect": "YELLOW", "Perfect+": "LIGHTRED_EX"}
        return colors.get(tier, "BLUE")

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
            self.stats_time_label.setText(f"Session Time: {td}")
            if elapsed > 0 and self.session_rerolls > 0:
                rpm = (self.session_rerolls / elapsed) * 60
                self.stats_rpm_label.setText(f"Rerolls per Minute (RPM): {rpm:.1f}")

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
        log_box = self._log_box()
        if log_box is None:
            return

        def colored_html(part: str, color_tag: str | None) -> str:
            if color_tag:
                color = COLOR_MAP.get(str(color_tag).upper(), COLOR_MAP["DEFAULT"])
                return f'<span style="color:{color}">{html.escape(str(part))}</span>'
            return html.escape(str(part))

        if isinstance(tag, list):
            line = "".join(colored_html(part, sub_tag) for part, sub_tag in zip(message, tag))
        elif tag:
            line = colored_html(message, tag)
        else:
            line = html.escape(str(message))

        log_box.moveCursor(QTextCursor.End)
        log_box.insertHtml(line + "<br>")
        log_box.moveCursor(QTextCursor.End)

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
            self.scan_event.clear()
            self.log("[*] Scan paused. Press the scan hotkey again to resume.")
        else:
            self.is_running = True
            self.scan_event.set()
            self.log("[*] Scan started. Looking for selected target...")
        self.update_status_ui()

    def toggle_main_loop(self):
        if not self.is_scanning():
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
                def template_color_tag(name: str) -> str:
                    for template in config.TEMPLATES:
                        if template["name"] == name:
                            return template.get("color", "BLUE").upper()
                    return "BLUE"

                self._log_colored_names("[*] Active profiles: ", self.active_templates, template_color_tag)
                self.template_stats = {name: {"rerolls_since_last": 0, "history": []} for name in self.active_templates}
            else:
                active_tiers = config.SCORES_SYSTEM.get("active_tiers", [])
                if not active_tiers:
                    self.log("[-] Error: No active tiers selected in Scores mode!", tag="error")
                    return
                self._log_colored_names("[*] Active Tiers: ", active_tiers, self._score_tier_color_tag)
                self.template_stats = {name: {"rerolls_since_last": 0, "history": []} for name in active_tiers}

            self.session_start_time = time.time()
            self.session_rerolls = 0
            self.best_map_stats = None
            self.best_map_score = -1
            self.worst_map_stats = None
            self.worst_map_score = float("inf")
            self.refresh_stats_ui()

            self.is_running = False
            self.is_ready_to_start = False
            self.scan_event.clear()
            self.stop_event.clear()
            self.scanner_thread = threading.Thread(target=self.background_loop, daemon=True)
            self.scanner_thread.start()
            self._filters.sync()
            self.update_status_ui()
        else:
            # The stop path is `shutdown()`'s two events plus the forced flush,
            # so it is the same call: one definition of "release the worker".
            self.shutdown()
            self.is_running = False
            self.is_ready_to_start = False
            self.log("\n[*] Stopping auto-reroll monitor...")
            self._schedule(500, self.update_status_ui)

    def refresh_stats_ui(self):
        # Both were `hasattr`-guarded on the shared namespace, for app doubles
        # that carried neither. They are ports now and always present; each one
        # already answers "no owner" internally on the app side, which is where
        # that decision belongs.
        self._refresh_session_stats_snapshot()
        _set_text(self.stats_rerolls_label, f"Session Rerolls: {self.session_rerolls}")
        self._refresh_session_tracked_item_stats_ui()

        if self.best_map_stats:
            _set_text(self.stats_best_label, f"Best Map Found: {format_stats(self.best_map_stats, self.active_templates)}")
        else:
            _set_text(self.stats_best_label, "Best Map Found: None")

        if self.worst_map_stats:
            _set_text(self.stats_worst_label, f"Worst Map Found: {format_stats(self.worst_map_stats, self.active_templates)}")
        else:
            _set_text(self.stats_worst_label, "Worst Map Found: None")

        active_names = set()
        for name, data in self.template_stats.items():
            active_names.add(name)
            color_tag = "BLUE"
            if config.EVALUATION_MODE == "templates":
                for template in config.TEMPLATES:
                    if template["name"] == name:
                        color_tag = template.get("color", "BLUE").upper()
                        break
            else:
                color_tag = self._score_tier_color_tag(name)
            hex_color = COLOR_MAP.get(color_tag, COLOR_MAP["DEFAULT"])
            history = data["history"]
            avg_text = f"{sum(history) / len(history):.1f} ({len(history)} found)" if history else "N/A"

            label = self.stats_avg_labels.get(name)
            if label is None:
                label = QLabel()
                label.setWordWrap(True)
                self.stats_avg_layout.addWidget(label)
                self.stats_avg_labels[name] = label
            label.setText(f"{name}: {avg_text}")
            label.setStyleSheet(f"color: {hex_color}; font-size: 16px; font-weight: 600; background: transparent;")

        stale_names = [name for name in self.stats_avg_labels if name not in active_names]
        for name in stale_names:
            label = self.stats_avg_labels.pop(name)
            self.stats_avg_layout.removeWidget(label)
            label.deleteLater()

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
        if self._scan_abort_requested():
            return False

        previous_state = None
        previous_stats = None
        if self.client is not None:
            try:
                previous_state = self.client.get_map_generation_state()
                previous_stats = self.client.get_map_stats()
            except MemoryReadError as exc:
                self.log(f"[WAIT] Could not read current map state before restart: {exc}", tag="warning")
        if self._scan_abort_requested():
            return False

        try:
            self._run_control.run_control_provider.restart_run()
        except RunControlError as exc:
            self.log(f"[-] {exc}", tag="error")
            return False

        try:
            self._run_control.run_control_provider.wait_for_next_run(
                client=self.client,
                previous_state=previous_state,
                previous_stats=previous_stats,
                warn=lambda message: self.log(f"[WAIT] {message}", tag="warning"),
                abort_condition=self._scan_abort_requested,
            )
        except InterruptedError:
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
        last_reroll_time = time.monotonic()
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

                is_first_scan = False
                last_state = self.client.get_map_generation_state()
                last_stats = raw_stats
                stats = adapt_map_stats(raw_stats)
                eval_context = {
                    "supports_bald_heads": stats.get("Chests", 0) >= 69,
                }

                self.check_best_map(stats)
                self.check_worst_map(stats)
                candidate = evaluate_candidate(stats, self.active_templates, context=eval_context)

                if candidate is not None:
                    if not self._run_control.wait_for_game_window_focus(process_name):
                        continue

                    t_name = candidate.get("name")
                    t_color = candidate.get("color", "BLUE").upper()
                    score_text = (
                        f" (Score: {candidate.get('score', 0):.1f})"
                        if config.EVALUATION_MODE == "scores"
                        else ""
                    )
                    self.log(["\n[$$$] TARGET MAP FOUND! Profile: ", f"{t_name}{score_text}"], tag=["success", t_color])
                    self.log(f"Map Stats: {format_stats(stats, self.active_templates)}", tag="success")
                    self.log_target_found(t_name)

                    if not self._run_control.handle_confirmed_target_window(process_name):
                        continue

                    self.is_running = False
                    self.scan_event.clear()
                    self._schedule(0, self.update_status_ui)
                    continue
                else:
                    self.log(f"Stats: {format_stats(stats, self.active_templates)}")

                if not self._run_control.wait_for_game_window_focus(process_name):
                    continue

                elapsed = time.monotonic() - last_reroll_time
                while elapsed < config.MIN_DELAY:
                    if self._scan_abort_requested():
                        break
                    time.sleep(0.05)
                    elapsed = time.monotonic() - last_reroll_time

                if self._scan_abort_requested():
                    continue

                if self.reroll_map():
                    last_reroll_time = time.monotonic()

            except TimeoutError:
                self.log("[-] Map took too long to load.", tag="warning")
                self.log("[*] Restarting run to recover...", tag="warning")
                if self._run_control.wait_for_game_window_focus(process_name) and self.reroll_map():
                    last_reroll_time = time.monotonic()
                last_state = None
                last_stats = None
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError) as exc:
                self.is_running = False
                self.is_ready_to_start = False
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
        self.tab_stats = QWidget()
        stats_layout = QVBoxLayout(self.tab_stats)
        stats_scroll, _stats_content, stats_content_layout = _make_scroll_section()
        stats_layout.addWidget(stats_scroll)
        self.stats_time_label = QLabel("Session Time: 00:00:00")
        self.stats_rerolls_label = QLabel("Session Rerolls: 0")
        self.stats_rpm_label = QLabel("Rerolls per Minute (RPM): 0.0")
        self.stats_best_label = QLabel("Best Map Found: None")
        self.stats_worst_label = QLabel("Worst Map Found: None")

        overview_group = QGroupBox("Session Overview")
        overview_layout = QVBoxLayout(overview_group)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(8)
        for widget in (
            self.stats_time_label,
            self.stats_rerolls_label,
            self.stats_rpm_label,
        ):
            widget.setWordWrap(True)
            widget.setStyleSheet(_session_stats_label_stylesheet(accent=True))
            overview_layout.addWidget(widget)
        stats_content_layout.addWidget(overview_group)

        maps_group = QGroupBox("Map Highlights")
        maps_layout = QVBoxLayout(maps_group)
        maps_layout.setContentsMargins(12, 12, 12, 12)
        maps_layout.setSpacing(10)
        for widget in (
            self.stats_best_label,
            self.stats_worst_label,
        ):
            widget.setWordWrap(True)
            widget.setStyleSheet(_session_stats_label_stylesheet())
            maps_layout.addWidget(widget)
        stats_content_layout.addWidget(maps_group)

        tracked_items_group = QGroupBox("Tracked Items")
        tracked_items_layout = QVBoxLayout(tracked_items_group)
        tracked_items_layout.setContentsMargins(12, 12, 12, 12)
        tracked_items_layout.setSpacing(0)
        tracked_items_row = QHBoxLayout()
        tracked_items_row.setContentsMargins(0, 0, 0, 0)
        tracked_items_row.setSpacing(8)
        self.stats_tracked_items_label = QLabel("Anvils Map 1: 0")
        self.stats_tracked_items_label.setWordWrap(True)
        self.stats_tracked_items_label.setStyleSheet(_session_stats_label_stylesheet())
        self.stats_tracked_items_settings_btn = QPushButton("")
        self.stats_tracked_items_settings_btn.setObjectName("iconBtn")
        self.stats_tracked_items_settings_btn.setToolTip("Tracked item settings")
        self.stats_tracked_items_settings_btn.setFixedSize(34, 30)
        _apply_button_icon(self.stats_tracked_items_settings_btn, "media/settings_icon.png", 18)
        self.stats_tracked_items_settings_btn.clicked.connect(self._open_tracked_item_settings_dialog)
        tracked_items_row.addWidget(self.stats_tracked_items_label, 1)
        tracked_items_row.addWidget(self.stats_tracked_items_settings_btn)
        tracked_items_layout.addLayout(tracked_items_row)
        stats_content_layout.addWidget(tracked_items_group)

        average_group = QGroupBox("Average Rerolls per Target")
        average_layout = QVBoxLayout(average_group)
        average_layout.setContentsMargins(12, 12, 12, 12)
        average_layout.setSpacing(8)
        self.stats_avg_frame = QWidget()
        self.stats_avg_frame.setObjectName("cardContent")
        self.stats_avg_layout = QVBoxLayout(self.stats_avg_frame)
        self.stats_avg_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_avg_layout.setSpacing(6)
        average_layout.addWidget(self.stats_avg_frame)
        stats_content_layout.addWidget(average_group)
        stats_content_layout.addStretch(1)
        self._add_tab(self.tab_stats, "Session Stats")


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
