"""The Live Stats tab: rendering the current run as it is read from memory.

Builds its own widgets (``_build_live_stats_tab``, moved here by step 11b) and
reads them back, which is why this file's widget reads never counted as hidden
dependencies -- see the roadmap's step 11b table.

What is *not* here: acquiring the data. ``refresh_live_player_stats_now`` and the
memory clients live in ``app/player_stats_memory.py``; this tab only renders what it is
handed. That boundary is the whole point of step 14 -- it is what let this module
land under ``ui/`` with no ``infra`` import at all.

Still a mixin (step 9's MRO constraint); ``display_player_stats_snapshot`` and
friends are called class-qualified from the suite.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from core.game_state import RuntimeGameMode
from core.stats.types import PLAYER_STAT_GROUPS
from gui_layout import (
    LIVE_STATS_CARD_COLUMNS,
    LIVE_STATS_VALUE_WIDTH,
    _apply_player_stat_value_baseline,
    _apply_powerups_card_baselines,
    _apply_run_summary_baselines,
    _apply_stage_summary_column_baseline,
    _apply_summary_label_padding,
    _build_chests_stats_card,
    _retain_hidden_widget_size,
)
from ui.shared import _make_scroll_section, _set_text
from gui_styles import (
    ITEM_SORT_LABELS,
    PLAYER_STATS_ACTIVE_BUTTON_COLOR,
    PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR,
    PLAYER_STATS_INACTIVE_BUTTON_COLOR,
    PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR,
    _button_state_stylesheet,
)
from projections import formatting


class LiveStatsTabMixin:
    def _refresh_live_powerups_label(self) -> None:
        self._apply_live_powerups_card(None)
    def _reset_live_player_stats_ui(self, status_text: str, *, items_text: str = "--") -> None:
        _set_text(self.player_stats_status_label, status_text)
        for label in self.player_stats_rows.values():
            _set_text(label, "--")
        self.player_stats_items_expanded = False
        self._ensure_live_snapshot_store().reset_for_new_match()
        self._update_items_section("live", items_text=items_text)
        _set_text(self.player_stats_chests_per_minute_label, "Average chests/min: --")
        self._apply_live_powerups_card(None)
        _set_text(self.player_stats_in_game_time_label, "In-Game Time: --")
        _set_text(self.player_stats_mob_kills_label, "Mob Kills: --")
        _set_text(getattr(self, "player_stats_kps_averages_label", None), "KPS: --")
        _set_text(self.player_stats_level_label, "Level: --")
        self._set_chests_card_values(
            getattr(self, "player_stats_chests_card_values", None),
            None,
        )
        _set_text(getattr(self, "player_stats_new_items_label", None), "Live snapshot")
        _set_text(self.player_stats_banishes_label, "No banishes yet")
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, None)
        self.player_stats_weapon_signature = None
        self.display_weapon_cards(
            (),
            scope="live",
            status_text="Waiting for weapon data...",
        )
        self.player_stats_tome_signature = None
        self.display_tome_cards(
            (),
            scope="live",
            status_text="Waiting for tome data...",
        )
        self.player_stats_chaos_signature = None
        self.display_chaos_tome_card(
            None,
            scope="live",
            status_text="Waiting for Chaos Tome data...",
        )
        self.player_stats_damage_source_signature = None
        self.display_damage_source_rows(
            (),
            scope="live",
            status_text="Waiting for damage source data...",
        )
    def display_player_stats(
        self,
        stats,
        items=(),
        *,
        weapons=(),
        tomes=(),
        chaos_tome=None,
        banishes=(),
        damage_sources=(),
        weapons_available: bool = True,
        tomes_available: bool = True,
        damage_sources_available: bool = True,
        status_text: str | None = None,
        chests_per_minute: float | None = None,
        items_text: str | None = None,
        game_time_seconds: float | None = None,
        mob_kills: int | None = None,
        kps: int | None = None,
        minute_avg_kps: int | None = None,
        five_minute_avg_kps: int | None = None,
        player_level: int | None = None,
        new_items_text: str | None = None,
        stage_summary_rows: list[dict[str, str]] | None = None,
    ):
        if status_text:
            _set_text(self.player_stats_status_label, status_text)
        for label, stat in stats.items():
            value_label = self.player_stats_rows.get(label)
            if value_label is not None:
                _set_text(value_label, stat.display_value)
        self._update_items_section("live", items, items_text=items_text)
        if chests_per_minute is None:
            chests_per_minute = formatting.calculate_player_chests_per_minute(stats)
        _set_text(
            self.player_stats_chests_per_minute_label,
            formatting.format_chests_per_minute(chests_per_minute),
        )
        _set_text(
            getattr(self, "player_stats_powerups_duration_label", None),
            self.format_live_powerups(stats),
        )
        self._apply_live_powerups_card(stats)
        _set_text(
            self.player_stats_in_game_time_label,
            formatting.format_in_game_time(game_time_seconds),
        )
        _set_text(
            self.player_stats_mob_kills_label,
            formatting.format_mob_kills(mob_kills, kps),
        )
        _set_text(
            getattr(self, "player_stats_kps_averages_label", None),
            formatting.format_kps_averages(minute_avg_kps, five_minute_avg_kps),
        )
        _set_text(
            self.player_stats_level_label,
            formatting.format_player_level(player_level),
        )
        get_chest_stats = getattr(self.live_run_tracker, "get_chest_stats", None)
        if callable(get_chest_stats):
            self._update_live_chest_summary(get_chest_stats())
        if new_items_text is not None:
            _set_text(getattr(self, "player_stats_new_items_label", None), new_items_text)
        else:
            _set_text(getattr(self, "player_stats_new_items_label", None), "Live snapshot")
        _set_text(self.player_stats_banishes_label, formatting.format_banishes_rich_text(banishes))
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, stage_summary_rows)
        self.display_weapon_cards(
            weapons if weapons_available else (),
            scope="live",
            status_text=None if weapons_available else "Weapons unavailable",
        )
        self.display_tome_cards(
            tomes if tomes_available else (),
            scope="live",
            status_text=None if tomes_available else "Tomes unavailable",
        )
        self.display_chaos_tome_card(
            chaos_tome,
            scope="live",
            status_text=None if chaos_tome is not None else "No Chaos Tome data yet",
        )
        self.display_damage_source_rows(
            damage_sources if damage_sources_available else (),
            scope="live",
            status_text=None if damage_sources_available else "Damage sources unavailable",
        )
    def display_player_stats_snapshot(self, snapshot, *, items_text: str | None = None):
        index = self.player_stats_vod_snapshots.index(snapshot) + 1
        total = len(self.player_stats_vod_snapshots)
        self.display_player_stats(
            snapshot.stats,
            snapshot.items,
            weapons=getattr(snapshot, "weapons", ()),
            tomes=getattr(snapshot, "tomes", ()),
            chaos_tome=getattr(snapshot, "chaos_tome", None),
            banishes=getattr(snapshot, "banishes", ()),
            damage_sources=getattr(snapshot, "damage_sources", ()),
            status_text=(
                f"Recorded snapshot {index}/{total} at {snapshot.time_label}"
                f" | {formatting.format_in_game_time(snapshot.game_time_seconds)}"
            ),
            chests_per_minute=formatting.resolve_snapshot_chests_per_minute(snapshot),
            items_text=items_text,
            game_time_seconds=snapshot.game_time_seconds,
            mob_kills=getattr(snapshot, "mob_kills", None),
            kps=getattr(snapshot, "kps_at_capture", None),
            minute_avg_kps=getattr(snapshot, "minute_avg_kps_at_capture", None),
            five_minute_avg_kps=getattr(snapshot, "five_minute_avg_kps_at_capture", None),
            player_level=getattr(snapshot, "player_level", None),
            new_items_text=formatting.format_snapshot_item_gains_preview(
                self._previous_player_stats_snapshot(snapshot),
                snapshot,
                segment_snapshots=self._player_stats_snapshot_segment(snapshot),
            ),
            stage_summary_rows=formatting.build_stage_summary(
                self.player_stats_vod_snapshots[:index]
            ),
        )
    def _previous_player_stats_snapshot(self, snapshot):
        try:
            index = self.player_stats_vod_snapshots.index(snapshot)
        except ValueError:
            return None
        if index <= 0:
            return None
        return self.player_stats_vod_snapshots[index - 1]
    def _player_stats_snapshot_segment(self, snapshot) -> tuple[object, ...]:
        try:
            index = self.player_stats_vod_snapshots.index(snapshot)
        except ValueError:
            return (snapshot,)
        start_index = max(0, index - 1)
        return tuple(self.player_stats_vod_snapshots[start_index : index + 1])
    def on_player_stats_slider_changed(self, value):
        snapshot_count = len(self.player_stats_vod_snapshots)
        if snapshot_count == 0:
            return
        index = min(max(int(round(float(value))), 0), snapshot_count - 1)
        if self.player_stats_selected_snapshot_index == index:
            return
        self.player_stats_selected_snapshot_index = index
        self.display_player_stats_snapshot(self.player_stats_vod_snapshots[index])
        self.refresh_player_stats_timeline_ui(update_slider=False)

    def set_recording_status_text(self, text: str) -> None:
        """Set the Live Stats status line.

        This mixin builds `player_stats_status_label`, so it is the only place
        that should write it. `app/vod_capture.py` used to reach in and call
        `_set_text` on the widget directly -- a Qt write from the app layer,
        against the widget whose creator had already moved here in step 14b.
        It now goes through `PlayerStatsView` instead.
        """
        _set_text(self.player_stats_status_label, text)

    def set_mob_kills_text(self, text: str) -> None:
        """Set the Live Stats mob-kills line.

        Same shape, and the same reason, as `set_recording_status_text` above:
        this mixin builds `player_stats_mob_kills_label`, so it is the only
        place that should write it. `app/refresh_tasks.py` used to import
        `_set_text` from `gui_shared` and write the widget itself -- the last
        consumer of `gui_shared` outside UI code, outstanding since step 6.
        The app layer still decides what the line says; it no longer reaches
        through a Qt helper to put it there.
        """
        _set_text(self.player_stats_mob_kills_label, text)

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True):
        snapshot_count = len(self.player_stats_vod_snapshots)
        recording_armed = self._is_player_stats_recording_armed()
        waiting_mode = getattr(self, "player_stats_recording_waiting_mode", None)

        if self.player_stats_vod_recorder.is_recording or recording_armed:
            self.player_stats_record_btn.setText("Stop Recording")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_ACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR,
                )
            )
        else:
            self.player_stats_record_btn.setText(f"Start Recording ({config.PLAYER_STATS_RECORD_HOTKEY.upper()})")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_INACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR,
                )
            )

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            self.player_stats_slider.setEnabled(True)
            self.player_stats_slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                index = self.player_stats_selected_snapshot_index
                self.player_stats_slider.setValue(index if index is not None else snapshot_count - 1)
        else:
            self.player_stats_slider.setEnabled(False)
            self.player_stats_slider.setMaximum(1)
            self.player_stats_slider.setValue(0)

        if self.player_stats_vod_recorder.is_recording:
            prefix = f"Recording {self.player_stats_vod_recorder.elapsed_label()} | "
            if snapshot_count:
                selected = self.player_stats_selected_snapshot_index
                mode = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
                self.player_stats_timeline_label.setText(f"{prefix}{snapshot_count} snapshots | {mode}")
            elif waiting_mode == RuntimeGameMode.PAUSED_IN_GAME.value:
                self.player_stats_timeline_label.setText(f"{prefix}Paused in game")
            else:
                self.player_stats_timeline_label.setText(f"{prefix}No snapshots")
        elif recording_armed:
            self.player_stats_timeline_label.setText("Recording armed | waiting for run")
        else:
            self.player_stats_timeline_label.setText("Live stats")

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            first = self.player_stats_vod_snapshots[0].time_label
            last = self.player_stats_vod_snapshots[-1].time_label
            selected = self.player_stats_selected_snapshot_index
            current = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
            self.player_stats_slider_time_label.setText(f"Timeline: {first} - {last} | Selected: {current}")
        elif self.player_stats_vod_recorder.is_recording:
            self.player_stats_slider_time_label.setText(
                f"Timeline: recording {self.player_stats_vod_recorder.elapsed_label()} | waiting for first snapshot"
            )
        elif recording_armed:
            self.player_stats_slider_time_label.setText("Timeline: recording armed | waiting for run")
        else:
            self.player_stats_slider_time_label.setText("Timeline: live stats")
    def toggle_player_items_expanded(self) -> None:
        self.player_stats_items_expanded = not self.player_stats_items_expanded
        self._update_items_section(
            "live",
            self.player_stats_items_current,
            items_text=self.player_stats_items_text_current,
        )
    def _update_live_chest_summary(self, chest_stats) -> None:
        labels = getattr(self, "player_stats_chests_card_values", None)
        if labels:
            self._set_chests_card_values(
                labels,
                formatting.chests_card_values(
                    chest_stats.opened_by_stage,
                    chest_stats.total_by_stage,
                    chest_stats.total_opened,
                    chest_stats.total_chests,
                    chest_stats.paid if chest_stats.counters_available else None,
                    chest_stats.key_procs if chest_stats.counters_available else None,
                    chest_stats.free_chests if chest_stats.counters_available else None,
                    chest_stats.keys_count,
                    chest_stats.expected_key_procs if chest_stats.expected_complete else None,
                    chest_stats.total_opened_is_minimum,
                ),
            )
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
        self.player_stats_items_toggle_btn = QPushButton("Show more")
        self.player_stats_items_toggle_btn.clicked.connect(self.toggle_player_items_expanded)
        self.player_stats_items_toggle_btn.setProperty("class", "SmallGhostButton")
        _retain_hidden_widget_size(self.player_stats_items_toggle_btn)
        self.player_stats_items_toggle_btn.setEnabled(False)
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
        self.player_stats_kps_averages_label = QLabel("KPS: --")
        chest_rate_layout.addWidget(self.player_stats_kps_averages_label)
        self.player_stats_level_label = QLabel("Level: --")
        chest_rate_layout.addWidget(self.player_stats_level_label)
        _apply_summary_label_padding(
            self.player_stats_chests_per_minute_label,
            self.player_stats_in_game_time_label,
            self.player_stats_mob_kills_label,
            self.player_stats_kps_averages_label,
            self.player_stats_level_label,
        )
        _apply_run_summary_baselines(
            self.player_stats_chests_per_minute_label,
            self.player_stats_in_game_time_label,
            self.player_stats_mob_kills_label,
            self.player_stats_kps_averages_label,
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
        self.player_stats_powerups_group = QGroupBox("Powerups")
        live_powerups_layout = QVBoxLayout(self.player_stats_powerups_group)
        self.player_stats_live_powerup_labels = {}
        for effect_name in ("Rage", "Clock", "Shield", "Stonks"):
            label = QLabel(f"{effect_name}: --")
            _apply_summary_label_padding(label)
            live_powerups_layout.addWidget(label)
            self.player_stats_live_powerup_labels[effect_name] = label
        _apply_powerups_card_baselines(self.player_stats_live_powerup_labels)
        live_summary_grid.addWidget(self.player_stats_powerups_group, 0, 2)
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
        placeholder_group, self.player_stats_chests_card_values = _build_chests_stats_card()
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
        chaos_tab = QWidget()
        chaos_tab_layout = QVBoxLayout(chaos_tab)
        self.player_stats_chaos_status_label = QLabel("Waiting for Chaos Tome data...")
        self.player_stats_chaos_status_label.setWordWrap(True)
        chaos_tab_layout.addWidget(self.player_stats_chaos_status_label)
        player_chaos_scroll, _player_chaos_scroll_content, player_chaos_scroll_layout = _make_scroll_section()
        player_chaos_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.player_stats_chaos_layout = player_chaos_scroll_layout
        chaos_tab_layout.addWidget(player_chaos_scroll)
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
        self.player_stats_detail_tabs.addTab(chaos_tab, "Chaos")
        self.player_stats_detail_tabs.addTab(damage_sources_tab, "Damage Sources")
        player_content_layout.addWidget(self.player_stats_detail_tabs)
        player_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        tomes_tab_layout.setContentsMargins(0, 0, 0, 0)
        chaos_tab_layout.setContentsMargins(0, 0, 0, 0)
        damage_sources_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.tabview.addTab(self.tab_player_stats, "Live Stats")

    def format_live_powerups(self, stats) -> str:
        formatter = getattr(self.live_run_tracker, "format_powerups_summary", None)
        snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
        if callable(formatter) and callable(snapshot_reader):
            try:
                if getattr(snapshot_reader(), "available", False) is True:
                    return formatter(include_left_word=False)
            except Exception:
                pass
        return formatting.format_powerups_duration(stats)
