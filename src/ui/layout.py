"""The main window's layout, and the router that runs its tab bars.

``gui_layout.py`` until step 27b, which moved it here and closed the last two
``TOPLEVEL_DEBT`` entries. It could not move as one file: see
``ui/tabs/player_stats/metrics.py`` for what came out of it first and why the
split was the point rather than the move.

What is left reads ``app``, ``core`` and ``ui`` -- all of which §2 lets ``ui``
import -- plus ``ui.dialogs``, which was ``gui_dialogs`` until 27a. The two
builders that import ``ui.tabs.player_stats`` inside their bodies keep doing
so; with the metrics gone that is no longer covering a cycle, but it is also
not this step's to change, so the comments there now say which of the two
reasons still applies.
"""
from __future__ import annotations

import os

from ui.shared import (
    _apply_button_icon,
    resource_path,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs import (
    DeleteDialog,
    ScoresSettingsDialog,
    TemplateDialog,
    TemplateManagerDialog,
)

from app import config
from app.snapshot_store import live_snapshot_store
from app.vod_capture import vod_capture


def _is_tab_active(tabview, label: str) -> bool:
    """Is `label` the tab currently showing in `tabview`?

    Module-level and handed its tab bar, rather than four one-line methods
    reading `self.tabview`, because it has two callers that are not the same
    object: `TabRouter`, which asks it about the bar it routes, and
    `MegabonkApp`, whose two surviving predicates are called *on the
    application* by `app/` modules that may not import a UI component
    (`player_stats_memory`, `player_stats_refresh`, `refresh_tasks`,
    `vod_capture`) and by `gui_overlay.build_overlay`. One implementation, two
    callers, no ambient `self` -- the shape steps 19 and 24a took for the same
    reason: a free function has no class to be orphaned from.

    The `None` guard is new and deliberate. The four predicates this replaces
    read `self.tabview.tabText(...)` unguarded, which raises before the tab bar
    exists -- and Qt **swallows exceptions raised inside a slot**, so a router
    firing early would degrade into a traceback on stderr with no other
    symptom. That is the failure shape steps 21 and 22c each shipped once.
    "No tab is active because there is no tab bar" is the same answer with no
    way to hide.
    """
    if tabview is None:
        return False
    return tabview.tabText(tabview.currentIndex()) == label


class TabRouter:
    """What happens when the user switches a tab.

    `GuiLayoutMixin`'s last responsibility, and the reason `MegabonkApp` still
    had a base class. Eight methods that read `self.tabview`,
    `self.left_tabview` and `self._templates_panel` out of the shared
    namespace, and called *thirteen* delegators on the application to reach
    components the app was already holding -- eleven of which had no other
    production caller, and are gone with this object.

    **Every port is a supplier, and that is the measurement rather than
    style.** `_build_left_tabs` and `_build_right_panel` connect
    `currentChanged` **before** `addTab` populates either panel, so these slots
    fire during `build_layout`, while `_templates_panel`, `_recordings_view`
    and `_compare_runs_view` are still `None`. A router holding values captured
    at construction would hold `None` for the life of the application. Keeping
    the connect at the same two points is what keeps the initial firing order
    identical, which `tools/step23_startup_smoke.py` is the only check that
    can see.

    That firing order is also why each view is guarded. The four
    `hasattr(self, "ensure_..._chooser_for_empty_selection")` checks this
    replaces were permanently **true** -- `MegabonkApp` has defined both names
    since step 21c -- so they guarded nothing while reading as if they guarded
    construction order. The `is None` checks below guard the question those
    `hasattr` calls were misspelling. Removing the `hasattr` and adding the
    real guard is one edit on purpose: step 25b recorded what happens when a
    `hasattr` covering a method of the same class outlives the method, and it
    is "the feature silently stopped working" with a green suite.
    """

    def __init__(
        self,
        *,
        left_tabview,
        tabview,
        templates_panel,
        recordings_view,
        compare_runs_view,
        overlay,
        template_filters,
        update_status,
        refresh_live_player_stats,
        schedule_idle,
    ) -> None:
        self._left_tabview = left_tabview
        self._tabview = tabview
        self._templates_panel = templates_panel
        self._recordings_view = recordings_view
        self._compare_runs_view = compare_runs_view
        self._overlay = overlay
        self._template_filters = template_filters
        self._update_status = update_status
        self._refresh_live_player_stats = refresh_live_player_stats
        self._schedule_idle = schedule_idle

    # -- the left bar: Templates <-> Scores --------------------------------
    #
    # This writes `config.json` on **every** left tab switch, and it fires
    # during `build_layout` when `_build_left_tabs` calls `setCurrentIndex`.
    # Any harness that constructs a real app must stub `config.save_config`
    # before doing so or it overwrites the user's file.
    def on_left_tab_changed(self) -> None:
        left_tabview = self._left_tabview()
        if left_tabview is None:
            return
        tab_name = left_tabview.tabText(left_tabview.currentIndex())
        config.EVALUATION_MODE = "scores" if tab_name == "Scores" else "templates"
        config.user_config["EVALUATION_MODE"] = config.EVALUATION_MODE
        config.save_config(config.user_config)
        templates_panel = self._templates_panel()
        if templates_panel is not None:
            templates_panel.refresh_scores_ui()
        self._template_filters.sync(announce=True)
        self._update_status()

    # -- the right bar ------------------------------------------------------
    def on_right_tab_changed(self) -> None:
        self._refresh_recording_tabs()
        self._schedule_idle(self._refresh_right_tab_after_switch)

    def _refresh_right_tab_after_switch(self) -> None:
        self._refresh_recording_tabs()
        if self.is_live_stats_tab_active():
            self._refresh_live_player_stats()
        if self.is_overlay_tab_active():
            self._overlay.refresh_overlay_ui()

    def _refresh_recording_tabs(self) -> None:
        """The eight lines both right-bar handlers ran, run from one place.

        **This still runs twice per switch, and that is preserved rather than
        fixed.** `on_right_tab_changed` refreshes synchronously and then
        schedules `_refresh_right_tab_after_switch`, which refreshes again --
        so switching to Recordings re-reads the list once before the repaint
        and once after. Step 26 measured the duplication and did not remove it:
        the two passes straddle Qt's redraw, `VodLibrary` is what absorbs the
        second read, and a step whose subject is the router's *ownership* is
        not the place to change how often it fires. De-duplicating the text is
        not de-duplicating the calls -- the call count is identical to what the
        two copies produced.
        """
        recordings_view = self._recordings_view()
        if recordings_view is not None and self.is_recordings_tab_active():
            recordings_view.refresh_vods_list()
            recordings_view.ensure_recordings_chooser_for_empty_selection()
        compare_runs_view = self._compare_runs_view()
        if compare_runs_view is not None and self.is_compare_runs_tab_active():
            compare_runs_view.refresh_compare_runs_list()
            compare_runs_view.ensure_compare_runs_chooser_for_empty_selection()

    def is_live_stats_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "Live Stats")

    def is_overlay_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "OBS Overlay")

    def is_recordings_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "Recordings")

    def is_compare_runs_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "Compare Runs")

    # `RecordingsListView`'s single operation (`app/player_stats_view.py`).
    # The underscore is the protocol's, not a privacy claim: `vod_capture` and
    # `player_stats_refresh` call this name through `recordings_list_view()`,
    # whose fallback to the app object was scheduled to die with this step and
    # does -- `_build_tab_router` injects this object as `_recordings_list_view`.
    def _refresh_vods_list_if_visible(self) -> None:
        recordings_view = self._recordings_view()
        if recordings_view is not None and self.is_recordings_tab_active():
            recordings_view.refresh_vods_list()
        compare_runs_view = self._compare_runs_view()
        if compare_runs_view is not None and self.is_compare_runs_tab_active():
            compare_runs_view.refresh_compare_runs_list()


def build_layout(app):
    """Build the main window's layout. **`MegabonkApp`'s last base class.**

    This was `GuiLayoutMixin.setup_ui`, and the mixin existed for one reason:
    a method needs a `self`, and `self` was the application. Every widget it
    creates is assigned onto the app, every builder it calls was a sibling
    method found through the MRO, and the seventeen names it read but never
    assigned were the app's own API surface reached ambiently -- which is what
    made `MegabonkApp` a method namespace rather than a composition root.

    It is a function taking `app` now, which is the form the five view roots
    below have had since steps 19-23 and the form this file's own header has
    argued for since. Nothing about the sequence changed: same builders, same
    order, same tab positions. What changed is that `app` is a parameter with
    a name instead of an ambient `self`, so every one of those reads is
    visible at the call site and none of them is hidden.

    `app.window.setCentralWidget`, not `app.setCentralWidget`, is the only
    behavioural detail here worth a line. It was the one hidden read in this
    file whose owner was not the application: `MegabonkApp.__getattr__`
    forwards unknown names to `self.window`, so it resolved onto the
    `_AppWindow` by accident of the shell. Naming the window is the same call
    with the receiver written down.
    """
    app._tab_router = _build_tab_router(app)
    central = QWidget()
    app.window.setCentralWidget(central)
    root_layout = QVBoxLayout(central)
    root_layout.setContentsMargins(10, 10, 10, 10)
    root_layout.setSpacing(10)

    _build_header(app, root_layout)

    splitter = QSplitter(Qt.Horizontal)
    splitter.setChildrenCollapsible(False)
    root_layout.addWidget(splitter, 1)

    _build_left_tabs(app, splitter)
    right_layout = _build_right_panel(app, splitter)
    _build_logs_tab(app)
    app._scanner.build_session_stats_tab()
    app._player_stats_view = _build_live_stats_view(app)
    app._recordings_view = _build_recordings_view(app)
    app._compare_runs_view = _build_compare_runs_view(app)
    app.tabview.addTab(app._overlay.build(), "OBS Overlay")
    # The ~240 lines that built the Twitch tab's widgets are
    # `TwitchTab.build()`'s now (step 23b).
    app._twitch_tab = _build_twitch_tab(app)
    # These two lines were the last two of `_build_twitch_bot_tab` (step
    # 23a). The Twitch tab builder built the In-Game Overlay tab as well and
    # added it to the tab bar, which is where two of `gui_twitch.py`'s nine
    # hidden reads came from -- `_build_in_game_overlay_tab` and
    # `tab_in_game_overlay`. The in-game overlay is step 24's subject, so
    # nothing about it moves here: only the call site, hoisted to the
    # builder list it belongs in, in the position that keeps the tab bar's
    # order identical.
    app.tabview.addTab(app._in_game_overlay.build(), "In-Game Overlay")
    _build_footer_controls(app, right_layout)


def _build_header(app, root_layout):
    header_wrap = QWidget()
    header = QVBoxLayout(header_wrap)
    header.setContentsMargins(0, 4, 0, 8)
    header.setSpacing(6)
    header.setAlignment(Qt.AlignHCenter)

    title = QLabel("BonkScanner")
    title.setObjectName("SectionHeader")
    title.setAlignment(Qt.AlignHCenter)
    header.addWidget(title, 0, Qt.AlignHCenter)

    logo_label = QLabel()
    app.logo_label = logo_label
    logo_label.setAlignment(Qt.AlignHCenter)
    logo_path = resource_path("media/bonkscanner_icon2.png")
    if os.path.exists(logo_path):
        pixmap = QPixmap(logo_path)
        if not pixmap.isNull():
            logo_label.setPixmap(
                pixmap.scaled(72, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            logo_label.setText("BONK")
    else:
        logo_label.setText("BONK")
    header.addWidget(logo_label, 0, Qt.AlignHCenter)
    root_layout.addWidget(header_wrap)


def _build_left_tabs(app, splitter):
    left_panel = QWidget()
    left_layout = QVBoxLayout(left_panel)
    left_layout.setContentsMargins(0, 0, 0, 0)
    splitter.addWidget(left_panel)

    app.left_tabview = QTabWidget()
    app.left_tabview.currentChanged.connect(app._tab_router.on_left_tab_changed)
    left_layout.addWidget(app.left_tabview)

    # The ~34 lines that built both left tabs are `TemplatesPanel.build()`'s
    # now (step 22c). Which tab opens stays here: that is a router question,
    # and the router is an object as of step 26 -- but *which index the bar
    # opens on* is the layout's, and `setCurrentIndex` is what fires the
    # router's first left-bar slot, one line after the connect above.
    app._templates_panel = _build_templates_panel(app)
    app.left_tabview.setCurrentIndex(1 if config.EVALUATION_MODE == "scores" else 0)


def _build_right_panel(app, splitter):
    right_panel = QWidget()
    right_layout = QVBoxLayout(right_panel)
    right_layout.setContentsMargins(0, 0, 0, 0)
    splitter.addWidget(right_panel)
    splitter.setSizes([290, 970])

    app.tabview = QTabWidget()
    # Connected before a single `addTab` runs, and deliberately left that way:
    # see `TabRouter`'s header. Every `addTab` in `build_layout` fires this.
    app.tabview.currentChanged.connect(app._tab_router.on_right_tab_changed)
    right_layout.addWidget(app.tabview, 1)

    return right_layout


def _build_logs_tab(app):
    app.tab_logs = QWidget()
    logs_layout = QVBoxLayout(app.tab_logs)
    app.log_box = QTextEdit()
    app.log_box.setReadOnly(True)
    app.log_box.setFont(QFont("Consolas", 11))
    logs_layout.addWidget(app.log_box)
    app.tabview.addTab(app.tab_logs, "Logs")







def _build_footer_controls(app, right_layout):
    controls = QHBoxLayout()
    app.settings_btn = QPushButton("")
    app.settings_btn.setObjectName("SettingsButton")
    _apply_button_icon(app.settings_btn, "media/settings_icon.png", 20)
    app.settings_btn.setToolTip("Settings")
    app.settings_btn.clicked.connect(app.open_settings_dialog)
    app.help_btn = QPushButton("")
    app.help_btn.setObjectName("HelpButton")
    _apply_button_icon(app.help_btn, "media/help_icon.svg", 20)
    app.help_btn.setToolTip("Help")
    app.help_btn.clicked.connect(app.open_help_dialog)
    app.status_label = QLabel("Status: <span style='color:#9CA3AF;'>IDLE</span>")
    app.status_label.setTextFormat(Qt.RichText)
    app.status_label.setObjectName("StatusLabel")
    app.toggle_btn = QPushButton("Start")
    app.toggle_btn.setObjectName("ToggleButton")
    # The scan component, not `app.toggle_main_loop`. The application carried
    # that delegator only because this line ran with the app as `self`; 26c
    # deletes it. `open_settings_dialog` and `open_help_dialog` above stay on
    # the app for the opposite reason -- `SettingsDialog(window, master=self)`
    # has to mean the application, and `gui_app` records what breaks if the
    # `master` reads go quietly false.
    app.toggle_btn.clicked.connect(app._scanner.toggle_main_loop)
    controls.addWidget(app.settings_btn)
    controls.addWidget(app.help_btn)
    controls.addWidget(app.status_label, 1)
    controls.addWidget(app.toggle_btn)
    right_layout.addLayout(controls)


def _build_tab_router(app):
    """Construct the tab-switch router and name its ten collaborators.

    The composition root for `TabRouter` (step 26), called from the first line
    of `setup_ui` -- before `_build_left_tabs` and `_build_right_panel`, which
    is the whole constraint. Both connect `currentChanged` before populating
    their bar, so the router has to exist before either runs and cannot be
    handed a single widget that does.

    Six of the ten are late-bound suppliers, for the reason `TabRouter`'s
    header records: they name objects that do not exist yet at this line. The
    remaining four are real references to collaborators `gui_app.__init__`
    built before it called `setup_ui` -- the overlay component, the runtime
    filters, and two pieces of application surface that survive this step
    because `app/` and `gui_dialogs` call them on the application.

    `_recordings_list_view` is assigned here rather than in `gui_app.__init__`
    for the same reason `_build_recordings_view` registers its tab with
    `VodLibrary` here: the implementer does not exist until the layout is
    built. This assignment is what closes `recordings_list_view()`'s fallback
    to the app object -- scheduled for this step by
    `app/player_stats_view.py`'s docstring since step 19, and the last of the
    three port fallbacks that split created.
    """
    router = TabRouter(
        left_tabview=lambda: app.left_tabview,
        tabview=lambda: app.tabview,
        templates_panel=lambda: app._templates_panel,
        recordings_view=lambda: app._recordings_view,
        compare_runs_view=lambda: app._compare_runs_view,
        overlay=app._overlay,
        template_filters=app._template_filters,
        update_status=app.update_status_ui,
        refresh_live_player_stats=app.refresh_live_player_stats_now,
        schedule_idle=app.after_idle,
    )
    app._recordings_list_view = router
    return router


def _build_twitch_tab(app):
    """Construct the Twitch tab and add it to the right-hand tab bar.

    The composition root for `TwitchTab` (step 23b), kept at the exact point in
    `setup_ui` where `self._build_twitch_bot_tab()` used to be called, so the
    tab keeps its position and label in the tab bar.

    The tab takes no collaborators. It builds widgets and reports what is on
    them; every decision -- which config key a value lands in, whether a token
    is valid, when a worker starts -- belongs to the session object that step
    23c introduces, and `bind()` hands it the handlers later, from
    `gui_app.__init__`, where `setup_twitch_bot_ui` connected them before.

    `addTab` is here rather than in `build()` because the tab bar is not the
    tab's to know about: reaching `self.tabview` from inside the Twitch code is
    one of the seven ambient reads step 23 exists to remove.
    """
    from ui.tabs.twitch import TwitchTab

    view = TwitchTab()
    app.tabview.addTab(view.build(), "Twitch Bot")
    return view


def _build_templates_panel(app):
    """Construct the templates panel and name its eight collaborators.

    The composition root for `TemplatesPanel` (step 22c), kept at the exact
    point in `_build_left_panel` where the two tabs used to be built inline, so
    they keep their position and order in the left tab bar.

    Five of the eight are dialog factories. That is not ceremony: the layer
    table lets `ui/` import `app`, `projections` and `core`, and `gui_dialogs`
    is none of those. `ui/tabs/player_stats/recordings.py` reaches it through a
    `TOPLEVEL_DEBT` entry and that allowlist may only shrink, so the panel takes
    the dialogs as arguments and this module -- which is top-level and may
    import them freely -- supplies them. It is also what the roadmap asks for in
    as many words: shared dialogs passed as narrow UI dependencies rather than
    discovered through `self`.

    `sync_filters` points at the step-22b owner, not at the app's delegator, so
    the panel does not reach back through `MegabonkApp` to get to an object the
    app already holds.

    `window` is a supplier rather than the widget, for the reason
    `_build_recordings_view` records: this runs during `setup_ui`, and a
    captured `app.window` would freeze whatever it was at that moment.
    """
    from ui.tabs.templates import TemplatesPanel

    view = TemplatesPanel(
        left_tabview=app.left_tabview,
        window=lambda: app.window,
        sync_filters=app._template_filters.sync,
        template_dialog=TemplateDialog,
        template_manager_dialog=TemplateManagerDialog,
        delete_dialog=DeleteDialog,
        scores_settings_dialog=ScoresSettingsDialog,
        no_custom_templates_message=lambda parent: QMessageBox.information(
            parent, "No Custom Templates", "There are no custom templates to delete."
        ),
    )
    view.build()
    return view


def _build_compare_runs_view(app):
    """Construct the Compare Runs tab and name its three collaborators.

    The composition root for `CompareRunsTab` (step 21d), kept at the exact
    point in `setup_ui` where `self._build_compare_runs_tab()` used to be
    called so the tab keeps its position in the tab bar.

    The ~250 lines that built this tab's widgets moved *into* the tab. They were
    here because step 9 split the tab out as a mixin and left its construction
    behind; `_build_compare_run_panel` even had to import `ItemsSectionView`
    inside its body to dodge the resulting import cycle. Both are gone.

    Fewer collaborators than `RecordingsTab` needs, and that is the
    measurement, not an oversight: this tab opens no dialogs, so it needs no
    `window`; it writes no log lines; and it reads no recorder.
    """
    from ui.tabs.compare_runs import CompareRunsTab

    view = CompareRunsTab(
        tabview=app.tabview,
        vod_library=app.vod_library,
        is_active=app._tab_router.is_compare_runs_tab_active,
        schedule=lambda callback: (
            app.after(0, callback) if app._invoker is not None else callback()
        ),
    )
    view.build()
    app.vod_library.subscribe(
        invalidate=view.invalidate_compare_runs_list,
        repaint=view.refresh_compare_runs_list,
    )
    return view


def _build_recordings_view(app):
    """Construct the Recordings tab and name its six collaborators.

    The composition root for `RecordingsTab` (step 21c), kept at the exact point
    in `setup_ui` where `self._build_recordings_tab()` used to be called so the
    tab keeps its position in the tab bar.

    This is also where the tab is registered with `VodLibrary`. Registration
    cannot happen in `MegabonkApp.__init__` alongside the library itself: the
    tabs do not exist until `setup_ui` runs, and a subscriber list built before
    its subscribers is the ambient-namespace habit in a new spelling.

    `is_active` hands the tab the tab-bar question without handing it the
    router. It named `app._is_recordings_tab_active` until step 26 made the
    router an object; it names the router's own predicate now, which is the
    same answer from the object that owns the question rather than from a
    delegator the application only carried because the router lived on it.

    Imported inside the function body for the reason `_build_live_stats_view`
    records -- but read that reason as history now. `recordings` imported this
    module for its layout helpers, which made a module-scope import here a
    cycle; step 27b moved those helpers into
    `ui/tabs/player_stats/metrics.py`, a leaf of the tab package, so the cycle
    no longer exists and `recordings` imports the metrics directly. What is
    left is a deferral with nothing behind it. Promoting it is a decision with
    its own startup-order risk and no debt entry demanding it, so 27b records
    the change rather than making it.
    """
    from ui.tabs.player_stats import RecordingsTab

    view = RecordingsTab(
        tabview=app.tabview,
        vod_library=app.vod_library,
        window=lambda: app.window,
        vod_recorder=lambda: app.player_stats_vod_recorder,
        is_active=app._tab_router.is_recordings_tab_active,
        log=app.log,
        schedule=lambda callback: (
            app.after(0, callback) if app._invoker is not None else callback()
        ),
    )
    view.build()
    app.vod_library.subscribe(
        invalidate=view.invalidate_vods_list,
        repaint=view.refresh_vods_list,
        failed=view.on_vod_metadata_refresh_failed,
    )
    return view


def _build_live_stats_view(app):
    """Construct the Live Stats tab and name its ten collaborators.

    The composition root for `LiveStatsTab`, kept at the exact point in
    `_build_layout` where `_build_live_stats_tab()` used to be called so the
    tab keeps its position in the tab bar.

    Every argument is a supplier rather than a value, for the reason
    `RecordingTimelineView` records: `live_run_tracker` is assigned by
    `initialize_overlay_runtime` after `__init__` starts, `vod_capture`
    reassigns the snapshot list, and `player_stats_refresh` moves the selected
    index. A component holding the value would go stale exactly where the
    mixin reading `self` did not.

    Imported inside the function body: `live_stats` imported this module for
    its layout helpers, which made a module-scope import here the cycle step 19
    already shipped once -- invisible to the suite *and* to
    `test_import_direction`, because both analyse ASTs rather than importing.
    Step 27b split those helpers into `ui/tabs/player_stats/metrics.py` and
    `live_stats` now takes them at module level, so the cycle is gone. The
    deferral stays for the reason `_build_recordings_view` records: nothing
    requires removing it, and `test_deferred_imports` pins it as its live
    sample.
    """
    from ui.tabs.player_stats import LiveStatsTab

    def _select_snapshot(index, *, pinned):
        app.player_stats_selected_snapshot_index = index
        app.player_stats_snapshot_pinned = pinned

    view = LiveStatsTab(
        tabview=app.tabview,
        live_run_tracker=lambda: app.live_run_tracker,
        vod_recorder=lambda: app.player_stats_vod_recorder,
        vod_snapshots=lambda: app.player_stats_vod_snapshots,
        selected_snapshot_index=lambda: app.player_stats_selected_snapshot_index,
        recording_waiting_mode=lambda: vod_capture(app).recording_waiting_mode,
        ensure_live_snapshot_store=lambda: live_snapshot_store(app),
        is_recording_armed=lambda: vod_capture(app).is_recording_armed(),
        on_toggle_recording=lambda: vod_capture(app).toggle_recording(),
        on_snapshot_selected=_select_snapshot,
    )
    return view.build()
