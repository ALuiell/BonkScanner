from __future__ import annotations

import os

from ui.shared import (
    _apply_button_icon,
    _make_scroll_section,
    resource_path,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.snapshot_store import live_snapshot_store
from app.vod_capture import vod_capture
from core.stats.formats import PlayerStatFormat

LIVE_STATS_CARD_COLUMNS = 3
LIVE_STATS_VALUE_WIDTH = 64
RECORDINGS_STATS_CARD_COLUMNS = 3
RECORDINGS_LIST_MIN_WIDTH = 190
RECORDINGS_LIST_MAX_WIDTH = 280
STAGE_SUMMARY_COLUMN_BASELINES = {
    "stage": "Stage",
    "time": "59:59",
    "kills": "999,999",
    "items": "\u25cf 99 \u25cf 99 \u25cf 99 \u25cf 99",
}
STAGE_SUMMARY_COLUMN_PADDING = 8
SUMMARY_LABEL_BASELINE_PADDING = 8
RUN_SUMMARY_LABEL_BASELINES = {
    "chests_per_minute": "Average chests/min: 999.99",
    "powerups_duration": "Powerups: 999.9s | Clock: 999.9s",
    "in_game_time": "In-Game Time: 99:59:59",
    "mob_kills": "Mob Kills: 999,999",
    "kps_averages": "KPS: 60s 999/s | 5m 999/s",
    "level": "Level: 999",
}
POWERUPS_CARD_LINE_BASELINE = "Stonks: 99:59 -> +99:59 (999.99s)"
PLAYER_STAT_VALUE_BASELINES = {
    PlayerStatFormat.FLAT: "999,999",
    PlayerStatFormat.PERCENT: "999.9%",
    PlayerStatFormat.MULTIPLIER: "999.9x",
}


def _reserve_label_baseline_width(label, baseline: str, padding: int = SUMMARY_LABEL_BASELINE_PADDING) -> None:
    metrics = QFontMetrics(label.font())
    width = max(metrics.horizontalAdvance(baseline), metrics.horizontalAdvance(label.text()))
    label.setMinimumWidth(max(label.minimumWidth(), width + padding))


def _retain_hidden_widget_size(widget) -> None:
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


def _build_chests_stats_card():
    card = QFrame()
    card.setObjectName("StatCard")
    layout = QFormLayout(card)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(4)
    values = {}
    for key, title in (
        ("maps", "Maps"),
        ("total", "Total"),
        ("paid_free", "Paid / Free"),
        ("key_procs", "Key Procs"),
        ("expected", "Expected"),
        ("keys", "Keys"),
    ):
        value_label = QLabel("--")
        value_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if key == "maps":
            value_label.setWordWrap(True)
        layout.addRow(title, value_label)
        values[key] = value_label
    return card, values


def _apply_run_summary_baselines(chests_per_minute_label, *labels) -> None:
    if len(labels) == 3:
        powerups_duration_label = None
        in_game_time_label, mob_kills_label, level_label = labels
        kps_averages_label = None
    elif len(labels) == 4:
        powerups_duration_label = None
        in_game_time_label, mob_kills_label, kps_averages_label, level_label = labels
    elif len(labels) == 5:
        powerups_duration_label, in_game_time_label, mob_kills_label, kps_averages_label, level_label = labels
    else:
        raise TypeError("_apply_run_summary_baselines() expects 4, 5, or 6 labels")
    _reserve_label_baseline_width(
        chests_per_minute_label,
        RUN_SUMMARY_LABEL_BASELINES["chests_per_minute"],
    )
    if powerups_duration_label is not None:
        _reserve_label_baseline_width(
            powerups_duration_label,
            RUN_SUMMARY_LABEL_BASELINES["powerups_duration"],
        )
    _reserve_label_baseline_width(
        in_game_time_label,
        RUN_SUMMARY_LABEL_BASELINES["in_game_time"],
    )
    _reserve_label_baseline_width(
        mob_kills_label,
        RUN_SUMMARY_LABEL_BASELINES["mob_kills"],
    )
    if kps_averages_label is not None:
        _reserve_label_baseline_width(
            kps_averages_label,
            RUN_SUMMARY_LABEL_BASELINES["kps_averages"],
        )
    _reserve_label_baseline_width(
        level_label,
        RUN_SUMMARY_LABEL_BASELINES["level"],
    )


def _apply_player_stat_value_baseline(label, value_format) -> None:
    baseline = PLAYER_STAT_VALUE_BASELINES.get(value_format, PLAYER_STAT_VALUE_BASELINES[PlayerStatFormat.FLAT])
    _reserve_label_baseline_width(label, baseline)


def _apply_stage_summary_column_baseline(layout, rows) -> None:
    for column, key in enumerate(("stage", "time", "kills", "items")):
        baseline = STAGE_SUMMARY_COLUMN_BASELINES[key]
        width = 0
        for row in rows:
            label = row[key]
            metrics = QFontMetrics(label.font())
            width = max(width, metrics.horizontalAdvance(baseline), metrics.horizontalAdvance(label.text()))
        layout.setColumnMinimumWidth(column, width + STAGE_SUMMARY_COLUMN_PADDING)


def _apply_powerups_card_baselines(labels_by_name) -> None:
    for label in labels_by_name.values():
        _reserve_label_baseline_width(label, POWERUPS_CARD_LINE_BASELINE)


class GuiLayoutMixin:

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        self._build_header(root_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter, 1)

        self._build_left_tabs(splitter)
        right_layout = self._build_right_panel(splitter)
        self._build_logs_tab()
        self._build_session_stats_tab()
        self._player_stats_view = _build_live_stats_view(self)
        self._recordings_view = _build_recordings_view(self)
        self._compare_runs_view = _build_compare_runs_view(self)
        self._build_overlay_tab()
        self._build_twitch_bot_tab()
        self._build_footer_controls(right_layout)

    def _build_header(self, root_layout):
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
        self.logo_label = logo_label
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


    def _build_left_tabs(self, splitter):
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(left_panel)

        self.left_tabview = QTabWidget()
        self.left_tabview.currentChanged.connect(self.on_left_tab_changed)
        left_layout.addWidget(self.left_tabview)

        self.tab_templates = QWidget()
        templates_layout = QVBoxLayout(self.tab_templates)
        self.scrollable_templates, _templates_content, self.template_layout = _make_scroll_section()
        templates_layout.addWidget(self.scrollable_templates, 1)
        template_buttons = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.add_btn.clicked.connect(self.add_template_dialog)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self.edit_template_dialog)
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("DangerButton")
        self.del_btn.clicked.connect(self.del_template_dialog)
        template_buttons.addWidget(self.add_btn)
        template_buttons.addWidget(self.edit_btn)
        template_buttons.addWidget(self.del_btn)
        template_buttons.addStretch(1)
        templates_layout.addLayout(template_buttons)
        self.left_tabview.addTab(self.tab_templates, "Templates")

        self.tab_scores = QWidget()
        scores_layout = QVBoxLayout(self.tab_scores)
        scores_group = QGroupBox("Active Tiers")
        self.scores_templates_layout = QVBoxLayout(scores_group)
        scores_layout.addWidget(scores_group)
        self.scores_desc_label = QTextEdit()
        self.scores_desc_label.setReadOnly(True)
        scores_layout.addWidget(self.scores_desc_label, 1)
        scores_buttons = QHBoxLayout()
        self.edit_scores_btn = QPushButton("Edit Settings")
        _apply_button_icon(self.edit_scores_btn, "media/settings_icon.png", 18)
        self.edit_scores_btn.clicked.connect(self.open_scores_settings_dialog)
        scores_buttons.addWidget(self.edit_scores_btn)
        scores_buttons.addStretch(1)
        scores_layout.addLayout(scores_buttons)
        self.left_tabview.addTab(self.tab_scores, "Scores")
        self.left_tabview.setCurrentIndex(1 if config.EVALUATION_MODE == "scores" else 0)


    def _build_right_panel(self, splitter):
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(right_panel)
        splitter.setSizes([290, 970])

        self.tabview = QTabWidget()
        self.tabview.currentChanged.connect(self.on_right_tab_changed)
        right_layout.addWidget(self.tabview, 1)

        return right_layout

    def _build_logs_tab(self):
        self.tab_logs = QWidget()
        logs_layout = QVBoxLayout(self.tab_logs)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 11))
        logs_layout.addWidget(self.log_box)
        self.tabview.addTab(self.tab_logs, "Logs")







    def _build_footer_controls(self, right_layout):
        controls = QHBoxLayout()
        self.settings_btn = QPushButton("")
        self.settings_btn.setObjectName("SettingsButton")
        _apply_button_icon(self.settings_btn, "media/settings_icon.png", 20)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        self.help_btn = QPushButton("")
        self.help_btn.setObjectName("HelpButton")
        _apply_button_icon(self.help_btn, "media/help_icon.svg", 20)
        self.help_btn.setToolTip("Help")
        self.help_btn.clicked.connect(self.open_help_dialog)
        self.status_label = QLabel("Status: <span style='color:#9CA3AF;'>IDLE</span>")
        self.status_label.setTextFormat(Qt.RichText)
        self.status_label.setObjectName("StatusLabel")
        self.toggle_btn = QPushButton("Start")
        self.toggle_btn.setObjectName("ToggleButton")
        self.toggle_btn.clicked.connect(self.toggle_main_loop)
        controls.addWidget(self.settings_btn)
        controls.addWidget(self.help_btn)
        controls.addWidget(self.status_label, 1)
        controls.addWidget(self.toggle_btn)
        right_layout.addLayout(controls)

    def on_left_tab_changed(self):
        if self.left_tabview is None:
            return
        tab_name = self.left_tabview.tabText(self.left_tabview.currentIndex())
        config.EVALUATION_MODE = "scores" if tab_name == "Scores" else "templates"
        config.user_config["EVALUATION_MODE"] = config.EVALUATION_MODE
        config.save_config(config.user_config)
        self.refresh_scores_ui()
        self._sync_runtime_filters(announce=True)
        self.update_status_ui()

    def on_right_tab_changed(self):
        self._show_right_tab_transition_cover()
        if self._is_recordings_tab_active():
            self.refresh_vods_list()
            if hasattr(self, "ensure_recordings_chooser_for_empty_selection"):
                self.ensure_recordings_chooser_for_empty_selection()
        if self._is_compare_runs_tab_active():
            self.refresh_compare_runs_list()
            if hasattr(self, "ensure_compare_runs_chooser_for_empty_selection"):
                self.ensure_compare_runs_chooser_for_empty_selection()
        self.after_idle(self._refresh_right_tab_after_switch)

    def _refresh_right_tab_after_switch(self):
        if self._is_recordings_tab_active():
            self.refresh_vods_list()
            if hasattr(self, "ensure_recordings_chooser_for_empty_selection"):
                self.ensure_recordings_chooser_for_empty_selection()
        if self._is_compare_runs_tab_active():
            self.refresh_compare_runs_list()
            if hasattr(self, "ensure_compare_runs_chooser_for_empty_selection"):
                self.ensure_compare_runs_chooser_for_empty_selection()
        if self._is_live_stats_tab_active():
            self.refresh_live_player_stats_now()
        if self._is_overlay_tab_active():
            self.refresh_overlay_ui()

    def _show_right_tab_transition_cover(self):
        return None

    def _cancel_right_tab_transition(self):
        return None

    def _is_live_stats_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Live Stats"

    def _is_overlay_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "OBS Overlay"

    def _is_recordings_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Recordings"

    def _is_compare_runs_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Compare Runs"
    def _refresh_vods_list_if_visible(self):
        if self._is_recordings_tab_active():
            self.refresh_vods_list()
        if self._is_compare_runs_tab_active():
            self.refresh_compare_runs_list()


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
        is_active=app._is_compare_runs_tab_active,
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
    router: `on_right_tab_changed` and `_refresh_vods_list_if_visible` stay
    `gui_layout`'s until step 26.

    Imported inside the function body for the reason `_build_live_stats_view`
    records: `recordings` imports this module for its layout helpers, so a
    module-scope import here is a cycle -- invisible to the suite and to
    `test_import_direction`, because both analyse ASTs rather than importing.
    """
    from ui.tabs.player_stats import RecordingsTab

    view = RecordingsTab(
        tabview=app.tabview,
        vod_library=app.vod_library,
        window=lambda: app.window,
        vod_recorder=lambda: app.player_stats_vod_recorder,
        is_active=app._is_recordings_tab_active,
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

    Imported inside the function body: `live_stats` imports this module for its
    layout helpers, so a module-scope import here is the cycle step 19 already
    shipped once -- invisible to the suite and to `test_import_direction`,
    because both analyse ASTs rather than importing.
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
