from __future__ import annotations

import os
import sys
import threading
import time

from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication

from app import config
from app.coordinator import AppCoordinator
from app.version import CURRENT_VERSION
from app.player_stats_refresh import player_stats_refresh
from ui.tabs.compare_runs import CompareRunsMixin
from gui_layout import GuiLayoutMixin
from gui_overlay import OverlayMixin
from gui_in_game_overlay import InGameOverlayMixin
from gui_run_control import RunControlMixin
from gui_scanner import ScannerMixin
from ui.shared import UiInvoker, _AppWindow, resource_path
from app.refresh_tasks import PLAYER_STATS_REFRESH_MS
from ui.styles import build_qt_app_stylesheet
from gui_templates import TemplatesMixin
from gui_twitch import TwitchBotMixin
from app.vod_library import VodLibrary


class MegabonkApp(
    GuiLayoutMixin,
    RunControlMixin,
    TemplatesMixin,
    OverlayMixin,
    InGameOverlayMixin,
    CompareRunsMixin,
    ScannerMixin,
    TwitchBotMixin,
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

        self.setWindowTitle(f"BonkScanner v{CURRENT_VERSION}")
        self.resize(1320, 830)
        self.setMinimumSize(1120, 710)
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
        self.tab_vods = None
        self.tab_compare_runs = None
        self.log_box = None
        self.stats_time_label = None
        self.stats_rerolls_label = None
        self.stats_rpm_label = None
        self.stats_best_label = None
        self.stats_worst_label = None
        self.stats_tracked_items_label = None
        self.stats_tracked_items_settings_btn = None
        self.stats_avg_frame = None
        self.stats_avg_layout = None
        self.stats_avg_labels = {}
        # Every Live Stats widget is gone from the shared namespace: step 19
        # made `LiveStatsTab` an object with its own private widgets, built by
        # `gui_layout._build_live_stats_view` and reached through the
        # `PlayerStatsView` port. Twelve slots left here -- the status label,
        # the detail tabs, the stats-row map, the five run-summary labels, the
        # stage-summary labels, and the two that were never built at all.
        # `player_stats_selected_snapshot_index` and
        # `player_stats_snapshot_pinned` stay: they are app-layer state that
        # `vod_capture` and `player_stats_refresh` also write, so the tab
        # reports selections back through a callback rather than owning them.
        # Every Recordings widget is gone from the shared namespace too: step
        # 21c made `RecordingsTab` an object with its own private widgets, built
        # by `gui_layout._build_recordings_view`. Twenty-four slots left here,
        # plus the two chooser flags and, below, the four selection names and
        # the list signature. None of them had a production reader outside the
        # tab module -- these `= None` lines were their only other mention,
        # which is the measurement that let them move whole rather than stay as
        # app surface behind a port.
        self.compare_run_a_list_frame = None
        self.compare_run_b_list_frame = None
        self.compare_runs_chooser_group = None
        self.compare_runs_select_btn = None
        self.compare_runs_swap_btn = None
        self.compare_runs_stats_config_group = None
        self.compare_runs_stats_config_btn = None
        self.compare_runs_stat_checkboxes = {}
        self.compare_runs_items_checkbox = None
        self.compare_runs_stage_summary_checkbox = None
        self.compare_runs_weapons_checkbox = None
        self.compare_runs_tomes_checkbox = None
        self.compare_runs_chaos_checkbox = None
        self.compare_run_a_selected_label = None
        self.compare_run_b_selected_label = None
        self.compare_run_a_status_label = None
        self.compare_run_b_status_label = None
        self.compare_run_a_slider = None
        self.compare_run_b_slider = None
        self.compare_run_a_timeline_label = None
        self.compare_run_b_timeline_label = None
        self.compare_run_a_summary_label = None
        self.compare_run_b_summary_label = None
        self.compare_run_a_items_group = None
        self.compare_run_b_items_group = None
        self.compare_run_a_items_label = None
        self.compare_run_b_items_label = None
        self.compare_run_a_items_rarity_label = None
        self.compare_run_b_items_rarity_label = None
        self.compare_run_a_items_toggle_btn = None
        self.compare_run_b_items_toggle_btn = None
        self.compare_run_a_items_sort_combo = None
        self.compare_run_b_items_sort_combo = None
        # And the two compare sides', built by _build_compare_run_panel.
        self.compare_runs_diff_overview_group = None
        self.compare_runs_diff_overview_label = None
        self.compare_runs_diff_stats_group = None
        self.compare_runs_diff_stats_label = None
        self.compare_runs_diff_items_group = None
        self.compare_runs_diff_items_label = None
        self.compare_runs_diff_stage_summary_group = None
        self.compare_runs_diff_stage_summary_label = None
        self.compare_runs_diff_weapons_group = None
        self.compare_runs_diff_weapons_label = None
        self.compare_runs_diff_tomes_group = None
        self.compare_runs_diff_tomes_label = None
        self.compare_runs_diff_chaos_group = None
        self.compare_runs_diff_chaos_label = None
        self.compare_runs_item_details_btn = None
        self.status_label = None
        self.toggle_btn = None
        self.logo_label = None
        self.tab_overlay = None
        self.twitch_target_channel_entry = None
        self.overlay_state_store = None
        self.overlay_server = None
        self.live_run_tracker = None
        self.overlay_enabled_checkbox = None
        self.overlay_status_label = None
        self.overlay_server_toggle_btn = None
        self.overlay_url_entry = None
        self.overlay_widget_url_combo = None
        self.overlay_widget_url_entry = None
        self.overlay_port_entry = None
        self.overlay_template_combo = None
        self.overlay_widget_checkboxes = {}
        self.overlay_stats_checkboxes = {}
        self.overlay_stats_content = None
        self.overlay_tracked_items_label = None
        self.overlay_tracked_items_content = None
        self.overlay_tracked_items_toggle_btn = None
        self.overlay_item_names = ()
        self.overlay_item_search_entry = None
        self.overlay_item_selector = None
        self.overlay_map_one_only_checkbox = None
        self.overlay_add_tracked_item_btn = None
        self.overlay_tracked_rules_list = None
        self.overlay_remove_tracked_item_btn = None
        self.session_item_names = ()
        self.session_item_search_entry = None
        self.session_item_selector = None
        self.session_map_one_only_checkbox = None
        self.session_add_tracked_item_btn = None
        self.session_tracked_rules_list = None
        self.session_remove_tracked_item_btn = None

        self.is_running = False
        self.is_ready_to_start = False
        self.obs_recording_reminder_shown = False
        self.active_templates = []
        self.scanner_thread = None
        # client / player_stats_client / player_stats_game_data_client are owned by
        # AppCoordinator (step 12b); it initialises them to None in its __init__,
        # reached here through the client properties below and the scanner mixin.
        # The two memory-reconnect streaks that stood here are `PlayerStatsMemory`'s
        # fields now (step 20): nothing outside its reconnect policy read them.
        # The coordinator is built a few lines below.
        self.coordinator = AppCoordinator(
            tracked_item_rules=self._combined_tracked_item_rules(),
            stale_after_seconds=max(25.0, (float(PLAYER_STATS_REFRESH_MS) / 1000.0) * 2.5),
            overlay_host=config.OVERLAY.get("host", "127.0.0.1"),
            overlay_port=int(config.OVERLAY.get("port", 17845)),
            vod_interval_seconds=getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30),
        )
        # Aliases, not copies: the coordinator owns these, the mixins still reach
        # them through the shared `self`. Step 12 removes the aliases.
        self.player_stats_vod_recorder = self.coordinator.vod_recorder
        self.initialize_overlay_runtime()
        self.initialize_in_game_overlay_runtime()
        self.player_stats_last_run_id = None
        self.player_stats_disabled_items_cache = None
        self.player_stats_disabled_items_refresh_pending = False
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_snapshot_pinned = False
        # The eight recording-lifecycle names that stood here are
        # `VodCapture`'s fields now (step 20). The three above stay: their
        # readers are the Live Stats tab and `gui_layout`, and the tab writes
        # two of them back through its selection callback.
        self.compare_run_a_vod = None
        self.compare_run_b_vod = None
        self.compare_run_a_snapshot_index = None
        self.compare_run_b_snapshot_index = None
        self.compare_runs_list_signature = None
        self.compare_runs_chooser_expanded = False
        self.compare_runs_guided_selection_active = False
        self.compare_runs_stats_config_expanded = False
        compare_sections = self.configured_compare_run_sections()
        self.compare_runs_items_enabled = compare_sections["items"]
        self.compare_runs_stage_summary_enabled = compare_sections["stage_summary"]
        self.compare_runs_weapons_enabled = compare_sections["weapons"]
        self.compare_runs_tomes_enabled = compare_sections["tomes"]
        self.compare_runs_chaos_enabled = compare_sections["chaos"]
        self.compare_runs_item_details_expanded = False
        self.compare_runs_syncing = False
        self.run_control_provider = None
        self._hotkey_manager = None
        self.checkboxes = {}
        self.scores_checkboxes = {}
        self.animation_active = False
        self.animation_frame = 0
        self.stop_event = threading.Event()
        self.scan_event = threading.Event()
        self.session_start_time = None
        self.session_rerolls = 0
        self._total_rerolls_dirty = False
        self._total_rerolls_last_flush = time.monotonic()
        self._total_rerolls_lock = threading.Lock()
        self.best_map_stats = None
        self.best_map_score = -1
        self.worst_map_stats = None
        self.worst_map_score = float("inf")
        self.template_stats = {}
        self._twitch_session_snapshot = {
            "rerolls": 0,
            "seeds_found": 0,
            "tracked_rows": (),
        }
        self._twitch_session_snapshot_lock = threading.Lock()
        self._compare_run_load_generations = {}
        # The recording-metadata index, its refresh cycle and its two guards,
        # in one named object (step 21). They were four attributes here, read by
        # both recording tabs and written by one of them, whose completion
        # callback reached into the other tab's signature and repaint -- while
        # that tab called back into it to start the refresh. Neither tab names
        # the other now: both subscribe to this.
        #
        # `schedule` re-reads `_invoker` on every result rather than capturing
        # it, which is the same late-resolution rule step 20's services follow
        # and the same guard the callback it replaces applied inline.
        self.vod_library = VodLibrary(
            schedule=lambda callback: (
                self.after(0, callback) if self._invoker is not None else callback()
            ),
        )
        self.vod_library.subscribe(
            invalidate=self.invalidate_compare_runs_list,
            repaint=self.refresh_compare_runs_list,
        )

        self.setup_ui()
        self.setup_twitch_bot_ui()
        self.apply_overlay_autostart()
        self.refresh_templates()
        self.refresh_scores_templates_list()
        self.refresh_scores_ui()
        self.setup_hotkeys()
        self.update_timer()
        self.coordinator.start_refresh_loop(
            tick=self.update_player_stats_timer,
            schedule=self.after,
            is_active=lambda: not self._is_shutting_down,
            interval_ms=lambda: int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500)),
        )
        self.check_admin_rights()
        self.log(f"[*] Welcome to BonkScanner v{CURRENT_VERSION}!", tag="success")
        self.log(f"[*] Target Process: {config.PROCESS_NAME}")
        self.log("[*] Ready! Select templates and start the main process loop.")
        self.apply_run_control_mode(detach_hooks=False)
        self.after(1500, self.deferred_update_check)

    def __getattr__(self, name: str):
        window = self.__dict__.get("window")
        if window is not None and hasattr(window, name):
            return getattr(window, name)
        raise AttributeError(name)

    # -- coordinator-owned memory clients (step 12b) ----------------------
    #
    # These are pure delegation to the AppCoordinator. They lived on
    # PlayerStatsMemoryMixin until step 20 converted it to a service; the clients
    # are app-instance surface (gui_scanner, gui_twitch, player_stats_refresh and
    # the memory service all reach them), so they moved here rather than into the
    # service that no longer defines them.
    #
    # Step 20h removed the `__dict__` fallback that used to stand in for a
    # missing coordinator, which is step 20's third exit criterion: an app
    # double built with `object.__new__` must be *given* its clients, not have
    # the property quietly invent shadow storage for them. Doubles that assign
    # a client now install a coordinator first (`make_client_coordinator` in
    # `tests/test_gui_run_control.py`) -- the same carrier production uses, so
    # the four service resolvers cache in the same place for both.
    #
    # `__dict__`, not `getattr`: `MegabonkApp.__getattr__` forwards unknown
    # names to its `window`, so a `getattr` would consult the widget before
    # deciding there is no coordinator. `_client_owner` raises AttributeError
    # rather than letting a KeyError out, so an owner with no coordinator fails
    # the way a missing attribute is supposed to -- `hasattr` and
    # `getattr(app, ..., default)` keep behaving.
    def _client_owner(self):
        coordinator = self.__dict__.get("coordinator")
        if coordinator is None:
            raise AttributeError(
                "memory clients live on the AppCoordinator; this owner has none"
            )
        return coordinator

    @property
    def player_stats_client(self):
        return self._client_owner().player_stats_client

    @player_stats_client.setter
    def player_stats_client(self, value) -> None:
        self._client_owner().player_stats_client = value

    @property
    def player_stats_game_data_client(self):
        return self._client_owner().player_stats_game_data_client

    @player_stats_game_data_client.setter
    def player_stats_game_data_client(self, value) -> None:
        self._client_owner().player_stats_game_data_client = value

    # -- player-stats refresh (step 20g) ----------------------------------
    #
    # `PlayerStatsRefreshMixin` was the seventh and last app-side MRO base;
    # step 20g converted it into the `PlayerStatsRefresh` service. These two
    # stay here as one-line delegators because, unlike `RefreshTasksMixin`'s
    # six method pairs, both are genuine `MegabonkApp` surface with callers
    # outside their own module: `refresh_live_player_stats_now` is called on
    # the app by `gui_layout`, `gui_twitch`, `app/refresh_tasks` and
    # `app/vod_capture`, and `update_player_stats_timer` is the `tick=` handed
    # to `start_refresh_loop` below. Same finding, same shape and the same
    # place as the two coordinator-delegating client properties above.
    #
    # The two `app/` callers deliberately keep calling *the app*: nothing in
    # `app/` may import `app.player_stats_refresh`, which sits at the top of
    # that package's import DAG. They already receive this as an
    # owner-resolved lambda.
    def update_player_stats_timer(self) -> None:
        return player_stats_refresh(self).tick()

    def refresh_live_player_stats_now(self, **kwargs) -> bool:
        return player_stats_refresh(self).refresh_now(**kwargs)

    # -- Recordings tab (step 21c) ----------------------------------------
    #
    # Two one-line delegators, for the same reason `refresh_live_player_stats_now`
    # above keeps one: both are called *on the app* by the tab-switch router in
    # `gui_layout` (`on_right_tab_changed`, `_refresh_right_tab_after_switch`,
    # `_refresh_vods_list_if_visible`), and that router is **step 26's**. Step 21
    # may not assign it to a tab, so the app keeps the surface the router calls
    # and forwards it to the view it built.
    #
    # `hasattr(self, "ensure_recordings_chooser_for_empty_selection")` in
    # `gui_layout` guards both call sites. That guard going quietly false is the
    # silent-failure shape step 19's header records, so the name stays.
    def refresh_vods_list(self) -> None:
        return self._recordings_view.refresh_vods_list()

    def ensure_recordings_chooser_for_empty_selection(self) -> None:
        return self._recordings_view.ensure_recordings_chooser_for_empty_selection()

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
