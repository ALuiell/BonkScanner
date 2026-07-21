from __future__ import annotations

import os

from ui.shared import (
    _apply_button_icon,
    _apply_summary_label_padding,
    _make_scroll_section,
    resource_path,
)
from ui.styles import (
    ITEM_SORT_LABELS,
    PLAYER_STATS_VALUE_WIDTH,)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
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
from core.stats.types import PLAYER_STAT_GROUPS
from projections.item_sort import ITEM_SORT_RARITY_DESC

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
        self._build_compare_runs_tab()
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







    def _build_compare_runs_tab(self):
        self.tab_compare_runs = QWidget()
        compare_layout = QVBoxLayout(self.tab_compare_runs)

        selected_row = QHBoxLayout()
        self.compare_runs_select_btn = QPushButton("Select Runs")
        self.compare_runs_select_btn.setProperty("class", "CompareRunsGhostButton")
        self.compare_runs_select_btn.clicked.connect(self.toggle_compare_runs_chooser)
        self.compare_runs_swap_btn = QPushButton("Swap")
        self.compare_runs_swap_btn.setProperty("class", "CompareRunsGhostButton")
        self.compare_runs_swap_btn.clicked.connect(self.swap_compare_runs)
        self.compare_runs_stats_config_btn = QPushButton("Compare Settings")
        self.compare_runs_stats_config_btn.setProperty("class", "CompareRunsGhostButton")
        self.compare_runs_stats_config_btn.clicked.connect(self.toggle_compare_runs_stats_config)
        selected_row.addStretch(1)
        selected_row.addWidget(self.compare_runs_select_btn)
        selected_row.addWidget(self.compare_runs_swap_btn)
        selected_row.addWidget(self.compare_runs_stats_config_btn)
        compare_layout.addLayout(selected_row)

        self.compare_runs_chooser_group = QGroupBox("Select Recordings")
        self.compare_runs_chooser_group.setVisible(False)
        chooser_layout = QVBoxLayout(self.compare_runs_chooser_group)
        selector_grid = QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(8)
        selector_grid.setVerticalSpacing(6)
        selector_grid.addWidget(QLabel("Run A"), 0, 0)
        selector_grid.addWidget(QLabel("Run B"), 0, 1)
        self.compare_run_a_list_frame = QListWidget()
        self.compare_run_b_list_frame = QListWidget()
        for list_frame in (self.compare_run_a_list_frame, self.compare_run_b_list_frame):
            list_frame.setMinimumHeight(230)
            list_frame.setMaximumHeight(320)
        self.compare_run_a_list_frame.currentItemChanged.connect(
            lambda current, _previous: self._on_compare_run_selection_changed("a", current)
        )
        self.compare_run_b_list_frame.currentItemChanged.connect(
            lambda current, _previous: self._on_compare_run_selection_changed("b", current)
        )
        selector_grid.addWidget(self.compare_run_a_list_frame, 1, 0)
        selector_grid.addWidget(self.compare_run_b_list_frame, 1, 1)
        selector_grid.setColumnStretch(0, 1)
        selector_grid.setColumnStretch(1, 1)
        chooser_layout.addLayout(selector_grid)
        compare_layout.addWidget(self.compare_runs_chooser_group)

        self.compare_runs_stats_config_group = QGroupBox("Compare Settings")
        self.compare_runs_stats_config_group.setVisible(False)
        settings_layout = QVBoxLayout(self.compare_runs_stats_config_group)
        section_layout = QHBoxLayout()
        configured_sections = self.configured_compare_run_sections()
        self.compare_runs_items_checkbox = QCheckBox("Items")
        self.compare_runs_items_checkbox.setChecked(configured_sections["items"])
        self.compare_runs_items_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        self.compare_runs_stage_summary_checkbox = QCheckBox("Stage Summary")
        self.compare_runs_stage_summary_checkbox.setChecked(configured_sections["stage_summary"])
        self.compare_runs_stage_summary_checkbox.stateChanged.connect(
            lambda _state: self.on_compare_run_section_selection_changed()
        )
        self.compare_runs_weapons_checkbox = QCheckBox("Weapons")
        self.compare_runs_weapons_checkbox.setChecked(configured_sections["weapons"])
        self.compare_runs_weapons_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        self.compare_runs_tomes_checkbox = QCheckBox("Tomes")
        self.compare_runs_tomes_checkbox.setChecked(configured_sections["tomes"])
        self.compare_runs_tomes_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        self.compare_runs_chaos_checkbox = QCheckBox("Chaos")
        self.compare_runs_chaos_checkbox.setChecked(configured_sections["chaos"])
        self.compare_runs_chaos_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        section_layout.addWidget(QLabel("Show in Difference:"))
        section_layout.addWidget(self.compare_runs_stage_summary_checkbox)
        section_layout.addWidget(self.compare_runs_items_checkbox)
        section_layout.addWidget(self.compare_runs_weapons_checkbox)
        section_layout.addWidget(self.compare_runs_tomes_checkbox)
        section_layout.addWidget(self.compare_runs_chaos_checkbox)
        section_layout.addStretch(1)
        settings_layout.addLayout(section_layout)

        settings_scroll, _settings_scroll_content, settings_scroll_layout = _make_scroll_section()
        settings_scroll.setMinimumHeight(150)
        settings_scroll.setMaximumHeight(240)

        stats_config_layout = QGridLayout()
        stats_config_layout.setContentsMargins(8, 8, 8, 8)
        stats_config_layout.setHorizontalSpacing(12)
        stats_config_layout.setVerticalSpacing(4)
        self.compare_runs_stat_checkboxes = {}
        stat_specs = [spec for group in PLAYER_STAT_GROUPS for spec in group]
        selected_defaults = set(self.configured_compare_run_stat_labels())
        for index, spec in enumerate(stat_specs):
            checkbox = QCheckBox(spec.label)
            checkbox.setChecked(spec.label in selected_defaults)
            checkbox.stateChanged.connect(lambda _state: self.on_compare_run_stat_selection_changed())
            self.compare_runs_stat_checkboxes[spec.label] = checkbox
            stats_config_layout.addWidget(checkbox, index // 4, index % 4)
        for column in range(4):
            stats_config_layout.setColumnStretch(column, 1)
        stats_group = QGroupBox("Stats Selector")
        stats_group.setLayout(stats_config_layout)
        settings_scroll_layout.addWidget(stats_group)
        settings_scroll_layout.addStretch(1)
        settings_layout.addWidget(settings_scroll)
        compare_layout.addWidget(self.compare_runs_stats_config_group)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(8)
        run_a_group, self.compare_run_a_status_label, self.compare_run_a_slider, self.compare_run_a_timeline_label, self.compare_run_a_summary_label = self._build_compare_run_panel(
            "Run A",
            "a",
        )
        diff_group = QGroupBox("Difference")
        diff_layout = QVBoxLayout(diff_group)
        diff_scroll, _diff_scroll_content, diff_scroll_layout = _make_scroll_section()
        self.compare_runs_diff_overview_group, self.compare_runs_diff_overview_label = self._build_compare_diff_card(
            "Overview",
            "Select two recordings",
        )
        self.compare_runs_diff_stats_group, self.compare_runs_diff_stats_label = self._build_compare_diff_card(
            "Stats",
            "--",
        )
        self.compare_runs_diff_items_group, self.compare_runs_diff_items_label = self._build_compare_diff_card(
            "Items",
            "--",
        )
        self.compare_runs_item_details_btn = QPushButton("Show Item Details")
        self.compare_runs_item_details_btn.setProperty("class", "SmallGhostButton")
        self.compare_runs_item_details_btn.clicked.connect(self.toggle_compare_runs_item_details)
        self.compare_runs_item_details_btn.setVisible(False)
        self.compare_runs_diff_items_group.layout().addWidget(self.compare_runs_item_details_btn, 0, Qt.AlignLeft)
        self.compare_runs_diff_stage_summary_group, self.compare_runs_diff_stage_summary_label = self._build_compare_diff_card(
            "Stage Summary",
            "--",
        )
        self.compare_runs_diff_weapons_group, self.compare_runs_diff_weapons_label = self._build_compare_diff_card(
            "Weapons",
            "--",
        )
        self.compare_runs_diff_tomes_group, self.compare_runs_diff_tomes_label = self._build_compare_diff_card(
            "Tomes",
            "--",
        )
        self.compare_runs_diff_chaos_group, self.compare_runs_diff_chaos_label = self._build_compare_diff_card(
            "Chaos",
            "--",
        )
        diff_scroll_layout.addWidget(self.compare_runs_diff_overview_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_stats_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_stage_summary_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_items_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_weapons_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_tomes_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_chaos_group)
        diff_scroll_layout.addStretch(1)
        diff_layout.addWidget(diff_scroll, 1)
        run_b_group, self.compare_run_b_status_label, self.compare_run_b_slider, self.compare_run_b_timeline_label, self.compare_run_b_summary_label = self._build_compare_run_panel(
            "Run B",
            "b",
        )
        body_layout.addWidget(run_a_group, 3)
        body_layout.addWidget(diff_group, 4)
        body_layout.addWidget(run_b_group, 3)
        compare_layout.addLayout(body_layout, 1)
        self.tabview.addTab(self.tab_compare_runs, "Compare Runs")

    def _build_compare_diff_card(self, title: str, initial_text: str):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        label = QLabel(initial_text)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        _apply_summary_label_padding(label)
        layout.addWidget(label)
        return group, label

    def _build_compare_run_panel(self, title: str, side: str):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        status_label = QLabel("Select a recording")
        status_label.setTextFormat(Qt.RichText)
        status_label.setWordWrap(True)
        slider = QSlider(Qt.Horizontal)
        slider.setEnabled(False)
        slider.valueChanged.connect(lambda value, run_side=side: self.on_compare_run_slider_changed(run_side, value))
        timeline_label = QLabel("Timeline: --")
        summary_label = QLabel("--")
        summary_label.setTextFormat(Qt.RichText)
        summary_label.setWordWrap(True)
        _apply_summary_label_padding(status_label, timeline_label, summary_label)
        layout.addWidget(status_label)
        layout.addWidget(slider)
        layout.addWidget(timeline_label)
        summary_group = QGroupBox("Snapshot")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.addWidget(summary_label)
        items_group = QGroupBox("Items")
        items_layout = QVBoxLayout(items_group)
        items_label = QLabel("--")
        items_label.setTextFormat(Qt.RichText)
        items_label.setWordWrap(True)
        items_layout.addWidget(items_label)
        items_actions = QHBoxLayout()
        items_toggle_btn = QPushButton("Show all")
        items_toggle_btn.setProperty("class", "SmallGhostButton")
        items_toggle_btn.clicked.connect(lambda _checked=False, run_side=side: self.toggle_compare_run_items_expanded(run_side))
        items_toggle_btn.setVisible(False)
        items_rarity_label = QLabel("")
        items_rarity_label.setTextFormat(Qt.RichText)
        items_rarity_label.setStyleSheet("font-size: 14px;")
        items_rarity_label.setVisible(False)
        items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            items_sort_combo.addItem(label, mode)
        rarity_desc_index = items_sort_combo.findData("rarity_desc")
        if rarity_desc_index >= 0:
            items_sort_combo.setCurrentIndex(rarity_desc_index)
        # Imported in the method body, not at module scope. `gui_layout` is
        # a top-level module that `ui/tabs/player_stats/live_stats.py`
        # already imports from, and `ui.tabs.player_stats.__init__` pulls
        # that module in -- so a module-scope import here closes a cycle:
        # gui_layout -> ui.tabs.player_stats -> live_stats -> gui_layout.
        # It stayed invisible to the suite and to the import-direction
        # checker (both AST, not real imports) because `gui_app` happens to
        # import the package first; `import gui_layout` on its own raised.
        # The cycle is a symptom of the compare panel being built here at
        # all, which is what step 21 moves.
        from ui.tabs.player_stats.items_section import ItemsSectionView

        # One ordinary ItemsSectionView per compare side. This is not
        # a step-21 conversion and not an adapter: Compare Runs stays a
        # mixin, it just holds a view object instead of nine
        # string-keyed attributes per side. Constructed here because
        # this is where its widgets are built; step 21 moves the
        # construction, not the class.
        items_view = ItemsSectionView(
            group=items_group,
            label=items_label,
            rarity_label=items_rarity_label,
            toggle_btn=items_toggle_btn,
            sort_combo=items_sort_combo,
            initial_sort_mode=ITEM_SORT_RARITY_DESC,
        )
        setattr(self, f"compare_run_{side}_items_view", items_view)
        items_sort_combo.currentIndexChanged.connect(
            lambda _index, view=items_view: view.on_sort_changed()
        )
        items_actions.addWidget(items_toggle_btn, 0, Qt.AlignLeft)
        items_actions.addWidget(items_rarity_label, 0, Qt.AlignLeft)
        items_actions.addStretch(1)
        items_actions.addWidget(QLabel("Sort:"))
        items_actions.addWidget(items_sort_combo)
        items_layout.addLayout(items_actions)
        layout.addWidget(summary_group)
        layout.addWidget(items_group)
        layout.addStretch(1)
        return group, status_label, slider, timeline_label, summary_label


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
