from __future__ import annotations

from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication

import config
from gui_in_game_overlay_render import (
    build_event_timer_overlay_html,
    build_kps_overlay_html,
    build_luck_rarity_overlay_html,
    build_powerups_overlay_html,
    build_stats_overlay_html,
    build_status_indicator_html,
    calculate_luck_rarity_probabilities,
)
from gui_in_game_overlay_settings import (
    InGameWidgetSettingsDialog,
    build_in_game_overlay_tab,
    update_in_game_overlay_status_ui,
)
from gui_in_game_overlay_window import InGameOverlayWindow

try:
    from gui_run_control import win32gui
except Exception:
    win32gui = None


class InGameOverlayMixin:
    def initialize_in_game_overlay_runtime(self) -> None:
        self.in_game_overlay_window = None

        self.overlay_fast_timer = QTimer()
        self.overlay_fast_timer.timeout.connect(self._overlay_fast_tick)
        self.overlay_fast_timer.setInterval(500)

        self.overlay_slow_timer = QTimer()
        self.overlay_slow_timer.timeout.connect(self._overlay_slow_tick)
        self.overlay_slow_timer.setInterval(10000)

        self.after_idle(self._init_in_game_overlay)

    def _init_in_game_overlay(self) -> None:
        self.in_game_overlay_window = InGameOverlayWindow(self)

        if not config.IN_GAME_OVERLAY.get("auto_start", False):
            config.IN_GAME_OVERLAY["enabled"] = False

        if config.IN_GAME_OVERLAY["enabled"] and config.IN_GAME_OVERLAY.get("auto_start", False):
            self.start_in_game_overlay()

        self._update_igo_status_ui()

    def start_in_game_overlay(self) -> None:
        if not self.in_game_overlay_window:
            return
        self.overlay_fast_timer.start()
        self.overlay_slow_timer.start()
        became_visible = self._overlay_fast_tick()
        if not became_visible:
            self._overlay_slow_tick()

    def stop_in_game_overlay(self) -> None:
        if self.in_game_overlay_window:
            self.in_game_overlay_window.hide()
        self.overlay_fast_timer.stop()
        self.overlay_slow_timer.stop()

    def apply_in_game_overlay_settings(self) -> None:
        cfg = config.IN_GAME_OVERLAY
        if not self.in_game_overlay_window:
            return

        if cfg["enabled"]:
            # The window can already be visible from edit mode while the periodic
            # overlay timers are still stopped, so visibility is not a reliable
            # proxy for an active runtime.
            self.start_in_game_overlay()
        else:
            self.stop_in_game_overlay()
            self._update_igo_status_ui()
            return

        for widget_id, widget_cfg in cfg["widgets"].items():
            widget = self.in_game_overlay_window.widgets.get(widget_id)
            if widget is None:
                continue
            if widget_id == "powerups":
                if not widget_cfg["enabled"]:
                    widget.setVisible(False)
            else:
                widget.setVisible(widget_cfg["enabled"])
            widget.update_scale(widget_cfg.get("scale", 1.0))
            if widget_id == "luck_rarity" and hasattr(widget, "set_show_bar"):
                widget.set_show_bar(widget_cfg.get("show_bar", True))
            if not self.in_game_overlay_window.edit_mode:
                widget.move(widget_cfg["x"], widget_cfg["y"])

        self._overlay_fast_tick()
        self._overlay_slow_tick()
        self._update_igo_status_ui()

    def _in_game_overlay_target_geometry(self) -> QRect | None:
        if win32gui is not None and hasattr(self, "find_game_window"):
            try:
                game_window = self.find_game_window(config.PROCESS_NAME)
            except Exception:
                game_window = None
            if game_window:
                try:
                    left, top, right, bottom = win32gui.GetWindowRect(game_window)
                except Exception:
                    game_window = None
                else:
                    width = max(0, int(right) - int(left))
                    height = max(0, int(bottom) - int(top))
                    if width > 0 and height > 0:
                        return QRect(int(left), int(top), width, height)

        overlay_window = getattr(self, "in_game_overlay_window", None)
        if overlay_window is None or not getattr(overlay_window, "edit_mode", False):
            return None

        screen = overlay_window.screen() if overlay_window is not None else None
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.geometry() if screen is not None else None

    def hotkey_toggle_in_game_overlay_edit(self) -> None:
        self.after(0, self._toggle_igo_edit_mode)

    def _overlay_fast_tick(self) -> bool:
        if not self.in_game_overlay_window:
            return False

        cfg = config.IN_GAME_OVERLAY
        was_visible = self.in_game_overlay_window.isVisible()
        if not cfg.get("enabled", False) and not self.in_game_overlay_window.edit_mode:
            if self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.hide()
            return False

        if self.in_game_overlay_window.edit_mode:
            self.in_game_overlay_window.sync_geometry_to_target()
            if not self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.show()
        else:
            is_game_active = self.is_game_window_active(config.PROCESS_NAME)
            if is_game_active:
                self.in_game_overlay_window.sync_geometry_to_target()
                if not self.in_game_overlay_window.isVisible():
                    self.in_game_overlay_window.show()
            elif self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.hide()

        if not self.in_game_overlay_window.isVisible():
            return False

        widgets = self.in_game_overlay_window.widgets
        if cfg["widgets"]["kps"]["enabled"]:
            metrics_cfg = cfg["widgets"]["kps"].get("metrics", ["instant"])
            widgets["kps"].set_text(build_kps_overlay_html(self.live_run_tracker, metrics_cfg))

        # Retrieve snapshot and powerups map context to determine stage metadata
        latest_snapshot_reader = getattr(self.live_run_tracker, "latest_snapshot", None)
        latest_snapshot = latest_snapshot_reader() if callable(latest_snapshot_reader) else None

        is_graveyard = False
        map_context_reader = getattr(self.live_run_tracker, "powerup_map_context", None)
        map_context = map_context_reader() if callable(map_context_reader) else None
        if map_context is not None:
            is_graveyard = map_context.is_graveyard

        stage_index = 0
        stage_time_seconds = 0.0
        stage_timer_seconds = 0.0
        if latest_snapshot is not None:
            if getattr(latest_snapshot, "stage_index", None) is not None:
                stage_index = int(latest_snapshot.stage_index)
            stage_time_seconds = float(
                getattr(latest_snapshot, "stage_duration_seconds", 0.0) or 0.0
            )
            stage_timer_seconds = float(
                getattr(
                    latest_snapshot,
                    "stage_timer_seconds",
                    getattr(latest_snapshot, "stage_time_seconds", 0.0),
                )
                or 0.0
            )

        event_stage_index = stage_index
        event_stage_time_seconds = stage_time_seconds
        event_stage_timer_seconds = stage_timer_seconds
        fast_stage_context_reader = getattr(self.live_run_tracker, "fast_stage_timer_context", None)
        fast_stage_context = (
            fast_stage_context_reader() if callable(fast_stage_context_reader) else None
        )
        if fast_stage_context is not None:
            if getattr(fast_stage_context, "stage_index", None) is not None:
                event_stage_index = int(fast_stage_context.stage_index)
            event_stage_time_seconds = float(
                getattr(
                    fast_stage_context,
                    "stage_duration_seconds",
                    event_stage_time_seconds,
                )
                or 0.0
            )
            event_stage_timer_seconds = float(
                getattr(
                    fast_stage_context,
                    "stage_timer_seconds",
                    event_stage_timer_seconds,
                )
                or 0.0
            )

        if cfg["widgets"].get("stats", {}).get("enabled", False):
            selected_stats = cfg["widgets"]["stats"].get("selected_stats", ["Damage", "Difficulty", "XP Gain", "Luck"])
            html = build_stats_overlay_html(
                latest_snapshot,
                selected_stats,
                stage_index,
                stage_timer_seconds,
                stage_time_seconds,
                is_graveyard,
            )
            widgets["stats"].set_text(html)

        if cfg["widgets"].get("event_timer", {}).get("enabled", False):
            warning_seconds = cfg["widgets"]["event_timer"].get("warning_seconds", 15)
            graveyard_events_active = False
            active_reader = getattr(self.live_run_tracker, "graveyard_main_map_events_active", None)
            if callable(active_reader):
                graveyard_events_active = active_reader()

            html = build_event_timer_overlay_html(
                event_stage_index,
                event_stage_timer_seconds,
                event_stage_time_seconds,
                is_graveyard,
                warning_seconds,
                graveyard_main_map_events_active=graveyard_events_active,
                edit_mode=self.in_game_overlay_window.edit_mode,
            )
            widgets["event_timer"].set_text(html)

        if cfg["widgets"]["powerups"]["enabled"]:
            snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
            snapshot = snapshot_reader() if callable(snapshot_reader) else None
            html = self._build_powerups_overlay_html(
                snapshot,
                edit_mode=self.in_game_overlay_window.edit_mode,
            )
            if html:
                widgets["powerups"].set_text(html)
                widgets["powerups"].setVisible(True)
            else:
                widgets["powerups"].setVisible(False)

        became_visible = not was_visible and self.in_game_overlay_window.isVisible()
        if became_visible:
            self._refresh_in_game_overlay_slow_widgets()
        return became_visible

    @staticmethod
    def _build_powerups_overlay_html(
        snapshot,
        *,
        edit_mode: bool = False,
        current_run_time_seconds: float | None = None,
    ) -> str:
        return build_powerups_overlay_html(
            snapshot,
            edit_mode=edit_mode,
            current_run_time_seconds=current_run_time_seconds,
        )

    @staticmethod
    def _build_luck_rarity_overlay_html(snapshot) -> str:
        return build_luck_rarity_overlay_html(snapshot)

    def _overlay_slow_tick(self) -> None:
        if not self.in_game_overlay_window or not self.in_game_overlay_window.isVisible():
            return

        self._refresh_in_game_overlay_slow_widgets()

    def _refresh_in_game_overlay_slow_widgets(self) -> None:
        if not self.in_game_overlay_window:
            return

        widgets = self.in_game_overlay_window.widgets
        cfg = config.IN_GAME_OVERLAY
        widget_cfg = cfg.get("widgets", {})

        if widget_cfg.get("scanner", {}).get("enabled", False):
            is_active = bool(getattr(self, "scanner_thread", None) and self.scanner_thread.is_alive())
            widgets["scanner"].set_text(build_status_indicator_html("Scanner", is_active))

        if widget_cfg.get("recording", {}).get("enabled", False):
            is_recording = bool(
                getattr(self, "player_stats_vod_recorder", None)
                and self.player_stats_vod_recorder.is_recording
            )
            widgets["recording"].set_text(build_status_indicator_html("REC", is_recording))

        if widget_cfg.get("luck_rarity", {}).get("enabled", False):
            latest_snapshot_reader = getattr(self.live_run_tracker, "latest_snapshot", None)
            latest_snapshot = latest_snapshot_reader() if callable(latest_snapshot_reader) else None
            luck_stat = None
            if latest_snapshot is not None and isinstance(getattr(latest_snapshot, "stats", None), dict):
                luck_stat = latest_snapshot.stats.get("Luck")
            luck_value = getattr(luck_stat, "value", None)
            probabilities = calculate_luck_rarity_probabilities(luck_value)
            widget = widgets["luck_rarity"]
            if hasattr(widget, "set_probabilities"):
                widget.set_probabilities(
                    probabilities,
                    show_bar=widget_cfg.get("luck_rarity", {}).get("show_bar", True),
                )
            else:
                widget.set_text(self._build_luck_rarity_overlay_html(latest_snapshot))

    def _build_in_game_overlay_tab(self) -> None:
        build_in_game_overlay_tab(self)

    def _toggle_in_game_overlay(self) -> None:
        cfg = config.IN_GAME_OVERLAY
        cfg["enabled"] = not cfg["enabled"]
        self.apply_in_game_overlay_settings()
        config.save_config(config.user_config)

    def _update_igo_status_ui(self) -> None:
        update_in_game_overlay_status_ui(self)

    def _on_igo_settings_changed(self, *_args) -> None:
        cfg = config.IN_GAME_OVERLAY
        cfg["auto_start"] = self.igo_auto_start_cb.isChecked()
        cfg["widgets"]["scanner"]["enabled"] = self.igo_scanner_cb.isChecked()
        cfg["widgets"]["recording"]["enabled"] = self.igo_recording_cb.isChecked()
        cfg["widgets"]["kps"]["enabled"] = self.igo_kps_cb.isChecked()
        cfg["widgets"]["powerups"]["enabled"] = self.igo_powerups_cb.isChecked()
        cfg["widgets"]["luck_rarity"]["enabled"] = self.igo_luck_rarity_cb.isChecked()
        cfg["widgets"]["stats"]["enabled"] = self.igo_stats_cb.isChecked()
        cfg["widgets"]["event_timer"]["enabled"] = self.igo_event_timer_cb.isChecked()
        self.apply_in_game_overlay_settings()
        config.save_config(config.user_config)

    def _toggle_igo_edit_mode(self) -> None:
        if not self.in_game_overlay_window:
            return

        is_edit_mode = not self.in_game_overlay_window.edit_mode
        self.in_game_overlay_window.toggle_edit_mode(is_edit_mode)

        if is_edit_mode:
            self.igo_edit_btn.setText("Save Layout")
            self.igo_edit_btn.setStyleSheet("background-color: #22c55e; color: white;")
            if not self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.show()
        else:
            self.igo_edit_btn.setText("Edit Layout")
            self.igo_edit_btn.setStyleSheet("")
            self.apply_in_game_overlay_settings()
            config.save_config(config.user_config)

        self._update_igo_status_ui()

    def _open_igo_widget_settings_dialog(self) -> None:
        dialog = InGameWidgetSettingsDialog(self, self.tab_in_game_overlay)
        dialog.exec()
