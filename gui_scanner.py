from __future__ import annotations

import datetime
import html
import threading
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel

import config
import logic
import updater
from game_data import GameDataClient
from gui_shared import _clear_layout, _set_text
from gui_styles import COLOR_MAP, _button_state_stylesheet
from hook_loader import HookLoadError, HookProcessNotFoundError
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from run_control import RunControlError
from runtime_stats import adapt_map_stats

try:
    import keyboard
except ImportError:
    keyboard = None

class ScannerMixin:

    def deferred_update_check(self):
        threading.Thread(target=updater.check_and_update, args=(self, False), daemon=True).start()

    def update_timer(self):
        if self._is_shutting_down:
            return

        if self.scanner_thread and self.scanner_thread.is_alive() and self.session_start_time:
            elapsed = int(time.time() - self.session_start_time)
            td = datetime.timedelta(seconds=elapsed)
            self.stats_time_label.setText(f"Session Time: {td}")
            if elapsed > 0 and self.session_rerolls > 0:
                rpm = (self.session_rerolls / elapsed) * 60
                self.stats_rpm_label.setText(f"Rerolls per Minute (RPM): {rpm:.1f}")

        if self.player_stats_vod_recorder.is_recording:
            self.refresh_player_stats_timeline_ui(update_slider=False)

        self.after(1000, self.update_timer)

    def update_status_ui(self):
        if self.status_label is None or self.toggle_btn is None:
            return

        if self.scanner_thread and self.scanner_thread.is_alive():
            if self.is_running:
                status = "RUNNING"
            elif self.is_ready_to_start:
                status = "ARMED"
            else:
                status = "WAITING FOR GAME"
            self.status_label.setText(f"Status: {status}")
            self.toggle_btn.setText("Stop")
            self.toggle_btn.setStyleSheet(_button_state_stylesheet("#B91C1C", "#DC2626"))
        else:
            self.status_label.setText("Status: IDLE")
            self.toggle_btn.setText("Start")
            self.toggle_btn.setStyleSheet("")

    def animate_scanner_indicator(self):
        return None

    def _append_log(self, message, tag=None):
        if self.log_box is None:
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

        self.log_box.moveCursor(QTextCursor.End)
        self.log_box.insertHtml(line + "<br>")
        self.log_box.moveCursor(QTextCursor.End)

    def log(self, message, tag=None):
        if not hasattr(self, "_invoker"):
            return
        self.after(0, lambda m=message, t=tag: self._append_log(m, t))

    def toggle_main_loop(self):
        if self.scanner_thread is None or not self.scanner_thread.is_alive():
            self.log(f"\n[*] Starting auto-reroll monitor in {config.EVALUATION_MODE.upper()} mode...")

            if config.EVALUATION_MODE == "templates":
                self.active_templates = self._get_selected_template_names()
                if not self.active_templates:
                    self.log("[-] Error: You must select at least one template!", tag="error")
                    return
                colored_parts = ["[*] Active profiles: "]
                colored_tags = [None]
                for index, name in enumerate(self.active_templates):
                    color_tag = "BLUE"
                    for template in config.TEMPLATES:
                        if template["name"] == name:
                            color_tag = template.get("color", "BLUE").upper()
                            break
                    colored_parts.append(name)
                    colored_tags.append(color_tag)
                    if index < len(self.active_templates) - 1:
                        colored_parts.append(", ")
                        colored_tags.append(None)
                self.log(colored_parts, tag=colored_tags)
                self.template_stats = {name: {"rerolls_since_last": 0, "history": []} for name in self.active_templates}
            else:
                active_tiers = config.SCORES_SYSTEM.get("active_tiers", [])
                if not active_tiers:
                    self.log("[-] Error: No active tiers selected in Scores mode!", tag="error")
                    return
                self.log(f"[*] Active Tiers: {', '.join(active_tiers)}")
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
            self._sync_runtime_filters()
            self.update_status_ui()
        else:
            self.stop_event.set()
            self.scan_event.set()
            self.is_running = False
            self.is_ready_to_start = False
            self.log("\n[*] Stopping auto-reroll monitor...")
            self.after(500, self.update_status_ui)

    def refresh_stats_ui(self):
        _set_text(self.stats_rerolls_label, f"Session Rerolls: {self.session_rerolls}")

        if self.best_map_stats:
            _set_text(self.stats_best_label, f"Best Map Found: {self.format_stats(self.best_map_stats)}")
        else:
            _set_text(self.stats_best_label, "Best Map Found: None")

        if self.worst_map_stats:
            _set_text(self.stats_worst_label, f"Worst Map Found: {self.format_stats(self.worst_map_stats)}")
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
                colors = {"Light": "WHITE", "Good": "GREEN", "Perfect": "YELLOW", "Perfect+": "LIGHTRED_EX"}
                color_tag = colors.get(name, "BLUE")
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
            label.setStyleSheet(f"color: {hex_color}; font-size: 16px; font-weight: 600;")

        stale_names = [name for name in self.stats_avg_labels if name not in active_names]
        for name in stale_names:
            label = self.stats_avg_labels.pop(name)
            self.stats_avg_layout.removeWidget(label)
            label.deleteLater()

    def log_reroll_stats(self):
        self.session_rerolls += 1
        config.TOTAL_REROLLS += 1
        config.user_config["TOTAL_REROLLS"] = config.TOTAL_REROLLS
        try:
            config.save_config(config.user_config)
        except Exception as exc:
            self.log(f"[-] Could not save Total Rerolls: {exc}", tag="warning")

        for name in list(self.template_stats):
            self.template_stats[name]["rerolls_since_last"] += 1

        if self.session_rerolls % 5 == 0:
            self.after(0, self.refresh_stats_ui)

    def log_target_found(self, template_name: str):
        if template_name in self.template_stats:
            data = self.template_stats[template_name]
            attempts = data["rerolls_since_last"] if data["rerolls_since_last"] > 0 else 1
            data["history"].append(attempts)
            data["rerolls_since_last"] = 0
        self.after(0, self.refresh_stats_ui)

    def check_best_map(self, stats: dict):
        score = self.calculate_map_score(stats)
        if score > self.best_map_score:
            self.best_map_score = score
            self.best_map_stats = stats
            self.after(0, self.refresh_stats_ui)

    def check_worst_map(self, stats: dict):
        score = self.calculate_map_score(stats)
        if score < self.worst_map_score:
            self.worst_map_score = score
            self.worst_map_stats = stats
            self.after(0, self.refresh_stats_ui)

    def reroll_map(self):
        if self.run_control_provider is None:
            self.log("[-] Run control provider is not available; cannot restart run.", tag="error")
            return

        previous_state = None
        previous_stats = None
        if self.client is not None:
            try:
                previous_state = self.client.get_map_generation_state()
                previous_stats = self.client.get_map_stats()
            except MemoryReadError as exc:
                self.log(f"[WAIT] Could not read current map state before restart: {exc}", tag="warning")

        try:
            self.run_control_provider.restart_run()
        except RunControlError as exc:
            self.log(f"[-] {exc}", tag="error")
            return

        self.run_control_provider.wait_for_next_run(
            client=self.client,
            previous_state=previous_state,
            previous_stats=previous_stats,
            warn=lambda message: self.log(f"[WAIT] {message}", tag="warning"),
        )
        self.log_reroll_stats()

    def close_client(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

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
                    self.after(0, self.update_status_ui)
                except ProcessNotFoundError:
                    if wait_state != "process":
                        self.log(f"[WAIT] Waiting for process '{process_name}'...", tag="warning")
                        wait_state = "process"
                        self.after(0, self.update_status_ui)
                    time.sleep(1)
                    continue
                except ModuleNotFoundError:
                    if wait_state != "module":
                        self.log("[WAIT] Game found. Waiting for it to finish loading...", tag="warning")
                        wait_state = "module"
                        self.after(0, self.update_status_ui)
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
                if not self.wait_for_game_window_focus(process_name):
                    continue

                try:
                    raw_stats = self.client.wait_for_map_ready(
                        previous_state=last_state,
                        previous_stats=last_stats,
                        require_change=not is_first_scan,
                        abort_condition=lambda: self.stop_event.is_set() or not self.scan_event.is_set(),
                        timeout=10.0,
                    )
                except InterruptedError:
                    continue

                is_first_scan = False
                last_state = self.client.get_map_generation_state()
                last_stats = raw_stats
                stats = adapt_map_stats(raw_stats)

                self.check_best_map(stats)
                self.check_worst_map(stats)
                candidate = self.evaluate_candidate(stats)

                if candidate is not None:
                    if not self.wait_for_game_window_focus(process_name):
                        continue

                    t_name = candidate.get("name")
                    t_color = candidate.get("color", "BLUE").upper()
                    score_text = (
                        f" (Score: {candidate.get('score', 0):.1f})"
                        if config.EVALUATION_MODE == "scores"
                        else ""
                    )
                    self.log([f"\n[$$$] TARGET MAP FOUND! Profile: ", f"{t_name}{score_text}"], tag=["success", t_color])
                    self.log(f"Map Stats: {self.format_stats(stats)}", tag="success")
                    self.log_target_found(t_name)

                    if not self.handle_confirmed_target_window(process_name):
                        continue

                    self.is_running = False
                    self.scan_event.clear()
                    self.after(0, self.update_status_ui)
                    continue
                else:
                    self.log(f"Stats: {self.format_stats(stats)}")

                if not self.wait_for_game_window_focus(process_name):
                    continue

                elapsed = time.monotonic() - last_reroll_time
                while elapsed < config.MIN_DELAY:
                    if self.stop_event.is_set() or not self.scan_event.is_set():
                        break
                    time.sleep(0.05)
                    elapsed = time.monotonic() - last_reroll_time

                if self.stop_event.is_set() or not self.scan_event.is_set():
                    continue

                self.reroll_map()
                last_reroll_time = time.monotonic()

            except TimeoutError as exc:
                self.log(f"[-] Map took too long to load: {exc}", tag="warning")
                self.log("[*] Restarting run to recover...", tag="warning")
                self.reroll_map()
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
                self.after(0, self.update_status_ui)
                time.sleep(1)
            except Exception as exc:
                self.log(f"[-] Error during execution: {exc}", tag="error")
                time.sleep(1)

        self.close_client()
        self.is_running = False
        self.is_ready_to_start = False
        self.scan_event.clear()
        self.after(0, self.update_status_ui)

    def on_closing(self):
        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True
        self._cancel_right_tab_transition()
        self.stop_event.set()
        self.scan_event.set()
        self.close_client()
        self.close_player_stats_client()
        self.close_player_stats_game_data_client()
        if hasattr(self, "close_overlay_server"):
            self.close_overlay_server()
        player_stats_vod_recorder = self.__dict__.get("player_stats_vod_recorder")
        if player_stats_vod_recorder is not None:
            if player_stats_vod_recorder.is_recording:
                player_stats_vod_recorder.stop()
            else:
                player_stats_vod_recorder.close()
        hook_loader = self.native_hook_loader
        if hook_loader is not None:
            self.native_hook_generation += 1
            self.native_hook_loader = None
            self.native_hook_thread = None
            try:
                hook_loader.uninitialize()
                self.log("[+] Game restart helper disconnected.", tag="success")
            except HookProcessNotFoundError:
                self.log("[WAIT] Game is already closed; restart helper shutdown skipped.", tag="warning")
            except HookLoadError as exc:
                self.log(f"[WAIT] Could not disconnect restart helper during shutdown. Details: {exc}", tag="warning")
            except Exception as exc:
                self.log(f"[WAIT] Unexpected restart helper shutdown error. Details: {exc}", tag="warning")
            finally:
                try:
                    hook_loader.cleanup_cached_dll()
                except Exception as exc:
                    self.log(f"[WAIT] Could not clean up cached restart helper DLL. Details: {exc}", tag="warning")
        if keyboard:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self.destroy()