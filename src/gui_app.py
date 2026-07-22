from __future__ import annotations

import os
import sys

from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication

from app import config
from app.coordinator import AppCoordinator
from app.version import CURRENT_VERSION
from app.player_stats_memory import player_stats_memory
from app.player_stats_refresh import player_stats_refresh
from gui_dialogs import HelpDialog, SettingsDialog
from gui_layout import GuiLayoutMixin
from gui_overlay import build_overlay, combined_tracked_item_rules
from gui_in_game_overlay import build_in_game_overlay
from gui_run_control import build_run_control
from gui_scanner import build_scanner
from gui_twitch import build_twitch_session, session_command_tracked_item_config
from app.template_filters import TemplateRuntimeFilters
from ui.shared import UiInvoker, _AppWindow, resource_path
from ui.update_prompt import start_update_check
from app.refresh_tasks import PLAYER_STATS_REFRESH_MS
from ui.styles import build_qt_app_stylesheet
from app.vod_library import VodLibrary
from session_stats import SessionStats


class MegabonkApp(
    GuiLayoutMixin,
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
        # Every Session Stats widget is gone from the shared namespace: step 25
        # made `Scanner` an object that builds its own tab. Eleven slots left
        # here, and the measurement that allowed it is the same one steps
        # 21c/21d/23b ran: of the eleven, exactly two had a production reader
        # outside `gui_scanner` -- `tab_stats` and `stats_tracked_items_label`,
        # both already reached by `gui_overlay` through named ports rather than
        # by attribute, so both ports simply changed which object they name.
        # The other nine were mentioned only by these `= None` lines.
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
        # Every Twitch widget is gone from the shared namespace: step 23b made
        # `TwitchTab` an object with its own private widgets, built by
        # `gui_layout._build_twitch_tab`. Twenty-two names left, and
        # `twitch_target_channel_entry` -- this line -- was the only one of them
        # mentioned anywhere outside `gui_twitch.py`. Measured before the move,
        # as steps 21c/21d/22c measured theirs: none had a production reader
        # outside the module, which is what let them move whole rather than stay
        # as app surface behind a port.
        self._twitch_tab = None
        # `None` until the composition root runs at the end of `__init__`. The
        # two delegators below read it out of `__dict__` for that window, and so
        # that a missing session cannot fall through `__getattr__` to the window.
        self._twitch_session = None
        self.overlay_state_store = None
        self.overlay_server = None
        self.live_run_tracker = None

        # `is_running`, `is_ready_to_start`, `obs_recording_reminder_shown`,
        # `scanner_thread`, `stop_event`, `scan_event`, `session_start_time`,
        # `session_rerolls`, the four best/worst map slots, the three
        # `_total_rerolls_*` names, the ten Session Stats widget slots,
        # `run_control_provider` and `_hotkey_manager` all stood here until step
        # 25. Twenty-eight slots, and not one of them is declared by this class
        # any more: they are `Scanner`'s and `RunControl`'s own fields. That is
        # the step's third exit criterion made structural rather than argued --
        # `step25_ownership.py` reports one writing scope per name because there
        # is only one place left that could write them.
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
            # The guard is here, not in the service: "have the session-stats
            # widgets been built yet" is a question about construction order,
            # which is exactly what `_sync_runtime_filters` was asking with its
            # two `hasattr` calls. It asks the scanner now, because the scanner
            # owns those widgets -- and it asks whether the *scanner* exists
            # too, because these filters are built before it.
            refresh_stats=lambda: (
                self._scanner.refresh_stats_ui()
                if self.__dict__.get("_scanner") is not None
                and self._scanner.stats_avg_layout is not None
                else None
            ),
            # Late-bound for the same reason: `log` is the scanner's and the
            # scanner does not exist yet. Passing `self.log` bound here would
            # have captured the delegator before it could resolve.
            log=lambda message, tag=None: self.log(message, tag=tag),
            is_scanning=lambda: (
                self.__dict__.get("_scanner") is not None and self._scanner.is_scanning()
            ),
        )
        # client / player_stats_client / player_stats_game_data_client are owned by
        # AppCoordinator (step 12b); it initialises them to None in its __init__,
        # reached here through the client properties below and the scanner mixin.
        # The two memory-reconnect streaks that stood here are `PlayerStatsMemory`'s
        # fields now (step 20): nothing outside its reconnect policy read them.
        # The coordinator is built a few lines below.
        self.coordinator = AppCoordinator(
            tracked_item_rules=combined_tracked_item_rules(),
            stale_after_seconds=max(25.0, (float(PLAYER_STATS_REFRESH_MS) / 1000.0) * 2.5),
            overlay_host=config.OVERLAY.get("host", "127.0.0.1"),
            overlay_port=int(config.OVERLAY.get("port", 17845)),
            vod_interval_seconds=getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30),
        )
        # Aliases, not copies: the coordinator owns these, the mixins still reach
        # them through the shared `self`. Step 12 removes the aliases.
        self.player_stats_vod_recorder = self.coordinator.vod_recorder
        self.overlay_state_store = self.coordinator.overlay_state_store
        self.live_run_tracker = self.coordinator.live_run_tracker
        self.overlay_server = self.coordinator.overlay_server
        # The two step-25 components, built before every collaborator that
        # names them. They are mutually referential -- the scanner asks run
        # control where the game window is, run control asks the scanner
        # whether the scan was cancelled -- so run control is built first with
        # late-bound lambdas and handed to the scanner as a real reference.
        self._run_control = build_run_control(self)
        self._scanner = build_scanner(
            self, self.coordinator, self._run_control, self._template_filters
        )
        self._session_stats = SessionStats(
            self.live_run_tracker,
            template_stats=lambda: self.template_stats,
            rerolls=lambda: self._scanner.session_rerolls,
            snapshot_tracked_item_config=session_command_tracked_item_config,
        )
        self._overlay = build_overlay(self, self.coordinator, self._session_stats)
        self._in_game_overlay = build_in_game_overlay(self)
        self._in_game_overlay.start_runtime()
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
        self.animation_active = False
        self.animation_frame = 0
        # `template_stats` is `TemplateRuntimeFilters`' field (step 22b).
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
        self._twitch_session = build_twitch_session(
            self,
            self._twitch_tab,
            session_snapshot=self._session_stats.snapshot,
        )
        self._twitch_session.start()
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

    # The scan client, moved here from `ScannerMixin` by step 25a. Its two
    # siblings below have been the app's since step 20h and this one is the same
    # shape for the same owner; it only stayed on the mixin because that was
    # where step 12b found it.
    #
    # The `__dict__` fallback the other two lost at 20h is still here, and
    # deliberately so: the 34 `object.__new__` doubles in
    # `tests/test_gui_run_control.py` assign `app.client = <fake>` and step 25's
    # own conversion is what retires them. Removing it in the same commit that
    # moves the property would mix two failures into one bisect. It goes when
    # the doubles do, measured, not guessed.
    @property
    def client(self):
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            return coordinator.client
        return self.__dict__.get("_client")

    @client.setter
    def client(self, value) -> None:
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            coordinator.client = value
        else:
            self.__dict__["_client"] = value

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

    # -- Twitch shutdown surface (step 23c) --------------------------------
    #
    # `gui_scanner.on_closing` stops the bot and joins the auth thread
    # (`gui_scanner.py:554-558`). The scanner is **step 25's** subject, so not a
    # line of it changes here: these two forward to the component, exactly as
    # steps 20g, 21 and 22c left thin delegators for what a not-yet-converted
    # caller invokes on the app.
    #
    # Both guard on the session being absent. `on_closing` runs on app doubles
    # in the suite and can run before `__init__` finished on a construction
    # fault, and `stop_twitch_bot` was reached under `hasattr` before -- a
    # delegator that raised where the mixin's method did not would be a
    # behaviour change smuggled in as plumbing.
    def stop_twitch_bot(self) -> None:
        session = self.__dict__.get("_twitch_session")
        if session is not None:
            session.stop_bot()

    @property
    def twitch_auth_thread(self):
        session = self.__dict__.get("_twitch_session")
        return None if session is None else session.auth_thread

    # -- OBS overlay surface (step 24c) -----------------------------------
    #
    # Layout routing (step 26), scanner shutdown/session updates (step 25)
    # and the app-layer refresh services still invoke these names on the app.
    # The behaviour and every widget live on `gui_overlay.Overlay`; this is the
    # measured compatibility surface that lets those later boundaries stay put.
    def _build_overlay_tab(self):
        return self._overlay.build()

    def refresh_overlay_ui(self) -> None:
        self._overlay.refresh_overlay_ui()

    def apply_overlay_autostart(self) -> None:
        self._overlay.apply_overlay_autostart()

    def close_overlay_server(self) -> None:
        overlay = self.__dict__.get("_overlay")
        if overlay is not None:
            overlay.close_overlay_server()

    def update_overlay_state_from_tracker(self) -> None:
        overlay = self.__dict__.get("_overlay")
        if overlay is not None:
            overlay.update_overlay_state_from_tracker()

    def mark_overlay_read_failed(self, *, no_game: bool = False) -> None:
        overlay = self.__dict__.get("_overlay")
        if overlay is not None:
            overlay.mark_overlay_read_failed(no_game=no_game)
            return
        tracker = self.__dict__.get("live_run_tracker")
        if tracker is not None:
            tracker.mark_read_failed(no_game=no_game)

    def overlay_should_refresh_live_stats(self) -> bool:
        overlay = self.__dict__.get("_overlay")
        if overlay is not None:
            return overlay.overlay_should_refresh_live_stats()
        server = self.__dict__.get("overlay_server")
        return bool(
            config.OVERLAY.get("enabled", False)
            or (server is not None and server.is_running)
        )

    def refresh_session_tracked_item_stats_ui(self) -> None:
        overlay = self.__dict__.get("_overlay")
        if overlay is not None:
            overlay.refresh_session_tracked_item_stats_ui()

    def _refresh_session_stats_snapshot(self) -> None:
        session_stats = self.__dict__.get("_session_stats")
        if session_stats is not None:
            session_stats.refresh_snapshot()

    def open_session_tracked_item_settings_dialog(self) -> None:
        overlay = self.__dict__.get("_overlay")
        if overlay is not None:
            overlay.open_session_tracked_item_settings_dialog()

    # -- in-game overlay surface (step 24b) -------------------------------
    #
    # The layout, hotkey registration and shutdown path are steps 26, 25 and
    # 25 respectively. They still call these names on the application, so the
    # app keeps only the narrow forwarding surface while the component owns
    # the window, timers, widgets and behaviour.
    def _build_in_game_overlay_tab(self):
        return self._in_game_overlay.build()

    def hotkey_toggle_in_game_overlay_edit(self) -> None:
        overlay = self.__dict__.get("_in_game_overlay")
        if overlay is not None:
            overlay.hotkey_toggle_in_game_overlay_edit()

    def stop_in_game_overlay(self) -> None:
        overlay = self.__dict__.get("_in_game_overlay")
        if overlay is not None:
            overlay.stop_in_game_overlay()

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

    # -- scanner surface (step 25c) ----------------------------------------
    #
    # Six delegators, and the list is the measurement rather than a convenience
    # set. Each is called *on the application* by something step 25 may not
    # touch: `gui_layout` connects the Start/Stop button to `toggle_main_loop`,
    # calls `update_status_ui` after building the footer and `_build_session_
    # stats_tab` while assembling the right-hand tabs -- and that router is
    # **step 26's**. `log` has fourteen production callers across eleven
    # modules. `SettingsDialog` reaches `master.update_status_ui` and
    # `master.log` after a save, with `master=self` meaning the application for
    # the reason documented above `open_settings_dialog`.
    #
    # `update_timer` is the session clock this class starts in `__init__`.
    def toggle_main_loop(self) -> None:
        self._scanner.toggle_main_loop()

    def update_status_ui(self) -> None:
        self._scanner.update_status_ui()

    # Guarded, because `TemplateRuntimeFilters` is built before the scanner and
    # takes `log` as a port: a construction fault between the two would
    # otherwise turn a log line into an `AttributeError` through
    # `__getattr__`'s window forwarding. Silent is also what `Scanner.log`
    # itself does without an invoker, so this does not add a new failure shape.
    def log(self, message, tag=None) -> None:
        scanner = self.__dict__.get("_scanner")
        if scanner is not None:
            scanner.log(message, tag=tag)

    def update_timer(self) -> None:
        self._scanner.update_timer()

    def _build_session_stats_tab(self) -> None:
        self._scanner.build_session_stats_tab()

    # -- run-control surface (step 25c) ------------------------------------
    #
    # Three, for `SettingsDialog` (which re-registers hotkeys and re-applies
    # the run-control mode on save, both under `hasattr(self.master, ...)`) and
    # for this class's own construction. Nothing else in production calls run
    # control on the app: `gui_in_game_overlay`'s three window/scan ports were
    # repointed at the components they were always about, which is what its own
    # step-24 note said step 25 would do.
    def setup_hotkeys(self) -> None:
        self._run_control.setup_hotkeys()

    def apply_run_control_mode(self, *, detach_hooks: bool = True) -> None:
        self._run_control.apply_run_control_mode(detach_hooks=detach_hooks)

    def check_admin_rights(self) -> None:
        self._run_control.check_admin_rights()

    # -- application shutdown (step 25b) -----------------------------------
    #
    # This was `ScannerMixin.on_closing`. Only two of its steps are the
    # scanner's; the other seven owners it drives -- the layout's pending tab
    # transition, the coordinator's memory clients, the OBS server, the in-game
    # overlay, the Twitch bot and its auth thread, the VOD recorder, the hotkey
    # manager and the window -- were reached through ambient `self` on the
    # shared namespace, and were nine of `gui_scanner`'s 29 hidden reads.
    #
    # The three `hasattr` guards that stood on `close_overlay_server`,
    # `stop_in_game_overlay` and `stop_twitch_bot` are gone, and that is a
    # deliberate deletion rather than a tidy-up. They were written when the
    # scanner could not know whether an app double carried those features; here
    # all three are methods of the class this method belongs to, so the guard is
    # always true and would only ever hide a *rename*. `hasattr` covering a name
    # the same class defines is the silent-shutdown-skip shape step 19 recorded
    # -- it converts "this method moved" into "this feature stopped shutting
    # down", with a green suite. Each of the three already guards its own
    # missing component internally, which is where that decision belongs.
    def on_closing(self):
        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True
        self._cancel_right_tab_transition()
        self._scanner.shutdown()
        # The coordinator owns the three memory clients (step 12b), so it closes
        # them (step 12c). App doubles built without a coordinator fall back to the
        # mixin close methods, preserving the shutdown order those tests assert.
        coordinator = getattr(self, "coordinator", None)
        if coordinator is not None:
            coordinator.shutdown()
        else:
            self._scanner.close_client()
            player_stats_memory(self).close_player_stats_client()
            player_stats_memory(self).close_player_stats_game_data_client()
        self.close_overlay_server()
        self.stop_in_game_overlay()
        self.stop_twitch_bot()
        if getattr(self, "twitch_auth_thread", None) is not None:
            self.twitch_auth_thread._shutdown_server()
            self.twitch_auth_thread.wait(2000)
        player_stats_vod_recorder = self.__dict__.get("player_stats_vod_recorder")
        if player_stats_vod_recorder is not None:
            if player_stats_vod_recorder.is_recording:
                player_stats_vod_recorder.stop()
            else:
                player_stats_vod_recorder.close()
        self._run_control.stop_hotkeys()
        self.destroy()

    # Scheduled 1.5s into `__init__`. It hands *the application* to the update
    # flow, which reaches back for `log`, the window and the settings it
    # prompts about; it had nothing to do with the scan loop beyond sharing a
    # namespace with it.
    def deferred_update_check(self):
        start_update_check(self, force_check=False)

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
