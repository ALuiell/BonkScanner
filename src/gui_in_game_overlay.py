from __future__ import annotations

from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication

import config
from gui_in_game_overlay_render import (
    build_kps_overlay_html,
    build_powerups_overlay_html,
    build_status_indicator_html,
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
        self.in_game_overlay_window.sync_geometry_to_target()
        self.in_game_overlay_window.show()
        self.overlay_fast_timer.start()
        self.overlay_slow_timer.start()
        self._overlay_fast_tick()
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
            if not self.in_game_overlay_window.isVisible():
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
        screen = overlay_window.screen() if overlay_window is not None else None
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.geometry() if screen is not None else None

    def hotkey_toggle_in_game_overlay_edit(self) -> None:
        self.after(0, self._toggle_igo_edit_mode)

    def _overlay_fast_tick(self) -> None:
        if not self.in_game_overlay_window:
            return

        cfg = config.IN_GAME_OVERLAY
        if not cfg.get("enabled", False) and not self.in_game_overlay_window.edit_mode:
            if self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.hide()
            return

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
            return

        widgets = self.in_game_overlay_window.widgets
        if cfg["widgets"]["kps"]["enabled"]:
            metrics_cfg = cfg["widgets"]["kps"].get("metrics", ["instant"])
            widgets["kps"].set_text(build_kps_overlay_html(self.live_run_tracker, metrics_cfg))

        if cfg["widgets"]["powerups"]["enabled"]:
            snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
            snapshot = snapshot_reader() if callable(snapshot_reader) else None
            latest_snapshot_reader = getattr(self.live_run_tracker, "latest_snapshot", None)
            latest_snapshot = latest_snapshot_reader() if callable(latest_snapshot_reader) else None
            current_run_time_seconds = getattr(latest_snapshot, "game_time_seconds", None)
            html = self._build_powerups_overlay_html(
                snapshot,
                edit_mode=self.in_game_overlay_window.edit_mode,
                current_run_time_seconds=current_run_time_seconds,
            )
            if html:
                widgets["powerups"].set_text(html)
                widgets["powerups"].setVisible(True)
            else:
                widgets["powerups"].setVisible(False)

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

    def _overlay_slow_tick(self) -> None:
        if not self.in_game_overlay_window or not self.in_game_overlay_window.isVisible():
            return

        widgets = self.in_game_overlay_window.widgets
        cfg = config.IN_GAME_OVERLAY

        if cfg["widgets"]["scanner"]["enabled"]:
            is_active = bool(getattr(self, "scanner_thread", None) and self.scanner_thread.is_alive())
            widgets["scanner"].set_text(build_status_indicator_html("Scanner", is_active))

        if cfg["widgets"]["recording"]["enabled"]:
            is_recording = bool(
                getattr(self, "player_stats_vod_recorder", None)
                and self.player_stats_vod_recorder.is_recording
            )
            widgets["recording"].set_text(build_status_indicator_html("REC", is_recording))

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
