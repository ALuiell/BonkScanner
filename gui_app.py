from __future__ import annotations

import os
import sys
import threading

from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication

import config
import updater
from gui_layout import GuiLayoutMixin
from gui_player_stats import PlayerStatsMixin
from gui_run_control import RunControlMixin
from gui_scanner import ScannerMixin
from gui_shared import UiInvoker, _AppWindow, resource_path
from gui_styles import ITEM_SORT_DEFAULT, build_qt_app_stylesheet
from gui_templates import TemplatesMixin
from vod_storage import VodRecorder


class MegabonkApp(
    GuiLayoutMixin,
    RunControlMixin,
    TemplatesMixin,
    PlayerStatsMixin,
    ScannerMixin,
):
    _qt_app: QApplication | None = None

    @classmethod
    def _ensure_qt_application(cls) -> QApplication:
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
            cls._qt_app = app
            app.setApplicationName("BonkScanner")
            checkmark_path = resource_path("media/checkmark.svg").replace("\\", "/")
            app.setStyleSheet(build_qt_app_stylesheet(checkmark_path))
        cls._qt_app = app
        return app

    def __init__(self):
        self._ensure_qt_application()
        self.window = _AppWindow(self)
        self._invoker = UiInvoker()
        self._close_protocol_handler = None
        self._is_shutting_down = False
        self._close_in_progress = False

        self.setWindowTitle(f"BonkScanner v{updater.CURRENT_VERSION}")
        self.resize(1280, 760)
        self.setMinimumSize(1080, 640)
        icon_path = resource_path("media/bonkscanner_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.left_tabview = None
        self.tab_templates = None
        self.tab_scores = None
        self.scrollable_templates = None
        self.template_layout = None
        self.scores_templates_frame = None
        self.scores_templates_layout = None
        self.scores_desc_label = None
        self.tabview = None
        self.tab_logs = None
        self.tab_stats = None
        self.tab_player_stats = None
        self.tab_vods = None
        self.log_box = None
        self.stats_time_label = None
        self.stats_rerolls_label = None
        self.stats_rpm_label = None
        self.stats_best_label = None
        self.stats_worst_label = None
        self.stats_avg_frame = None
        self.stats_avg_layout = None
        self.stats_avg_labels = {}
        self.player_stats_status_label = None
        self.player_stats_record_btn = None
        self.player_stats_slider = None
        self.player_stats_slider_time_label = None
        self.player_stats_timeline_label = None
        self.player_stats_detail_tabs = None
        self.player_stats_rows = {}
        self.player_stats_items_group = None
        self.player_stats_items_label = None
        self.player_stats_items_rarity_label = None
        self.player_stats_items_toggle_btn = None
        self.player_stats_items_sort_combo = None
        self.player_stats_items_sort_mode = ITEM_SORT_DEFAULT
        self.player_stats_items_expanded = False
        self.player_stats_items_current = ()
        self.player_stats_items_text_current = None
        self.player_stats_banishes_label = None
        self.player_stats_live_banishes = ()
        self.player_stats_in_game_time_label = None
        self.player_stats_chests_per_minute_label = None
        self.player_stats_mob_kills_label = None
        self.player_stats_level_label = None
        self.player_stats_new_items_label = None
        self.player_stats_stage_summary_labels = []
        self.player_stats_weapons_status_label = None
        self.player_stats_weapons_layout = None
        self.player_stats_weapon_cards = []
        self.player_stats_weapon_signature = None
        self.player_stats_tomes_status_label = None
        self.player_stats_tomes_layout = None
        self.player_stats_tome_cards = []
        self.player_stats_tome_signature = None
        self.vods_list_frame = None
        self.vods_status_label = None
        self.vods_name_entry = None
        self.vods_rename_btn = None
        self.vods_delete_btn = None
        self.vods_slider = None
        self.vods_slider_time_label = None
        self.vods_detail_tabs = None
        self.vods_rows = {}
        self.vods_items_group = None
        self.vods_items_label = None
        self.vods_items_rarity_label = None
        self.vods_items_toggle_btn = None
        self.vods_items_sort_combo = None
        self.vods_items_sort_mode = ITEM_SORT_DEFAULT
        self.vods_items_expanded = False
        self.vods_items_current = ()
        self.vods_items_text_current = None
        self.vods_banishes_label = None
        self.vods_in_game_time_label = None
        self.vods_chests_per_minute_label = None
        self.vods_mob_kills_label = None
        self.vods_level_label = None
        self.vods_new_items_label = None
        self.vods_compare_set_btn = None
        self.vods_compare_clear_btn = None
        self.vods_compare_details_btn = None
        self.vods_compare_details_group = None
        self.vods_compare_details_summary_label = None
        self.vods_compare_details_items_label = None
        self.vods_stage_summary_labels = []
        self.vods_weapons_status_label = None
        self.vods_weapons_layout = None
        self.vods_weapon_cards = []
        self.vods_weapon_signature = None
        self.vods_tomes_status_label = None
        self.vods_tomes_layout = None
        self.vods_tome_cards = []
        self.vods_tome_signature = None
        self.status_label = None
        self.toggle_btn = None
        self.logo_label = None

        self.is_running = False
        self.is_ready_to_start = False
        self.active_templates = []
        self.scanner_thread = None
        self.client = None
        self.player_stats_client = None
        self.player_stats_game_data_client = None
        self.player_stats_vod_recorder = VodRecorder(
            interval_seconds=getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30),
        )
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = None
        self.player_stats_recording_stage_ptr = 0
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = None
        self.loaded_vod = None
        self.loaded_vod_snapshot_index = None
        self.loaded_vod_compare_start_index = None
        self.vods_compare_details_expanded = False
        self.native_hook_loader = None
        self.native_hook_thread = None
        self.native_hook_generation = 0
        self.run_control_provider = None
        self._native_hook_admin_warning_logged = False
        self._native_hook_error_dialog_visible = False
        self.checkboxes = {}
        self.scores_checkboxes = {}
        self.animation_active = False
        self.animation_frame = 0
        self.stop_event = threading.Event()
        self.scan_event = threading.Event()
        self.session_start_time = None
        self.session_rerolls = 0
        self.best_map_stats = None
        self.best_map_score = -1
        self.worst_map_stats = None
        self.worst_map_score = float("inf")
        self.template_stats = {}
        self.vods_list_signature = None

        self.setup_ui()
        self.refresh_templates()
        self.refresh_scores_templates_list()
        self.refresh_scores_ui()
        self.setup_hotkeys()
        self.update_timer()
        self.update_player_stats_timer()
        self.check_admin_rights()
        self.log(f"[*] Welcome to BonkScanner v{updater.CURRENT_VERSION}!", tag="success")
        self.log(f"[*] Target Process: {config.PROCESS_NAME}")
        self.log("[*] Ready! Select templates and start the main process loop.")
        self.apply_run_control_mode(detach_hooks=False)
        self.after(1500, self.deferred_update_check)

    def __getattr__(self, name: str):
        window = self.__dict__.get("window")
        if window is not None and hasattr(window, name):
            return getattr(window, name)
        raise AttributeError(name)

    @staticmethod
    def _scope_prefix(scope: str) -> str:
        scope_prefixes = {
            "live": "player_stats",
            "vod": "vods",
        }
        try:
            return scope_prefixes[scope]
        except KeyError as exc:
            raise ValueError(f"Unknown UI scope: {scope}") from exc

    @property
    def qt_app(self) -> QApplication:
        return self._ensure_qt_application()

    def protocol(self, name: str, callback: object) -> None:
        if name == "WM_DELETE_WINDOW":
            self._close_protocol_handler = callback

    def mainloop(self) -> int:
        self.window.show()
        return self.qt_app.exec()

    def destroy(self):
        self._close_in_progress = True
        self.window.close()

    def _handle_window_close(self, event: QCloseEvent) -> None:
        if self._close_in_progress or self._is_shutting_down:
            event.accept()
            return
        handler = self._close_protocol_handler or getattr(self, "on_closing", None)
        if callable(handler):
            event.ignore()
            handler()
            return
        event.accept()

    def after(self, delay_ms: int, callback):
        self._invoker.call_later.emit(int(delay_ms), callback)
        return None

    def after_idle(self, callback):
        self._invoker.call_now.emit(callback)
        return None

    def winfo_exists(self) -> bool:
        return not self._is_shutting_down
