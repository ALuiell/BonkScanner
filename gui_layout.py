from __future__ import annotations

import os

from gui_shared import _apply_button_icon, _make_scroll_section, resource_path
from gui_styles import (
    ITEM_SORT_LABELS,
    PLAYER_STATS_VALUE_WIDTH,
    _session_stats_label_stylesheet,
)

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
    QLineEdit,
    QListWidget,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
from player_stats import PLAYER_STAT_GROUPS, PlayerStatFormat

SUMMARY_LABEL_PADDING_STYLESHEET = "padding-left: 4px;"
LIVE_STATS_CARD_COLUMNS = 3
LIVE_STATS_VALUE_WIDTH = 64
RECORDINGS_STATS_CARD_COLUMNS = 3
RECORDINGS_LIST_MIN_WIDTH = 150
RECORDINGS_LIST_MAX_WIDTH = 240
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
    "in_game_time": "In-Game Time: 99:59:59",
    "mob_kills": "Mob Kills: 999,999",
    "level": "Level: 999",
}
PLAYER_STAT_VALUE_BASELINES = {
    PlayerStatFormat.FLAT: "999,999",
    PlayerStatFormat.PERCENT: "999.9%",
    PlayerStatFormat.MULTIPLIER: "999.9x",
}


def _apply_summary_label_padding(*labels) -> None:
    for label in labels:
        label.setStyleSheet(SUMMARY_LABEL_PADDING_STYLESHEET)


def _reserve_label_baseline_width(label, baseline: str, padding: int = SUMMARY_LABEL_BASELINE_PADDING) -> None:
    metrics = QFontMetrics(label.font())
    width = max(metrics.horizontalAdvance(baseline), metrics.horizontalAdvance(label.text()))
    label.setMinimumWidth(max(label.minimumWidth(), width + padding))


def _retain_hidden_widget_size(widget) -> None:
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


def _apply_run_summary_baselines(
    chests_per_minute_label,
    in_game_time_label,
    mob_kills_label,
    level_label,
) -> None:
    _reserve_label_baseline_width(
        chests_per_minute_label,
        RUN_SUMMARY_LABEL_BASELINES["chests_per_minute"],
    )
    _reserve_label_baseline_width(
        in_game_time_label,
        RUN_SUMMARY_LABEL_BASELINES["in_game_time"],
    )
    _reserve_label_baseline_width(
        mob_kills_label,
        RUN_SUMMARY_LABEL_BASELINES["mob_kills"],
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
        self._build_live_stats_tab()
        self._build_recordings_tab()
        self._build_compare_runs_tab()
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


    def _build_session_stats_tab(self):
        self.tab_stats = QWidget()
        stats_layout = QVBoxLayout(self.tab_stats)
        stats_scroll, _stats_content, stats_content_layout = _make_scroll_section()
        stats_layout.addWidget(stats_scroll)
        self.stats_time_label = QLabel("Session Time: 00:00:00")
        self.stats_rerolls_label = QLabel("Session Rerolls: 0")
        self.stats_rpm_label = QLabel("Rerolls per Minute (RPM): 0.0")
        self.stats_best_label = QLabel("Best Map Found: None")
        self.stats_worst_label = QLabel("Worst Map Found: None")

        overview_group = QGroupBox("Session Overview")
        overview_layout = QVBoxLayout(overview_group)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(8)
        for widget in (
            self.stats_time_label,
            self.stats_rerolls_label,
            self.stats_rpm_label,
        ):
            widget.setWordWrap(True)
            widget.setStyleSheet(_session_stats_label_stylesheet(accent=True))
            overview_layout.addWidget(widget)
        stats_content_layout.addWidget(overview_group)

        maps_group = QGroupBox("Map Highlights")
        maps_layout = QVBoxLayout(maps_group)
        maps_layout.setContentsMargins(12, 12, 12, 12)
        maps_layout.setSpacing(10)
        for widget in (
            self.stats_best_label,
            self.stats_worst_label,
        ):
            widget.setWordWrap(True)
            widget.setStyleSheet(_session_stats_label_stylesheet())
            maps_layout.addWidget(widget)
        stats_content_layout.addWidget(maps_group)

        average_group = QGroupBox("Average Rerolls per Target")
        average_layout = QVBoxLayout(average_group)
        average_layout.setContentsMargins(12, 12, 12, 12)
        average_layout.setSpacing(8)
        self.stats_avg_frame = QWidget()
        self.stats_avg_layout = QVBoxLayout(self.stats_avg_frame)
        self.stats_avg_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_avg_layout.setSpacing(6)
        average_layout.addWidget(self.stats_avg_frame)
        stats_content_layout.addWidget(average_group)
        stats_content_layout.addStretch(1)
        self.tabview.addTab(self.tab_stats, "Session Stats")


    def _build_live_stats_tab(self):
        self.tab_player_stats = QWidget()
        player_layout = QVBoxLayout(self.tab_player_stats)
        player_scroll, _player_content, player_content_layout = _make_scroll_section()
        player_layout.addWidget(player_scroll)
        self.player_stats_status_label = QLabel("Waiting for game...")
        player_content_layout.addWidget(self.player_stats_status_label)
        player_controls = QHBoxLayout()
        self.player_stats_record_btn = QPushButton(f"Start Recording ({config.PLAYER_STATS_RECORD_HOTKEY.upper()})")
        self.player_stats_record_btn.clicked.connect(self.toggle_player_stats_recording)
        self.player_stats_timeline_label = QLabel("Live stats")
        player_controls.addWidget(self.player_stats_record_btn)
        player_controls.addStretch(1)
        player_controls.addWidget(self.player_stats_timeline_label)
        player_content_layout.addLayout(player_controls)
        self.player_stats_slider = QSlider(Qt.Horizontal)
        self.player_stats_slider.setEnabled(False)
        self.player_stats_slider.valueChanged.connect(self.on_player_stats_slider_changed)
        player_content_layout.addWidget(self.player_stats_slider)
        self.player_stats_slider_time_label = QLabel("Timeline: live stats")
        player_content_layout.addWidget(self.player_stats_slider_time_label)
        items_group = QGroupBox("Items")
        self.player_stats_items_group = items_group
        items_layout = QVBoxLayout(items_group)
        self.player_stats_items_label = QLabel("--")
        self.player_stats_items_label.setTextFormat(Qt.RichText)
        self.player_stats_items_label.setWordWrap(True)
        items_layout.addWidget(self.player_stats_items_label)
        self.player_stats_items_toggle_btn = QPushButton("Show all")
        self.player_stats_items_toggle_btn.clicked.connect(self.toggle_player_items_expanded)
        self.player_stats_items_toggle_btn.setProperty("class", "SmallGhostButton")
        _retain_hidden_widget_size(self.player_stats_items_toggle_btn)
        self.player_stats_items_toggle_btn.setVisible(False)
        items_actions = QHBoxLayout()
        self.player_stats_items_rarity_label = QLabel("")
        self.player_stats_items_rarity_label.setTextFormat(Qt.RichText)
        self.player_stats_items_rarity_label.setStyleSheet("font-size: 14px;")
        self.player_stats_items_rarity_label.setVisible(False)
        self.player_stats_items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            self.player_stats_items_sort_combo.addItem(label, mode)
        self.player_stats_items_sort_combo.currentIndexChanged.connect(
            lambda _index: self.on_items_sort_changed("live")
        )
        items_actions.addWidget(self.player_stats_items_toggle_btn, 0, Qt.AlignLeft)
        items_actions.addWidget(self.player_stats_items_rarity_label, 0, Qt.AlignLeft)
        items_actions.addStretch(1)
        items_actions.addWidget(QLabel("Sort:"))
        items_actions.addWidget(self.player_stats_items_sort_combo)
        items_layout.addLayout(items_actions)
        player_content_layout.addWidget(items_group)
        live_summary_grid = QGridLayout()
        live_summary_grid.setContentsMargins(0, 0, 0, 0)
        live_summary_grid.setHorizontalSpacing(8)
        live_summary_grid.setVerticalSpacing(8)
        chest_rate_group = QGroupBox("Run Summary")
        chest_rate_layout = QVBoxLayout(chest_rate_group)
        self.player_stats_chests_per_minute_label = QLabel("Average chests/min: --")
        chest_rate_layout.addWidget(self.player_stats_chests_per_minute_label)
        self.player_stats_in_game_time_label = QLabel("In-Game Time: --")
        chest_rate_layout.addWidget(self.player_stats_in_game_time_label)
        self.player_stats_mob_kills_label = QLabel("Mob Kills: --")
        chest_rate_layout.addWidget(self.player_stats_mob_kills_label)
        self.player_stats_level_label = QLabel("Level: --")
        chest_rate_layout.addWidget(self.player_stats_level_label)
        _apply_summary_label_padding(
            self.player_stats_chests_per_minute_label,
            self.player_stats_in_game_time_label,
            self.player_stats_mob_kills_label,
            self.player_stats_level_label,
        )
        _apply_run_summary_baselines(
            self.player_stats_chests_per_minute_label,
            self.player_stats_in_game_time_label,
            self.player_stats_mob_kills_label,
            self.player_stats_level_label,
        )
        live_summary_grid.addWidget(chest_rate_group, 0, 0)
        live_stage_summary_group = QGroupBox("Stage Summary")
        live_stage_summary_layout = QGridLayout(live_stage_summary_group)
        live_stage_summary_layout.setContentsMargins(10, 10, 10, 10)
        live_stage_summary_layout.setHorizontalSpacing(10)
        live_stage_summary_layout.setVerticalSpacing(4)
        for column, header in enumerate(("Stage", "Time", "Kills", "Items")):
            label = QLabel(header)
            label.setStyleSheet("font-weight: 700; color: #F3F4F6;")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            live_stage_summary_layout.addWidget(label, 0, column)
        self.player_stats_stage_summary_labels = []
        for index in range(4):
            stage_label = QLabel(str(index + 1))
            time_label = QLabel("--")
            kills_label = QLabel("--")
            items_label = QLabel("--")
            items_label.setTextFormat(Qt.RichText)
            stage_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for value_label in (time_label, kills_label, items_label):
                value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            _apply_summary_label_padding(stage_label, time_label, kills_label, items_label)
            live_stage_summary_layout.addWidget(stage_label, index + 1, 0)
            live_stage_summary_layout.addWidget(time_label, index + 1, 1)
            live_stage_summary_layout.addWidget(kills_label, index + 1, 2)
            live_stage_summary_layout.addWidget(items_label, index + 1, 3)
            self.player_stats_stage_summary_labels.append(
                {
                    "stage": stage_label,
                    "time": time_label,
                    "kills": kills_label,
                    "items": items_label,
                }
            )
        _apply_stage_summary_column_baseline(
            live_stage_summary_layout,
            self.player_stats_stage_summary_labels,
        )
        live_stage_summary_layout.setColumnStretch(0, 1)
        live_stage_summary_layout.setColumnStretch(1, 2)
        live_stage_summary_layout.setColumnStretch(2, 1)
        live_stage_summary_layout.setColumnStretch(3, 1)
        live_summary_grid.addWidget(live_stage_summary_group, 0, 1)
        live_new_items_group = QGroupBox("Segment Compare")
        live_new_items_layout = QVBoxLayout(live_new_items_group)
        self.player_stats_new_items_label = QLabel("Live snapshot")
        self.player_stats_new_items_label.setTextFormat(Qt.RichText)
        self.player_stats_new_items_label.setWordWrap(True)
        _apply_summary_label_padding(self.player_stats_new_items_label)
        live_new_items_layout.addWidget(self.player_stats_new_items_label)
        live_summary_grid.addWidget(live_new_items_group, 0, 2)
        live_banishes_group = QGroupBox("Banishes")
        live_banishes_layout = QVBoxLayout(live_banishes_group)
        self.player_stats_banishes_label = QLabel("No banishes yet")
        self.player_stats_banishes_label.setTextFormat(Qt.RichText)
        self.player_stats_banishes_label.setWordWrap(True)
        _apply_summary_label_padding(self.player_stats_banishes_label)
        live_banishes_layout.addWidget(self.player_stats_banishes_label)
        live_summary_grid.addWidget(live_banishes_group, 0, 3)
        for column in range(4):
            live_summary_grid.setColumnStretch(column, 1)
        player_content_layout.addLayout(live_summary_grid)
        self.player_stats_detail_tabs = QTabWidget()
        player_stats_tab = QWidget()
        player_stats_tab_layout = QVBoxLayout(player_stats_tab)
        player_stats_scroll, _player_stats_scroll_content, player_stats_scroll_layout = _make_scroll_section()
        player_stats_tab_layout.addWidget(player_stats_scroll)
        player_stats_grid = QGridLayout()
        player_stats_grid.setContentsMargins(0, 0, 0, 0)
        player_stats_grid.setHorizontalSpacing(8)
        player_stats_grid.setVerticalSpacing(8)
        for index, group in enumerate(PLAYER_STAT_GROUPS):
            stat_group = QFrame()
            stat_group.setObjectName("StatCard")
            group_layout = QFormLayout(stat_group)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.setHorizontalSpacing(6)
            group_layout.setVerticalSpacing(4)
            for spec in group:
                value_label = QLabel("--")
                value_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
                _apply_player_stat_value_baseline(value_label, spec.value_format)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.player_stats_rows[spec.label] = value_label
                group_layout.addRow(spec.label, value_label)
            player_stats_grid.addWidget(
                stat_group,
                index // LIVE_STATS_CARD_COLUMNS,
                index % LIVE_STATS_CARD_COLUMNS,
            )
        placeholder_index = len(PLAYER_STAT_GROUPS)
        placeholder_group = QFrame()
        placeholder_group.setObjectName("StatCard")
        placeholder_layout = QVBoxLayout(placeholder_group)
        placeholder_layout.setContentsMargins(8, 8, 8, 8)
        placeholder_label = QLabel("Have an idea for this slot? Let me know 💡")
        placeholder_label.setWordWrap(True)
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_layout.addStretch(1)
        placeholder_layout.addWidget(placeholder_label)
        placeholder_layout.addStretch(1)
        player_stats_grid.addWidget(
            placeholder_group,
            placeholder_index // LIVE_STATS_CARD_COLUMNS,
            placeholder_index % LIVE_STATS_CARD_COLUMNS,
        )
        for column in range(LIVE_STATS_CARD_COLUMNS):
            player_stats_grid.setColumnStretch(column, 1)
        player_stats_scroll_layout.addLayout(player_stats_grid)
        player_stats_scroll_layout.addStretch(1)
        weapons_tab = QWidget()
        weapons_tab_layout = QVBoxLayout(weapons_tab)
        self.player_stats_weapons_status_label = QLabel("Waiting for weapon data...")
        self.player_stats_weapons_status_label.setWordWrap(True)
        weapons_tab_layout.addWidget(self.player_stats_weapons_status_label)
        player_weapons_scroll, _player_weapons_scroll_content, player_weapons_scroll_layout = _make_scroll_section()
        player_weapons_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.player_stats_weapons_layout = player_weapons_scroll_layout
        weapons_tab_layout.addWidget(player_weapons_scroll)
        tomes_tab = QWidget()
        tomes_tab_layout = QVBoxLayout(tomes_tab)
        self.player_stats_tomes_status_label = QLabel("Waiting for tome data...")
        self.player_stats_tomes_status_label.setWordWrap(True)
        tomes_tab_layout.addWidget(self.player_stats_tomes_status_label)
        player_tomes_scroll, _player_tomes_scroll_content, player_tomes_scroll_layout = _make_scroll_section()
        player_tomes_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.player_stats_tomes_layout = player_tomes_scroll_layout
        tomes_tab_layout.addWidget(player_tomes_scroll)
        damage_sources_tab = QWidget()
        damage_sources_tab_layout = QVBoxLayout(damage_sources_tab)
        self.player_stats_damage_sources_status_label = QLabel("Waiting for damage source data...")
        self.player_stats_damage_sources_status_label.setWordWrap(True)
        damage_sources_tab_layout.addWidget(self.player_stats_damage_sources_status_label)
        player_damage_sources_scroll, _player_damage_sources_scroll_content, player_damage_sources_scroll_layout = _make_scroll_section()
        player_damage_sources_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.player_stats_damage_sources_layout = player_damage_sources_scroll_layout
        damage_sources_tab_layout.addWidget(player_damage_sources_scroll)
        self.player_stats_detail_tabs.addTab(player_stats_tab, "Stats")
        self.player_stats_detail_tabs.addTab(weapons_tab, "Weapons")
        self.player_stats_detail_tabs.addTab(tomes_tab, "Tomes")
        self.player_stats_detail_tabs.addTab(damage_sources_tab, "Damage Sources")
        player_content_layout.addWidget(self.player_stats_detail_tabs)
        player_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        tomes_tab_layout.setContentsMargins(0, 0, 0, 0)
        damage_sources_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.tabview.addTab(self.tab_player_stats, "Live Stats")


    def _build_recordings_tab(self):
        self.tab_vods = QWidget()
        vods_layout = QHBoxLayout(self.tab_vods)
        self.vods_list_frame = QListWidget()
        self.vods_list_frame.setMinimumWidth(RECORDINGS_LIST_MIN_WIDTH)
        self.vods_list_frame.setMaximumWidth(RECORDINGS_LIST_MAX_WIDTH)
        self.vods_list_frame.currentItemChanged.connect(self._on_vod_selection_changed)
        vods_layout.addWidget(self.vods_list_frame, 0)
        vods_detail = QWidget()
        vods_detail_layout = QVBoxLayout(vods_detail)
        self.vods_status_label = QLabel("Select a recording")
        vods_detail_layout.addWidget(self.vods_status_label)
        name_row = QHBoxLayout()
        self.vods_name_entry = QLineEdit()
        self.vods_rename_btn = QPushButton("Rename")
        self.vods_rename_btn.clicked.connect(self.rename_selected_vod)
        self.vods_cleanup_btn = QPushButton("Clean Short")
        self.vods_cleanup_btn.clicked.connect(self.cleanup_recordings_by_snapshot_count)
        self.vods_delete_btn = QPushButton("Delete")
        self.vods_delete_btn.setObjectName("DangerButton")
        self.vods_delete_btn.clicked.connect(self.delete_selected_vod)
        name_row.addWidget(self.vods_name_entry, 1)
        name_row.addWidget(self.vods_rename_btn)
        name_row.addWidget(self.vods_cleanup_btn)
        name_row.addWidget(self.vods_delete_btn)
        vods_detail_layout.addLayout(name_row)
        self.vods_slider = QSlider(Qt.Horizontal)
        self.vods_slider.setEnabled(False)
        self.vods_slider.valueChanged.connect(self.on_vods_slider_changed)
        vods_detail_layout.addWidget(self.vods_slider)
        self.vods_slider_time_label = QLabel("Timeline: --")
        vods_detail_layout.addWidget(self.vods_slider_time_label)
        vod_compare_actions = QHBoxLayout()
        self.vods_compare_set_btn = QPushButton("Set Compare Start")
        self.vods_compare_set_btn.setProperty("class", "SmallGhostButton")
        self.vods_compare_set_btn.clicked.connect(self.set_vod_compare_start)
        self.vods_compare_clear_btn = QPushButton("Clear Compare")
        self.vods_compare_clear_btn.setProperty("class", "SmallGhostButton")
        self.vods_compare_clear_btn.clicked.connect(self.clear_vod_compare_start)
        self.vods_compare_clear_btn.setEnabled(False)
        vod_compare_actions.addWidget(self.vods_compare_set_btn)
        vod_compare_actions.addWidget(self.vods_compare_clear_btn)
        vod_compare_actions.addStretch(1)
        vods_detail_layout.addLayout(vod_compare_actions)
        vod_items_group = QGroupBox("Items")
        self.vods_items_group = vod_items_group
        vod_items_layout = QVBoxLayout(vod_items_group)
        self.vods_items_label = QLabel("--")
        self.vods_items_label.setTextFormat(Qt.RichText)
        self.vods_items_label.setWordWrap(True)
        vod_items_layout.addWidget(self.vods_items_label)
        self.vods_items_toggle_btn = QPushButton("Show all")
        self.vods_items_toggle_btn.clicked.connect(self.toggle_vod_items_expanded)
        self.vods_items_toggle_btn.setProperty("class", "SmallGhostButton")
        _retain_hidden_widget_size(self.vods_items_toggle_btn)
        self.vods_items_toggle_btn.setVisible(False)
        vod_items_actions = QHBoxLayout()
        self.vods_items_rarity_label = QLabel("")
        self.vods_items_rarity_label.setTextFormat(Qt.RichText)
        self.vods_items_rarity_label.setStyleSheet("font-size: 14px;")
        self.vods_items_rarity_label.setVisible(False)
        self.vods_items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            self.vods_items_sort_combo.addItem(label, mode)
        self.vods_items_sort_combo.currentIndexChanged.connect(
            lambda _index: self.on_items_sort_changed("vod")
        )
        vod_items_actions.addWidget(self.vods_items_toggle_btn, 0, Qt.AlignLeft)
        vod_items_actions.addWidget(self.vods_items_rarity_label, 0, Qt.AlignLeft)
        vod_items_actions.addStretch(1)
        vod_items_actions.addWidget(QLabel("Sort:"))
        vod_items_actions.addWidget(self.vods_items_sort_combo)
        vod_items_layout.addLayout(vod_items_actions)
        vods_detail_layout.addWidget(vod_items_group)
        vod_summary_grid = QGridLayout()
        vod_summary_grid.setContentsMargins(0, 0, 0, 0)
        vod_summary_grid.setHorizontalSpacing(8)
        vod_summary_grid.setVerticalSpacing(8)
        vod_chest_rate_group = QGroupBox("Run Summary")
        vod_chest_rate_layout = QVBoxLayout(vod_chest_rate_group)
        self.vods_chests_per_minute_label = QLabel("Average chests/min: --")
        vod_chest_rate_layout.addWidget(self.vods_chests_per_minute_label)
        self.vods_in_game_time_label = QLabel("In-Game Time: --")
        vod_chest_rate_layout.addWidget(self.vods_in_game_time_label)
        self.vods_mob_kills_label = QLabel("Mob Kills: --")
        vod_chest_rate_layout.addWidget(self.vods_mob_kills_label)
        self.vods_level_label = QLabel("Level: --")
        vod_chest_rate_layout.addWidget(self.vods_level_label)
        _apply_summary_label_padding(
            self.vods_chests_per_minute_label,
            self.vods_in_game_time_label,
            self.vods_mob_kills_label,
            self.vods_level_label,
        )
        _apply_run_summary_baselines(
            self.vods_chests_per_minute_label,
            self.vods_in_game_time_label,
            self.vods_mob_kills_label,
            self.vods_level_label,
        )
        vod_summary_grid.addWidget(vod_chest_rate_group, 0, 0)
        vod_stage_summary_group = QGroupBox("Stage Summary")
        vod_stage_summary_layout = QGridLayout(vod_stage_summary_group)
        vod_stage_summary_layout.setContentsMargins(10, 10, 10, 10)
        vod_stage_summary_layout.setHorizontalSpacing(10)
        vod_stage_summary_layout.setVerticalSpacing(4)
        for column, header in enumerate(("Stage", "Time", "Kills", "Items")):
            label = QLabel(header)
            label.setStyleSheet("font-weight: 700; color: #F3F4F6;")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            vod_stage_summary_layout.addWidget(label, 0, column)
        self.vods_stage_summary_labels = []
        for index in range(4):
            stage_label = QLabel(str(index + 1))
            time_label = QLabel("--")
            kills_label = QLabel("--")
            items_label = QLabel("--")
            items_label.setTextFormat(Qt.RichText)
            stage_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for value_label in (time_label, kills_label, items_label):
                value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            _apply_summary_label_padding(stage_label, time_label, kills_label, items_label)
            vod_stage_summary_layout.addWidget(stage_label, index + 1, 0)
            vod_stage_summary_layout.addWidget(time_label, index + 1, 1)
            vod_stage_summary_layout.addWidget(kills_label, index + 1, 2)
            vod_stage_summary_layout.addWidget(items_label, index + 1, 3)
            self.vods_stage_summary_labels.append(
                {
                    "stage": stage_label,
                    "time": time_label,
                    "kills": kills_label,
                    "items": items_label,
                }
            )
        _apply_stage_summary_column_baseline(
            vod_stage_summary_layout,
            self.vods_stage_summary_labels,
        )
        vod_stage_summary_layout.setColumnStretch(0, 1)
        vod_stage_summary_layout.setColumnStretch(1, 2)
        vod_stage_summary_layout.setColumnStretch(2, 1)
        vod_stage_summary_layout.setColumnStretch(3, 1)
        vod_summary_grid.addWidget(vod_stage_summary_group, 0, 1)
        vod_new_items_group = QGroupBox("Segment Compare")
        vod_new_items_layout = QVBoxLayout(vod_new_items_group)
        self.vods_new_items_label = QLabel("No previous snapshot")
        self.vods_new_items_label.setTextFormat(Qt.RichText)
        self.vods_new_items_label.setWordWrap(True)
        _apply_summary_label_padding(self.vods_new_items_label)
        vod_new_items_layout.addWidget(self.vods_new_items_label)
        self.vods_compare_details_btn = QPushButton("Show details")
        self.vods_compare_details_btn.setProperty("class", "SmallGhostButton")
        self.vods_compare_details_btn.clicked.connect(self.toggle_vod_compare_details)
        self.vods_compare_details_btn.setVisible(False)
        vod_new_items_layout.addWidget(self.vods_compare_details_btn, 0, Qt.AlignLeft)
        vod_summary_grid.addWidget(vod_new_items_group, 0, 2)
        vod_banishes_group = QGroupBox("Banishes")
        vod_banishes_layout = QVBoxLayout(vod_banishes_group)
        self.vods_banishes_label = QLabel("No banishes yet")
        self.vods_banishes_label.setTextFormat(Qt.RichText)
        self.vods_banishes_label.setWordWrap(True)
        _apply_summary_label_padding(self.vods_banishes_label)
        vod_banishes_layout.addWidget(self.vods_banishes_label)
        vod_summary_grid.addWidget(vod_banishes_group, 0, 3)
        for column in range(4):
            vod_summary_grid.setColumnStretch(column, 1)
        vods_detail_layout.addLayout(vod_summary_grid)
        self.vods_compare_details_group = QGroupBox("Compare Details")
        vod_compare_details_layout = QVBoxLayout(self.vods_compare_details_group)
        self.vods_compare_details_summary_label = QLabel("--")
        self.vods_compare_details_summary_label.setWordWrap(True)
        self.vods_compare_details_items_label = QLabel("--")
        self.vods_compare_details_items_label.setTextFormat(Qt.RichText)
        self.vods_compare_details_items_label.setWordWrap(True)
        _apply_summary_label_padding(
            self.vods_compare_details_summary_label,
            self.vods_compare_details_items_label,
        )
        vod_compare_details_layout.addWidget(self.vods_compare_details_summary_label)
        vod_compare_scroll, _vod_compare_scroll_content, vod_compare_scroll_layout = _make_scroll_section()
        vod_compare_scroll.setMinimumHeight(120)
        vod_compare_scroll.setMaximumHeight(220)
        vod_compare_scroll_layout.setContentsMargins(0, 0, 0, 0)
        vod_compare_scroll_layout.addWidget(self.vods_compare_details_items_label)
        vod_compare_scroll_layout.addStretch(1)
        vod_compare_details_layout.addWidget(vod_compare_scroll)
        self.vods_compare_details_group.setVisible(False)
        vods_detail_layout.addWidget(self.vods_compare_details_group)
        self.vods_detail_tabs = QTabWidget()
        vod_stats_tab = QWidget()
        vod_stats_tab_layout = QVBoxLayout(vod_stats_tab)
        vods_scroll, _vods_scroll_content, vods_scroll_layout = _make_scroll_section()
        vod_stats_tab_layout.addWidget(vods_scroll)
        vods_stats_grid = QGridLayout()
        vods_stats_grid.setContentsMargins(0, 0, 0, 0)
        vods_stats_grid.setHorizontalSpacing(8)
        vods_stats_grid.setVerticalSpacing(8)
        for index, group in enumerate(PLAYER_STAT_GROUPS):
            stat_group = QFrame()
            stat_group.setObjectName("StatCard")
            group_layout = QFormLayout(stat_group)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.setHorizontalSpacing(6)
            group_layout.setVerticalSpacing(4)
            for spec in group:
                value_label = QLabel("--")
                value_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
                _apply_player_stat_value_baseline(value_label, spec.value_format)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.vods_rows[spec.label] = value_label
                group_layout.addRow(spec.label, value_label)
            vods_stats_grid.addWidget(
                stat_group,
                index // RECORDINGS_STATS_CARD_COLUMNS,
                index % RECORDINGS_STATS_CARD_COLUMNS,
            )
        placeholder_index = len(PLAYER_STAT_GROUPS)
        placeholder_group = QFrame()
        placeholder_group.setObjectName("StatCard")
        placeholder_layout = QVBoxLayout(placeholder_group)
        placeholder_layout.setContentsMargins(8, 8, 8, 8)
        placeholder_label = QLabel("Have an idea for this slot? Let me know 💡")
        placeholder_label.setWordWrap(True)
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_layout.addStretch(1)
        placeholder_layout.addWidget(placeholder_label)
        placeholder_layout.addStretch(1)
        vods_stats_grid.addWidget(
            placeholder_group,
            placeholder_index // RECORDINGS_STATS_CARD_COLUMNS,
            placeholder_index % RECORDINGS_STATS_CARD_COLUMNS,
        )
        for column in range(RECORDINGS_STATS_CARD_COLUMNS):
            vods_stats_grid.setColumnStretch(column, 1)
        vods_scroll_layout.addLayout(vods_stats_grid)
        vods_scroll_layout.addStretch(1)
        vod_weapons_tab = QWidget()
        vod_weapons_tab_layout = QVBoxLayout(vod_weapons_tab)
        self.vods_weapons_status_label = QLabel("Select a recording")
        self.vods_weapons_status_label.setWordWrap(True)
        vod_weapons_tab_layout.addWidget(self.vods_weapons_status_label)
        vod_weapons_scroll, _vod_weapons_scroll_content, vod_weapons_scroll_layout = _make_scroll_section()
        vod_weapons_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.vods_weapons_layout = vod_weapons_scroll_layout
        vod_weapons_tab_layout.addWidget(vod_weapons_scroll)
        vod_tomes_tab = QWidget()
        vod_tomes_tab_layout = QVBoxLayout(vod_tomes_tab)
        self.vods_tomes_status_label = QLabel("Select a recording")
        self.vods_tomes_status_label.setWordWrap(True)
        vod_tomes_tab_layout.addWidget(self.vods_tomes_status_label)
        vod_tomes_scroll, _vod_tomes_scroll_content, vod_tomes_scroll_layout = _make_scroll_section()
        vod_tomes_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.vods_tomes_layout = vod_tomes_scroll_layout
        vod_tomes_tab_layout.addWidget(vod_tomes_scroll)
        vod_damage_sources_tab = QWidget()
        vod_damage_sources_tab_layout = QVBoxLayout(vod_damage_sources_tab)
        self.vods_damage_sources_status_label = QLabel("Select a recording")
        self.vods_damage_sources_status_label.setWordWrap(True)
        vod_damage_sources_tab_layout.addWidget(self.vods_damage_sources_status_label)
        vod_damage_sources_scroll, _vod_damage_sources_scroll_content, vod_damage_sources_scroll_layout = _make_scroll_section()
        vod_damage_sources_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.vods_damage_sources_layout = vod_damage_sources_scroll_layout
        vod_damage_sources_tab_layout.addWidget(vod_damage_sources_scroll)
        self.vods_detail_tabs.addTab(vod_stats_tab, "Stats")
        self.vods_detail_tabs.addTab(vod_weapons_tab, "Weapons")
        self.vods_detail_tabs.addTab(vod_tomes_tab, "Tomes")
        self.vods_detail_tabs.addTab(vod_damage_sources_tab, "Damage Sources")
        vod_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_tomes_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_damage_sources_tab_layout.setContentsMargins(0, 0, 0, 0)
        vods_detail_layout.addWidget(self.vods_detail_tabs, 1)
        vods_layout.addWidget(vods_detail, 1)
        self.tabview.addTab(self.tab_vods, "Recordings")

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
        section_layout.addWidget(QLabel("Show in Difference:"))
        section_layout.addWidget(self.compare_runs_stage_summary_checkbox)
        section_layout.addWidget(self.compare_runs_items_checkbox)
        section_layout.addWidget(self.compare_runs_weapons_checkbox)
        section_layout.addWidget(self.compare_runs_tomes_checkbox)
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
        diff_scroll_layout.addWidget(self.compare_runs_diff_overview_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_stats_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_stage_summary_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_items_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_weapons_group)
        diff_scroll_layout.addWidget(self.compare_runs_diff_tomes_group)
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
        setattr(self, f"compare_run_{side}_items_group", items_group)
        items_layout = QVBoxLayout(items_group)
        items_label = QLabel("--")
        items_label.setTextFormat(Qt.RichText)
        items_label.setWordWrap(True)
        setattr(self, f"compare_run_{side}_items_label", items_label)
        items_layout.addWidget(items_label)
        items_actions = QHBoxLayout()
        items_toggle_btn = QPushButton("Show all")
        items_toggle_btn.setProperty("class", "SmallGhostButton")
        items_toggle_btn.clicked.connect(lambda _checked=False, run_side=side: self.toggle_compare_run_items_expanded(run_side))
        items_toggle_btn.setVisible(False)
        setattr(self, f"compare_run_{side}_items_toggle_btn", items_toggle_btn)
        items_rarity_label = QLabel("")
        items_rarity_label.setTextFormat(Qt.RichText)
        items_rarity_label.setStyleSheet("font-size: 14px;")
        items_rarity_label.setVisible(False)
        setattr(self, f"compare_run_{side}_items_rarity_label", items_rarity_label)
        items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            items_sort_combo.addItem(label, mode)
        rarity_desc_index = items_sort_combo.findData("rarity_desc")
        if rarity_desc_index >= 0:
            items_sort_combo.setCurrentIndex(rarity_desc_index)
        items_sort_combo.currentIndexChanged.connect(
            lambda _index, run_side=side: self.on_items_sort_changed(f"compare_{run_side}")
        )
        setattr(self, f"compare_run_{side}_items_sort_combo", items_sort_combo)
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
        self.help_btn = QPushButton("?")
        self.help_btn.setObjectName("HelpButton")
        self.help_btn.setToolTip("Help")
        self.help_btn.clicked.connect(self.open_help_dialog)
        self.status_label = QLabel("Status: IDLE")
        self.status_label.setObjectName("StatusLabel")
        self.toggle_btn = QPushButton(f"Start")
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
        if self._is_compare_runs_tab_active():
            self.refresh_compare_runs_list()
            if hasattr(self, "ensure_compare_runs_chooser_for_empty_selection"):
                self.ensure_compare_runs_chooser_for_empty_selection()
        self.after_idle(self._refresh_right_tab_after_switch)

    def _refresh_right_tab_after_switch(self):
        if self._is_recordings_tab_active():
            self.refresh_vods_list()
        if self._is_compare_runs_tab_active():
            self.refresh_compare_runs_list()
            if hasattr(self, "ensure_compare_runs_chooser_for_empty_selection"):
                self.ensure_compare_runs_chooser_for_empty_selection()
        if self._is_live_stats_tab_active():
            self.refresh_live_player_stats_now()

    def _show_right_tab_transition_cover(self):
        return None

    def _cancel_right_tab_transition(self):
        return None

    def _is_live_stats_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Live Stats"

    def _is_recordings_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Recordings"

    def _is_compare_runs_tab_active(self) -> bool:
        return self.tabview.tabText(self.tabview.currentIndex()) == "Compare Runs"

    def _refresh_vods_list_if_visible(self):
        if self._is_recordings_tab_active():
            self.refresh_vods_list()
        if self._is_compare_runs_tab_active():
            self.refresh_compare_runs_list()
