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
from gui_dialogs import HelpDialog, SettingsDialog
from gui_layout import GuiLayoutMixin
from gui_overlay import OverlayMixin
from gui_in_game_overlay import InGameOverlayMixin
from gui_run_control import RunControlMixin
from gui_scanner import ScannerMixin
from app.template_filters import TemplateRuntimeFilters
from ui.shared import UiInvoker, _AppWindow, resource_path
from app.refresh_tasks import PLAYER_STATS_REFRESH_MS
from ui.styles import build_qt_app_stylesheet
from gui_twitch import TwitchBotMixin
from app.vod_library import VodLibrary


class MegabonkApp(
    GuiLayoutMixin,
    RunControlMixin,
    OverlayMixin,
    InGameOverlayMixin,
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
        # `None` until `setup_ui` builds it, and the two delegators below guard
        # on that. Not defensive habit -- `_build_left_tabs` connects
        # `currentChanged` to `on_left_tab_changed` *before* the panel exists,
        # so `addTab` fires the router during construction. The mixin absorbed
        # this because `refresh_scores_ui` began `if self.scores_desc_label is
        # None: return` and the checkbox dicts were empty. Removing those slots
        # removed the guard with them, and Qt swallows exceptions raised inside
        # a slot: the app came up with a traceback on stderr and no other
        # symptom. Found by constructing the real app, not by the suite -- the
        # same way, and for the same reason, step 21's startup crash was found.
        self._templates_panel = None
        self.tabview = None
        self.tab_logs = None
        self.tab_stats = None
        self.tab_vods = None
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
        # Every Compare Runs widget is gone too: step 21d made `CompareRunsTab`
        # an object with its own private widgets, and moved the ~250 lines that
        # built them out of `gui_layout` and into the tab. Forty-seven slots
        # left here, plus the sixteen pieces of selection and section state
        # below. Measured, like the Recordings twenty-six: none had a
        # production reader outside the tab module.
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
        # `active_templates` and `template_stats` were plain slots here, and
        # `PRE_EXISTING_COLLISIONS` recorded that Scanner and Templates both
        # wrote them. Step 22b gave them an owner rather than letting
        # `TemplatesMixin` leaving the MRO make the register entry vanish while
        # both writers were still writing. Built first, before anything can read
        # the delegating properties above; every port is a late-bound lambda, so
        # the collaborators it names need not exist yet.
        self._template_filters = TemplateRuntimeFilters(
            # Late-bound: the panel does not exist until `setup_ui` runs, well
            # after this. Nothing asks the question before then.
            selected_template_names=lambda: (
                []
                if self._templates_panel is None
                else self._templates_panel.selected_template_names()
            ),
            # The guard is here, not in the service: "have the session-stats
            # widgets been built yet" is a question about this class's
            # construction order, which is exactly what `_sync_runtime_filters`
            # was asking with its two `hasattr` calls.
            refresh_stats=lambda: (
                self.refresh_stats_ui()
                if hasattr(self, "stats_avg_labels") and hasattr(self, "stats_avg_layout")
                else None
            ),
            log=self.log,
            is_scanning=lambda: (
                self.scanner_thread is not None and self.scanner_thread.is_alive()
            ),
        )
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
        self.run_control_provider = None
        self._hotkey_manager = None
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
        # `template_stats` is `TemplateRuntimeFilters`' field (step 22b).
        self._twitch_session_snapshot = {
            "rerolls": 0,
            "seeds_found": 0,
            "tracked_rows": (),
        }
        self._twitch_session_snapshot_lock = threading.Lock()
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

        self.setup_ui()
        self.setup_twitch_bot_ui()
        self.apply_overlay_autostart()
        self._templates_panel.refresh_templates()
        self._templates_panel.refresh_scores_templates_list()
        self._templates_panel.refresh_scores_ui()
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

    # -- template runtime filters (step 22b) ------------------------------
    #
    # `active_templates` and `template_stats` were two slots on this shared
    # namespace, written by `gui_app.__init__`, `gui_scanner` and
    # `gui_templates`, and named in `PRE_EXISTING_COLLISIONS` as co-owned. They
    # are `app.template_filters.TemplateRuntimeFilters`' fields now. These four
    # delegators are why `gui_scanner` needed no edit: its assignments still
    # read as assignments and now land in the owner.
    #
    # `__dict__` and a default rather than `_client_owner`'s raise, for a reason
    # this class documents twelve lines above: `MegabonkApp.__getattr__`
    # forwards unknown names to `self.window`. An AttributeError out of this
    # getter would be *caught* by that forwarding and answered by a widget,
    # which is a silent wrong answer rather than a failure. The fallback is the
    # `ScannerMixin.client` affordance for `object.__new__` doubles; production
    # always has the owner, and `test_template_filters.py` pins that.
    def _template_filters_owner(self):
        return self.__dict__.get("_template_filters")

    @property
    def active_templates(self):
        owner = self._template_filters_owner()
        if owner is not None:
            return owner.active_templates
        return self.__dict__.setdefault("_active_templates", [])

    @active_templates.setter
    def active_templates(self, value) -> None:
        owner = self._template_filters_owner()
        if owner is not None:
            owner.active_templates = value
        else:
            self.__dict__["_active_templates"] = value

    @property
    def template_stats(self):
        owner = self._template_filters_owner()
        if owner is not None:
            return owner.template_stats
        return self.__dict__.setdefault("_template_stats", {})

    @template_stats.setter
    def template_stats(self, value) -> None:
        owner = self._template_filters_owner()
        if owner is not None:
            owner.template_stats = value
        else:
            self.__dict__["_template_stats"] = value

    # Thin delegators, kept on the app for the same reason step 20g's two and
    # step 21's four are: `gui_layout.on_left_tab_changed` and `gui_scanner`
    # call these *on the app*, and the router that does so is step 26's subject.
    # They forward to the app-layer owner; neither reaches the templates UI.
    def _sync_runtime_filters(self, *, announce: bool = False) -> None:
        self._template_filters.sync(announce=announce)

    def _get_selected_template_names(self) -> list[str]:
        return self._template_filters.selected_template_names()

    # `gui_layout.on_left_tab_changed` calls this *on the app* when the user
    # switches between the Templates and Scores tabs. Same shape and same reason
    # as the delegators above: the router is step 26's subject, so the panel
    # gets the work and the app keeps the one-line entry point.
    def refresh_scores_ui(self) -> None:
        if self._templates_panel is None:
            return
        self._templates_panel.refresh_scores_ui()

    # -- footer dialogs (step 22c) ----------------------------------------
    #
    # These two sat in `gui_templates.py` and have nothing to do with templates:
    # they hang off the footer buttons, next to Start/Stop. They are here rather
    # than in `TemplatesPanel` because of what the first one does --
    # `SettingsDialog(window, master=self)`. The dialog reaches `master` for
    # about ten things and several of those reads are under `hasattr`
    # (`setup_hotkeys`, `apply_run_control_mode`, `player_stats_vod_recorder`,
    # `player_stats_view(master)`, `log`, `update_status_ui`,
    # `vod_capture(master)`).
    #
    # Had they moved to the panel, `master` would be the panel, every `hasattr`
    # branch would go quietly false, and hotkeys would stop re-registering after
    # a settings save -- with a green suite and no exception anywhere. That is
    # precisely the failure step 19 recorded for
    # `SettingsDialog.save -> refresh_player_stats_timeline_ui`. `master=self`
    # here still means the application.
    def open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.window, master=self)
        dialog.exec()

    def open_help_dialog(self) -> None:
        dialog = HelpDialog(self.window)
        dialog.exec()

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

    # -- Compare Runs tab (step 21d) ---------------------------------------
    #
    # The same two, for the same router, for the same reason. Step 26 takes the
    # router; until then this is the surface it calls.
    def refresh_compare_runs_list(self) -> None:
        return self._compare_runs_view.refresh_compare_runs_list()

    def ensure_compare_runs_chooser_for_empty_selection(self) -> None:
        return self._compare_runs_view.ensure_compare_runs_chooser_for_empty_selection()

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
