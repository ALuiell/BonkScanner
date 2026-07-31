from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from core.luck_rarity import LUCK_RARITY_MODEL_ATTRIBUTION
from ui.canvas_preview import CanvasPreview, PreviewWidget
from ui.module_tile import ModuleTile
from ui.run_toggle import IN_GAME_OVERLAY_CAPTIONS
from ui.settings_card import SettingsCard
from ui.shared import _make_scroll_section
from ui.styles import _set_widget_style_role
from ui.tab_hero import STATE_OFF, STATE_OK, STATE_WARN, TabHero

#: The seven in-game widgets, in grid order, with the label each tile carries.
#: The mock merged `stats` and `event_timer` into one tile; they are two
#: independent config keys and `_on_igo_settings_changed` writes both, so
#: merging them would have taken away "timer without stats".
IN_GAME_WIDGET_TILES = (
    ("scanner", "Scanner status", "igo_scanner_cb"),
    ("recording", "Recording status", "igo_recording_cb"),
    ("kps", "KPS", "igo_kps_cb"),
    ("powerups", "Active powerups", "igo_powerups_cb"),
    ("luck_rarity", "Luck rarity %", "igo_luck_rarity_cb"),
    ("stats", "Stats", "igo_stats_cb"),
    ("event_timer", "Event timer", "igo_event_timer_cb"),
)


class InGameWidgetSettingsDialog(QDialog):
    def __init__(self, parent_mixin: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_mixin = parent_mixin
        self.setWindowTitle("In-Game Widgets Configuration")
        self.resize(700, 760)
        self.setMinimumSize(640, 680)

        main_layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)
        
        # Basic tab
        self.basic_tab = QWidget()
        basic_layout = QVBoxLayout(self.basic_tab)
        basic_scroll, _basic_content, basic_scroll_layout = _make_scroll_section()
        basic_scroll_layout.setSpacing(16)
        basic_layout.addWidget(basic_scroll)
        self.tabs.addTab(self.basic_tab, "Basic Settings")
        
        # Advanced tab
        self.advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_tab)
        advanced_scroll, _advanced_content, advanced_scroll_layout = _make_scroll_section()
        advanced_scroll_layout.setSpacing(16)
        advanced_layout.addWidget(advanced_scroll)
        self.tabs.addTab(self.advanced_tab, "Advanced Settings")
        
        self._init_basic_layout(basic_scroll_layout)
        self._init_advanced_layout(advanced_scroll_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    def _init_basic_layout(self, layout) -> None:
        _add_scale_group(
            layout,
            title="Scanner Status Settings",
            attr_name="scanner_scale_spin",
            widget_id="scanner",
            parent=self,
        )
        _add_scale_group(
            layout,
            title="Recording Status Settings",
            attr_name="recording_scale_spin",
            widget_id="recording",
            parent=self,
        )

        kps_group = QGroupBox("KPS Settings")
        kps_layout = QVBoxLayout(kps_group)
        kps_layout.setContentsMargins(16, 12, 16, 12)
        _add_scale_row(kps_layout, self, "kps_scale_spin", "kps")

        metrics_group = QGroupBox("Metrics Displayed")
        metrics_layout = QHBoxLayout(metrics_group)
        metrics_layout.setSpacing(10)
        selected_metrics = set(config.IN_GAME_OVERLAY["widgets"]["kps"].get("metrics", ["instant"]))

        self.kps_instant_cb = _build_checkbox("KPS", "instant" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_instant_cb)
        self.kps_60s_cb = _build_checkbox("60s", "60s" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_60s_cb)
        self.kps_5m_cb = _build_checkbox("5m", "5m" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_5m_cb)
        self.kps_run_cb = _build_checkbox("Run", "run" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_run_cb)

        kps_layout.addWidget(metrics_group)
        layout.addWidget(kps_group)

        _add_scale_group(
            layout,
            title="Active Powerups Settings",
            attr_name="powerups_scale_spin",
            widget_id="powerups",
            parent=self,
        )
        luck_rarity_group = QGroupBox("Luck Rarity Settings")
        luck_rarity_layout = QVBoxLayout(luck_rarity_group)
        luck_rarity_layout.setContentsMargins(16, 12, 16, 12)
        _add_scale_row(luck_rarity_layout, self, "luck_rarity_scale_spin", "luck_rarity")
        self.luck_rarity_show_bar_cb = _build_checkbox(
            "Show rarity bar",
            bool(config.IN_GAME_OVERLAY["widgets"]["luck_rarity"].get("show_bar", True)),
            self._save_settings,
        )
        luck_rarity_layout.addWidget(self.luck_rarity_show_bar_cb)

        # Independent of the bar, not nested under it: all four combinations of
        # the two are valid, and the block anchors to the percentage row, which
        # is always drawn.
        self.luck_rarity_show_expected_cb = _build_checkbox(
            "Show expected frame",
            bool(config.IN_GAME_OVERLAY["widgets"]["luck_rarity"].get("show_expected", False)),
            self._save_settings,
        )
        self.luck_rarity_show_expected_cb.setToolTip(LUCK_RARITY_MODEL_ATTRIBUTION)
        luck_rarity_layout.addWidget(self.luck_rarity_show_expected_cb)

        expected_layout_row = QHBoxLayout()
        expected_layout_row.addWidget(QLabel("Expected layout:"))
        self.luck_rarity_expected_layout_combo = QComboBox()
        for label, value in (("Column (2x2)", "column"), ("Row (single line)", "row")):
            self.luck_rarity_expected_layout_combo.addItem(label, value)
        current_layout = config.IN_GAME_OVERLAY["widgets"]["luck_rarity"].get(
            "expected_layout", "column"
        )
        self.luck_rarity_expected_layout_combo.setCurrentIndex(
            max(0, self.luck_rarity_expected_layout_combo.findData(current_layout))
        )
        self.luck_rarity_expected_layout_combo.currentIndexChanged.connect(self._save_settings)
        expected_layout_row.addWidget(self.luck_rarity_expected_layout_combo)
        expected_layout_row.addStretch(1)
        luck_rarity_layout.addLayout(expected_layout_row)
        layout.addWidget(luck_rarity_group)

        event_timer_group = QGroupBox("Event Timer Settings")
        event_timer_layout = QVBoxLayout(event_timer_group)
        event_timer_layout.setContentsMargins(16, 12, 16, 12)
        _add_scale_row(event_timer_layout, self, "event_timer_scale_spin", "event_timer")
        
        warn_layout = QHBoxLayout()
        warn_layout.addWidget(QLabel("Warning threshold (seconds):"))
        self.event_timer_warning_spin = QSpinBox()
        self.event_timer_warning_spin.setRange(1, 300)
        self.event_timer_warning_spin.setValue(config.IN_GAME_OVERLAY["widgets"]["event_timer"].get("warning_seconds", 15))
        self.event_timer_warning_spin.valueChanged.connect(self._save_settings)
        warn_layout.addWidget(self.event_timer_warning_spin)
        warn_layout.addStretch(1)
        event_timer_layout.addLayout(warn_layout)
        layout.addWidget(event_timer_group)
        layout.addStretch(1)

    def _init_advanced_layout(self, layout) -> None:
        stats_group = QGroupBox("Stats Widget Settings")
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setContentsMargins(16, 12, 16, 12)
        
        _add_scale_row(stats_layout, self, "stats_scale_spin", "stats")
        stats_layout.addSpacing(8)
        
        stats_layout.addWidget(QLabel("Select stats to display in the In-Game Stats widget:"))
        
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(10)
        grid_layout.setContentsMargins(0, 8, 0, 8)
        
        selected_stats = set(config.IN_GAME_OVERLAY["widgets"]["stats"].get("selected_stats", ["Damage", "Difficulty", "XP Gain", "Luck"]))
        
        self.stats_checkboxes = {}
        for index, label in enumerate(config.ALL_STAT_LABELS):
            cb = QCheckBox(label)
            cb.setChecked(label in selected_stats)
            cb.stateChanged.connect(self._save_settings)
            self.stats_checkboxes[label] = cb
            grid_layout.addWidget(cb, index // 4, index % 4)
            
        stats_layout.addWidget(grid_widget)
        stats_layout.addSpacing(12)

        reset_btn_layout = QHBoxLayout()
        self.stats_reset_btn = QPushButton("Reset to Default Stats")
        self.stats_reset_btn.clicked.connect(self._reset_stats_to_default)
        reset_btn_layout.addWidget(self.stats_reset_btn)
        reset_btn_layout.addStretch(1)
        stats_layout.addLayout(reset_btn_layout)

        layout.addWidget(stats_group)
        layout.addStretch(1)

    def _reset_stats_to_default(self) -> None:
        default_stats = set(config.DEFAULT_IN_GAME_OVERLAY["widgets"]["stats"]["selected_stats"])
        for label, cb in self.stats_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(label in default_stats)
            cb.blockSignals(False)
        self._save_settings()

    def _save_settings(self, *_args) -> None:
        widgets = config.IN_GAME_OVERLAY["widgets"]
        widgets["scanner"]["scale"] = self.scanner_scale_spin.value()
        widgets["recording"]["scale"] = self.recording_scale_spin.value()
        widgets["kps"]["scale"] = self.kps_scale_spin.value()
        widgets["powerups"]["scale"] = self.powerups_scale_spin.value()
        widgets["luck_rarity"]["scale"] = self.luck_rarity_scale_spin.value()
        widgets["luck_rarity"]["show_bar"] = self.luck_rarity_show_bar_cb.isChecked()
        widgets["luck_rarity"]["show_expected"] = self.luck_rarity_show_expected_cb.isChecked()
        widgets["luck_rarity"]["expected_layout"] = (
            self.luck_rarity_expected_layout_combo.currentData() or "column"
        )
        widgets["event_timer"]["scale"] = self.event_timer_scale_spin.value()
        widgets["event_timer"]["warning_seconds"] = self.event_timer_warning_spin.value()
        widgets["stats"]["scale"] = self.stats_scale_spin.value()
        
        selected_stats = []
        for label in config.ALL_STAT_LABELS:
            if label in self.stats_checkboxes and self.stats_checkboxes[label].isChecked():
                selected_stats.append(label)
        widgets["stats"]["selected_stats"] = selected_stats or ["Damage", "Difficulty", "XP Gain", "Luck"]

        metrics = []
        if self.kps_instant_cb.isChecked():
            metrics.append("instant")
        if self.kps_60s_cb.isChecked():
            metrics.append("60s")
        if self.kps_5m_cb.isChecked():
            metrics.append("5m")
        if self.kps_run_cb.isChecked():
            metrics.append("run")
        widgets["kps"]["metrics"] = metrics or ["instant"]

        self.parent_mixin.apply_in_game_overlay_settings()
        config.save_config(config.user_config)


def build_in_game_overlay_tab(parent_mixin: Any) -> None:
    parent_mixin.tab_in_game_overlay = QWidget()
    tab_layout = QVBoxLayout(parent_mixin.tab_in_game_overlay)
    tab_layout.setContentsMargins(0, 0, 0, 0)

    scroll, _scroll_content, layout = _make_scroll_section()
    layout.setSpacing(12)
    layout.setContentsMargins(8, 8, 8, 8)
    tab_layout.addWidget(scroll)

    layout.addWidget(_build_igo_hero(parent_mixin))

    workspace = QHBoxLayout()
    workspace.setSpacing(12)
    layout.addLayout(workspace)

    main_column = QVBoxLayout()
    main_column.setSpacing(12)
    workspace.addLayout(main_column, 1)

    side_column = QVBoxLayout()
    side_column.setSpacing(12)
    workspace.addLayout(side_column, 0)

    _build_igo_layout_card(parent_mixin, main_column)
    _build_igo_widgets_card(parent_mixin, main_column)
    main_column.addStretch(1)

    _build_igo_preview_card(parent_mixin, side_column)
    _build_igo_tip_card(parent_mixin, side_column)
    side_column.addStretch(1)

    layout.addStretch(1)
    update_in_game_overlay_status_ui(parent_mixin)
    refresh_in_game_overlay_hotkey_ui(parent_mixin)
    refresh_in_game_overlay_preview(parent_mixin)


def _build_igo_hero(parent_mixin: Any) -> TabHero:
    parent_mixin.igo_hero = TabHero(
        title="In-Game Overlay",
        subtitle="Pin live scanner information directly over the game window.",
        icon_path="media/in_game_icon.svg",
        auto_text="Auto-start overlay",
        run_captions=IN_GAME_OVERLAY_CAPTIONS,
    )
    parent_mixin.igo_auto_start_cb = parent_mixin.igo_hero.auto_switch
    parent_mixin.igo_auto_start_cb.setChecked(config.IN_GAME_OVERLAY.get("auto_start", False))
    parent_mixin.igo_auto_start_cb.setToolTip(
        "Start the transparent overlay automatically when the application starts."
    )
    parent_mixin.igo_auto_start_cb.stateChanged.connect(parent_mixin._on_igo_settings_changed)

    parent_mixin.igo_toggle_btn = parent_mixin.igo_hero.run_toggle
    parent_mixin.igo_toggle_btn.toggle_requested.connect(parent_mixin._toggle_in_game_overlay)
    # `igo_status_label` is gone -- the badge is the status now. Kept as None so
    # a straggling reader gets a clean `is None` rather than an AttributeError.
    parent_mixin.igo_status_label = None
    return parent_mixin.igo_hero


def _build_igo_layout_card(parent_mixin: Any, column) -> None:
    """Card 1. No segmented control: layout mode is entered by hotkey only.

    The tab used to carry an `Edit Layout` button that renamed itself to
    `Save Layout` and painted itself green inline. It duplicated an affordance
    already on screen at the only moment it matters -- the overlay itself shows
    a `Save Layout & Exit` button while in edit mode, and `Esc` and the hotkey
    both leave it. Pressing it from here was the awkward path anyway: it drops
    the overlay over a game you are not looking at, and with no game running the
    widgets spread across the whole screen.
    """
    card = SettingsCard(
        number=1,
        title="Layout & activation",
        subtitle="Drag widgets over the game in layout mode; it saves on exit.",
    )

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(8)

    hotkey_row = QWidget()
    hotkey_layout = QHBoxLayout(hotkey_row)
    hotkey_layout.setContentsMargins(0, 0, 0, 0)
    hotkey_layout.setSpacing(8)
    parent_mixin.igo_hotkey_entry = QLineEdit(hotkey_row)
    parent_mixin.igo_hotkey_entry.setMaximumWidth(90)
    parent_mixin.igo_hotkey_entry.editingFinished.connect(
        lambda: _save_in_game_overlay_hotkey(parent_mixin)
    )
    hotkey_layout.addWidget(parent_mixin.igo_hotkey_entry)
    hotkey_layout.addWidget(QLabel("press again to save and exit", hotkey_row))
    hotkey_layout.addStretch(1)
    form.addRow("Edit hotkey:", hotkey_row)

    window_row = QWidget()
    window_layout = QHBoxLayout(window_row)
    window_layout.setContentsMargins(0, 0, 0, 0)
    window_layout.setSpacing(8)
    window_name = QLineEdit(str(getattr(config, "PROCESS_NAME", "") or ""), window_row)
    window_name.setReadOnly(True)
    window_layout.addWidget(window_name, 1)
    parent_mixin.igo_target_window_label = QLabel("", window_row)
    parent_mixin.igo_target_window_label.setObjectName("fieldSuffix")
    window_layout.addWidget(parent_mixin.igo_target_window_label)
    form.addRow("Target window:", window_row)

    card.body.addLayout(form)
    column.addWidget(card)


def _build_igo_widgets_card(parent_mixin: Any, column) -> None:
    parent_mixin.igo_widget_settings_btn = QPushButton("Widget Settings")
    parent_mixin.igo_widget_settings_btn.clicked.connect(
        parent_mixin._open_igo_widget_settings_dialog
    )
    card = SettingsCard(
        number=2,
        title="In-game widgets",
        subtitle="Scale and per-widget details live in settings.",
        action=parent_mixin.igo_widget_settings_btn,
    )

    grid = QGridLayout()
    grid.setSpacing(8)
    grid.setContentsMargins(0, 0, 0, 0)
    for index, (widget_id, label, attribute) in enumerate(IN_GAME_WIDGET_TILES):
        tile = ModuleTile(label)
        tile.setChecked(bool(config.IN_GAME_OVERLAY["widgets"][widget_id]["enabled"]))
        tile.stateChanged.connect(parent_mixin._on_igo_settings_changed)
        setattr(parent_mixin, attribute, tile)
        grid.addWidget(tile, index // 3, index % 3)
    card.body.addLayout(grid)

    column.addWidget(card)


def _build_igo_preview_card(parent_mixin: Any, column) -> None:
    card = SettingsCard(
        number=None,
        title="Game-window preview",
        subtitle="Read-only - drag in layout mode.",
    )
    card.setMaximumWidth(360)

    parent_mixin.igo_preview = CanvasPreview()
    card.body.addWidget(parent_mixin.igo_preview)
    column.addWidget(card)

    # Its own slow poll, for the same reason the OBS preview has one: whether
    # the game window exists is read live, and nothing else ticks while the
    # overlay is off.
    parent_mixin.igo_preview_timer = QTimer(parent_mixin.tab_in_game_overlay)
    parent_mixin.igo_preview_timer.setInterval(1500)
    parent_mixin.igo_preview_timer.timeout.connect(
        lambda: refresh_in_game_overlay_preview(parent_mixin)
    )
    parent_mixin.igo_preview_timer.start()


def _build_igo_tip_card(parent_mixin: Any, column) -> None:
    tip = QFrame()
    tip.setObjectName("tipCard")
    tip.setProperty("tipCard", "true")
    tip.setMaximumWidth(360)
    tip_layout = QVBoxLayout(tip)
    tip_layout.setContentsMargins(12, 11, 12, 11)
    tip_layout.setSpacing(4)

    title = QLabel("LAYOUT SHORTCUT", tip)
    title.setObjectName("tipCardTitle")
    tip_layout.addWidget(title)

    # Load-bearing now that layout mode is hotkey-only: this is the *only* place
    # on screen that says how to enter it. It interpolates the key, so it is
    # re-rendered whenever the key changes -- a stale instruction here is the
    # whole feature gone. See `refresh_in_game_overlay_hotkey_ui`.
    parent_mixin.igo_tip_label = QLabel("", tip)
    parent_mixin.igo_tip_label.setObjectName("tipCardText")
    parent_mixin.igo_tip_label.setWordWrap(True)
    parent_mixin.igo_tip_label.setTextFormat(Qt.RichText)
    tip_layout.addWidget(parent_mixin.igo_tip_label)

    column.addWidget(tip)


def in_game_overlay_hotkey_text() -> str:
    return str(getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9") or "f9").upper()


def refresh_in_game_overlay_hotkey_ui(parent_mixin: Any) -> None:
    """Re-read the hotkey into the field and the tip.

    Called after this tab saves it and after the Settings dialog does. The two
    are deliberately both editors of one value, so neither can be the only one
    that knows it changed.
    """
    hotkey = in_game_overlay_hotkey_text()
    entry = getattr(parent_mixin, "igo_hotkey_entry", None)
    if entry is not None and entry.text().strip().upper() != hotkey:
        entry.blockSignals(True)
        entry.setText(hotkey)
        entry.blockSignals(False)
    tip = getattr(parent_mixin, "igo_tip_label", None)
    if tip is not None:
        tip.setText(
            f"Press <b>{hotkey}</b> to enter layout mode. Drag the widgets over "
            f"the game, then press <b>{hotkey}</b> or <b>Esc</b> to save and exit."
        )


def _save_in_game_overlay_hotkey(parent_mixin: Any) -> None:
    entry = getattr(parent_mixin, "igo_hotkey_entry", None)
    if entry is None:
        return
    hotkey = entry.text().strip().lower()
    current = str(getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9") or "f9").lower()
    if not hotkey or hotkey == current:
        # An empty field would unbind the only way into layout mode. Put the
        # current value back rather than saving nothing.
        refresh_in_game_overlay_hotkey_ui(parent_mixin)
        return
    config.IN_GAME_OVERLAY_EDIT_HOTKEY = hotkey
    config.user_config["IN_GAME_OVERLAY_EDIT_HOTKEY"] = hotkey
    config.save_config(config.user_config)
    # Rebinding is not optional: `setup_hotkeys` tears the previous manager down
    # and builds a new one, and without it the saved key does nothing until the
    # app restarts -- with the tip already telling the user to press it.
    parent_mixin.rebind_hotkeys()
    refresh_in_game_overlay_hotkey_ui(parent_mixin)


def refresh_in_game_overlay_preview(parent_mixin: Any) -> None:
    preview = getattr(parent_mixin, "igo_preview", None)
    if preview is None:
        return
    if not parent_mixin.is_in_game_overlay_tab_active():
        return

    geometry = parent_mixin._in_game_overlay_target_geometry()
    detected = geometry is not None
    label = getattr(parent_mixin, "igo_target_window_label", None)
    if label is not None:
        label.setText("Detected" if detected else "Not running")
        label.setProperty("state", STATE_OK if detected else STATE_OFF)
        style = label.style()
        if style is not None:
            style.unpolish(label)
            style.polish(label)

    if geometry is not None:
        preview.set_canvas(geometry.width(), geometry.height())
        preview.set_placeholder("")
    else:
        # The overlay's own fallback, said out loud: without the game there is
        # no client rect to scale against, so what is shown is against the
        # screen and would otherwise look mysteriously shifted.
        preview.set_canvas(1920, 1080)
        preview.set_placeholder(
            "Game window not found.\nPositions are shown against a 1920x1080 screen."
        )

    widgets = config.IN_GAME_OVERLAY.get("widgets", {})
    preview.set_widgets(
        PreviewWidget(
            label=label_text,
            x=int(widgets.get(widget_id, {}).get("x", 0) or 0),
            y=int(widgets.get(widget_id, {}).get("y", 0) or 0),
        )
        for widget_id, label_text, _attribute in IN_GAME_WIDGET_TILES
        if widgets.get(widget_id, {}).get("enabled")
    )


def update_in_game_overlay_status_ui(parent_mixin: Any) -> None:
    hero = getattr(parent_mixin, "igo_hero", None)
    if hero is None:
        return

    # `enabled` is what the user asked for; whether the transparent window is
    # actually up is a separate fact, and it is the one the badge claims. The
    # old label read the config flag alone, so a window that failed to appear
    # still reported Running -- tolerable in a small grey label, not in a green
    # badge two centimetres wide.
    wanted = bool(config.IN_GAME_OVERLAY.get("enabled", False))
    window = getattr(parent_mixin, "in_game_overlay_window", None)
    visible = bool(window is not None and window.isVisible())
    edit_mode = bool(window is not None and getattr(window, "edit_mode", False))

    if edit_mode:
        hero.set_status("LAYOUT MODE", STATE_WARN)
    elif wanted and visible:
        hero.set_status("RUNNING", STATE_OK)
    elif wanted:
        # Asked for and not on screen. Usually benign -- the overlay hides
        # itself whenever the game is not focused -- so it is a warning, not an
        # error, and the subtitle says which of the two this is.
        hero.set_status(
            "WAITING",
            STATE_WARN,
            detail="Overlay is on, but the game window is not in front.",
        )
    else:
        hero.set_status("STOPPED", STATE_OFF)

    toggle = getattr(parent_mixin, "igo_toggle_btn", None)
    if toggle is not None:
        start_text, stop_text = IN_GAME_OVERLAY_CAPTIONS
        toggle.setText(stop_text if wanted else start_text)
        _set_widget_style_role(toggle, "stopScanner" if wanted else "primary")


def _add_scale_group(layout, *, title: str, attr_name: str, widget_id: str, parent: Any) -> None:
    group = QGroupBox(title)
    group_layout = QVBoxLayout(group)
    group_layout.setContentsMargins(16, 12, 16, 12)
    _add_scale_row(group_layout, parent, attr_name, widget_id)
    layout.addWidget(group)


def _add_scale_row(layout, parent: Any, attr_name: str, widget_id: str) -> None:
    scale_layout = QHBoxLayout()
    scale_layout.addWidget(QLabel("Scale:"))
    spin = QDoubleSpinBox()
    spin.setRange(0.5, 3.0)
    spin.setSingleStep(0.1)
    spin.setValue(config.IN_GAME_OVERLAY["widgets"][widget_id].get("scale", 1.0))
    spin.valueChanged.connect(parent._save_settings)
    scale_layout.addWidget(spin)
    scale_layout.addStretch(1)
    layout.addLayout(scale_layout)
    setattr(parent, attr_name, spin)


def _build_checkbox(label: str, checked: bool, handler) -> QCheckBox:
    checkbox = QCheckBox(label)
    checkbox.setChecked(checked)
    checkbox.stateChanged.connect(handler)
    return checkbox
