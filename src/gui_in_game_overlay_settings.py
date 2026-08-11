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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import config
from core.luck_rarity import LUCK_RARITY_MODEL_ATTRIBUTION
from ui.run_toggle import IN_GAME_OVERLAY_CAPTIONS
from ui.dialogs.shell import DIALOG_REGULAR, dialog_body, dialog_footer
from ui.settings_card import SettingsCard, build_workspace
from ui.shared import LabeledSwitch, _make_scroll_section
from ui.styles import _set_widget_style_role
from ui.tab_hero import STATE_OFF, STATE_OK, STATE_WARN, TabHero

#: The seven in-game widgets, in table order, with the label each row carries
#: and the attribute its enable toggle is stored under.
#:
#: Named for rows rather than tiles because that is what they are now: the
#: on/off grid and the scale dialog merged into one table, so a widget is one
#: line rather than a tile here and a group box over there. The mock merged
#: `stats` and `event_timer` into a single entry; they are two independent
#: config keys, and merging them would have taken away "timer without stats".
IN_GAME_WIDGET_ROWS = (
    ("scanner", "Scanner status", "igo_scanner_cb"),
    ("recording", "Recording status", "igo_recording_cb"),
    ("kps", "KPS", "igo_kps_cb"),
    ("powerups", "Active powerups", "igo_powerups_cb"),
    ("luck_rarity", "Luck rarity %", "igo_luck_rarity_cb"),
    ("stats", "Stats", "igo_stats_cb"),
    ("event_timer", "Event timer", "igo_event_timer_cb"),
    ("item_cooldowns", "Item cooldowns", "igo_item_cooldowns_cb"),
    ("build_progression", "Build Progression", "igo_build_progression_cb"),
)


#: Which attribute each widget's scale spin box is stored under. The table
#: builder writes them and `_on_igo_settings_changed` reads all of them back by
#: name, so the two need one list rather than two hand-kept copies -- a rename
#: on one side alone is a setting that silently stops saving.
#: `igo_`-prefixed like every other widget this builder writes onto the
#: component, which is what the enable toggles beside them are already called.
#: The bare names these carried came from the dialog, where the prefix would
#: have been noise; on the component it is the convention.
IGO_SCALE_SPIN_ATTRIBUTES = {
    "scanner": "igo_scanner_scale_spin",
    "recording": "igo_recording_scale_spin",
    "kps": "igo_kps_scale_spin",
    "powerups": "igo_powerups_scale_spin",
    "luck_rarity": "igo_luck_rarity_scale_spin",
    "stats": "igo_stats_scale_spin",
    "event_timer": "igo_event_timer_scale_spin",
    "item_cooldowns": "igo_item_cooldowns_scale_spin",
    "build_progression": "igo_build_progression_scale_spin",
}


class InGameWidgetSettingsDialog(QDialog):
    """The stats picker, and only that.

    It used to hold every widget's scale and flags as well. Those are a table on
    the tab now -- they were always about the same seven widgets, and keeping
    half of them behind a modal only paid while that modal was a 700x760 window
    with tabs of its own. What is left is the one thing that does not fit a
    table row: fourteen checkboxes and a reset.

    The name is unchanged because `InGameOverlay` takes it as an injected
    default and the tab reaches it through `_open_igo_widget_settings_dialog`.
    """

    def __init__(self, parent_mixin: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_mixin = parent_mixin
        self.setWindowTitle("Stats shown by the Stats widget")

        layout = dialog_body(
            self,
            title="Stats widget",
            subtitle="Which stats the in-game Stats widget shows. None selected falls back to four.",
            width=DIALOG_REGULAR,
        )

        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(10)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        selected_stats = set(config.IN_GAME_OVERLAY["widgets"]["stats"].get(
            "selected_stats", ["Damage", "Difficulty", "XP Gain", "Luck"]))

        self.stats_checkboxes: dict[str, QCheckBox] = {}
        for index, label in enumerate(config.ALL_STAT_LABELS):
            cb = QCheckBox(label)
            cb.setChecked(label in selected_stats)
            cb.stateChanged.connect(self._save_settings)
            self.stats_checkboxes[label] = cb
            grid_layout.addWidget(cb, index // 4, index % 4)

        layout.addWidget(grid_widget)
        layout.addStretch(1)

        self.stats_reset_btn = QPushButton("Reset to Default Stats")
        self.stats_reset_btn.clicked.connect(self._reset_stats_to_default)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        dialog_footer(self, primary=close_btn, destructive=self.stats_reset_btn)

    def _reset_stats_to_default(self) -> None:
        default_stats = set(config.DEFAULT_IN_GAME_OVERLAY["widgets"]["stats"]["selected_stats"])
        for label, cb in self.stats_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(label in default_stats)
            cb.blockSignals(False)
        self._save_settings()

    def _save_settings(self, *_args) -> None:
        selected = [
            label for label in config.ALL_STAT_LABELS
            if self.stats_checkboxes[label].isChecked()
        ]
        # The empty list is not stored: the widget falls back to four defaults,
        # and writing `[]` would make "I unticked everything" and "I never chose"
        # the same saved state.
        config.IN_GAME_OVERLAY["widgets"]["stats"]["selected_stats"] = (
            selected or ["Damage", "Difficulty", "XP Gain", "Luck"]
        )
        self.parent_mixin.apply_in_game_overlay_settings()
        config.save_config(config.user_config)
        # The Stats row on the tab reports this count; without the call it keeps
        # whatever it said when the tab was built.
        refresh_in_game_overlay_stats_summary(self.parent_mixin)


def build_in_game_overlay_tab(parent_mixin: Any) -> None:
    parent_mixin.tab_in_game_overlay = QWidget()
    tab_layout = QVBoxLayout(parent_mixin.tab_in_game_overlay)
    tab_layout.setContentsMargins(0, 0, 0, 0)

    scroll, _scroll_content, layout = _make_scroll_section()
    layout.setSpacing(12)
    layout.setContentsMargins(8, 8, 8, 8)
    tab_layout.addWidget(scroll)

    layout.addWidget(_build_igo_hero(parent_mixin))

    # No rail on this tab. Its two cards and the hero now share one left edge
    # and one right edge, which is the "everything on one level" the layout was
    # asked for -- and the rail had nothing left to hold anyway once the tip
    # went (see `_build_igo_layout_card` for why it went).
    main_column, _rail = build_workspace(layout, rail_width=None, max_width=None)

    _build_igo_layout_card(parent_mixin, main_column)
    _build_igo_widgets_card(parent_mixin, main_column)
    main_column.addStretch(1)

    layout.addStretch(1)
    update_in_game_overlay_status_ui(parent_mixin)
    refresh_in_game_overlay_hotkey_ui(parent_mixin)
    refresh_in_game_overlay_target_window(parent_mixin)

    # A slow poll for the one live fact this tab still shows. It used to drive
    # the canvas preview as well; the preview is gone and the detection line is
    # not, because whether the game is running changes without anything else in
    # this tab ticking.
    parent_mixin.igo_target_window_timer = QTimer(parent_mixin.tab_in_game_overlay)
    parent_mixin.igo_target_window_timer.setInterval(1500)
    parent_mixin.igo_target_window_timer.timeout.connect(
        lambda: refresh_in_game_overlay_target_window(parent_mixin)
    )
    parent_mixin.igo_target_window_timer.start()


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
        subtitle="Press the hotkey to drag the widgets over the game; it saves on exit.",
    )

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(8)

    hotkey_row = QWidget()
    hotkey_row.setObjectName("fieldRow")
    hotkey_layout = QHBoxLayout(hotkey_row)
    hotkey_layout.setContentsMargins(0, 0, 0, 0)
    hotkey_layout.setSpacing(8)
    parent_mixin.igo_hotkey_entry = QLineEdit(hotkey_row)
    parent_mixin.igo_hotkey_entry.setMaximumWidth(90)
    parent_mixin.igo_hotkey_entry.editingFinished.connect(
        lambda: _save_in_game_overlay_hotkey(parent_mixin)
    )
    hotkey_layout.addWidget(parent_mixin.igo_hotkey_entry)
    hotkey_layout.addStretch(1)
    form.addRow("Edit hotkey:", hotkey_row)

    window_row = QWidget()
    window_row.setObjectName("fieldRow")
    window_layout = QHBoxLayout(window_row)
    window_layout.setContentsMargins(0, 0, 0, 0)
    window_layout.setSpacing(8)
    window_name = QLineEdit(str(getattr(config, "PROCESS_NAME", "") or ""), window_row)
    window_name.setReadOnly(True)
    # Capped, not stretched. The card spans the tab now, and a process name in a
    # field the width of the window is the same "row with its two ends half a
    # screen apart" the tile grid was fixed for.
    window_name.setMaximumWidth(320)
    window_layout.addWidget(window_name)
    parent_mixin.igo_target_window_label = QLabel("", window_row)
    parent_mixin.igo_target_window_label.setObjectName("fieldSuffix")
    window_layout.addWidget(parent_mixin.igo_target_window_label)
    form.addRow("Target window:", window_row)

    # The form takes the width it needs and the tip takes the right-hand end of
    # the same card. Card 1 has two short rows in it; stretched across the tab it
    # was two thirds empty, and that empty third is the only piece of this tab
    # with nothing to do. A tip beside them costs no height at all -- the card is
    # already as tall as the form.
    body = QHBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(16)
    body.addLayout(form, 0)
    body.addStretch(1)
    body.addWidget(_build_igo_tip(parent_mixin), 0, Qt.AlignTop)

    card.body.addLayout(body)
    column.addWidget(card)


#: How wide the tip beside card 1's form is allowed to be. Three lines at this
#: width; letting it size itself put the whole sentence on one line running the
#: width of the tab, which is the shape the OBS tip was widened out of.
_TIP_WIDTH = 380


def _build_igo_tip(parent_mixin: Any) -> QFrame:
    """The layout-mode hint, back in card 1 rather than in a rail of its own.

    It went when the rail did, on the grounds that the sentence beside the
    hotkey field said the same thing. That sentence is gone now: with layout
    mode reachable only by hotkey, this is the only place the app explains how
    to get into it, and it names the key -- so `refresh_in_game_overlay_hotkey_ui`
    has to re-render it whenever the key changes, from either editor.
    """
    tip = QFrame()
    tip.setObjectName("tipCard")
    tip.setProperty("tipCard", "true")
    tip.setFixedWidth(_TIP_WIDTH)
    tip_layout = QVBoxLayout(tip)
    tip_layout.setContentsMargins(12, 11, 12, 11)
    tip_layout.setSpacing(4)

    title = QLabel("◎ LAYOUT SHORTCUT", tip)
    title.setObjectName("tipCardTitle")
    tip_layout.addWidget(title)

    parent_mixin.igo_tip_label = QLabel("", tip)
    parent_mixin.igo_tip_label.setObjectName("tipCardText")
    parent_mixin.igo_tip_label.setWordWrap(True)
    tip_layout.addWidget(parent_mixin.igo_tip_label)
    return tip


def _build_igo_widgets_card(parent_mixin: Any, column) -> None:
    """One table: what is on, how big it is, and whatever else it has.

    This used to be a grid of on/off tiles with a `Widget Settings` button
    opening a dialog that held the scales. The two halves were always about the
    same seven widgets, and splitting them across a tab and a modal was worth it
    only while that modal was a 700x760 window with tabs of its own. Once it
    became a 639x348 table it fitted the tab with room to spare -- and the tab
    had about 1560x580 of nothing in it.

    The stats picker stays behind a button. Fourteen checkboxes is the one thing
    here that genuinely does not fit a row.
    """
    card = SettingsCard(
        number=2,
        title="In-game widgets",
        subtitle="What is shown over the game, how big, and with what.",
    )

    table = QGridLayout()
    # Roomy, but the columns are still sized to their contents and grouped at
    # the left. Distributing them across the card was tried and measured: on a
    # 1920 window the Event timer row put its name at x=24 and its switch at
    # x=1210, which is the same "two ends of one row half a screen apart" the
    # tile grid was fixed for. A row has to be readable in one look; the surplus
    # width is better spent on nothing.
    table.setHorizontalSpacing(34)
    table.setVerticalSpacing(10)
    table.setColumnStretch(3, 1)
    table.setContentsMargins(6, 0, 6, 0)

    for index, title in enumerate(("Widget", "", "Scale", "Options")):
        if not title:
            continue
        header = QLabel(title)
        header.setObjectName("tableHeader")
        table.addWidget(header, 0, index)

    for row, (widget_id, label, attribute) in enumerate(IN_GAME_WIDGET_ROWS, start=1):
        name = _IgoRowNameLabel(label)
        name.setObjectName("tableRowName")
        table.addWidget(name, row, 0)

        # `LabeledSwitch` with no caption: the name is already the first column,
        # and the tab's `_on_igo_settings_changed` reads these back by attribute
        # exactly as it read the tiles, so nothing downstream changes.
        toggle = LabeledSwitch("")
        toggle.setChecked(bool(config.IN_GAME_OVERLAY["widgets"][widget_id]["enabled"]))
        toggle.stateChanged.connect(parent_mixin._on_igo_settings_changed)
        setattr(parent_mixin, attribute, toggle)
        # The name drives the switch, the same way the caption did when these
        # rows were captioned checkboxes. Splitting the name into its own
        # `QLabel` silently took that away: the click target went from the full
        # width of "Recording status" to a 40px switch, which is what a user
        # notices as the control being hard to hit. `ModuleTile` solved the same
        # problem for the tile grids by making the whole tile the target.
        name.set_target(toggle)
        table.addWidget(toggle, row, 1)

        table.addWidget(_igo_scale_spin(parent_mixin, widget_id), row, 2)

        options = _igo_widget_options(parent_mixin, widget_id)
        if options is None:
            options = QLabel("—")
            options.setObjectName("tableRowEmpty")
        table.addWidget(options, row, 3)

    card.body.addLayout(table)
    column.addWidget(card)


class _IgoRowNameLabel(QLabel):
    """The widget-name cell, which toggles the switch on its row.

    A plain `QLabel` here is what made these rows feel broken: the eye reads
    "name + switch" as one control, and only the switch answered. Restoring the
    captioned-checkbox behaviour costs one press handler.

    Deliberately not a `buddy`: `setBuddy` only wires the Alt-mnemonic, which
    these captions do not have, and does nothing for a mouse press.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._target: LabeledSwitch | None = None

    def set_target(self, target: LabeledSwitch) -> None:
        self._target = target
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        # On release, not press: a press that leaves the label before releasing
        # is a cancelled click everywhere else in Qt, and toggling on press
        # would make it commit anyway.
        target = self._target
        if (
            target is not None
            and event.button() == Qt.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            target.setChecked(not target.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _igo_scale_spin(parent_mixin: Any, widget_id: str) -> QDoubleSpinBox:
    """The one control every widget has, named per widget for the saver."""
    spin = QDoubleSpinBox()
    spin.setRange(0.5, 3.0)
    spin.setSingleStep(0.1)
    spin.setMaximumWidth(88)
    spin.setValue(config.IN_GAME_OVERLAY["widgets"][widget_id].get("scale", 1.0))
    spin.valueChanged.connect(parent_mixin._on_igo_settings_changed)
    setattr(parent_mixin, IGO_SCALE_SPIN_ATTRIBUTES[widget_id], spin)
    return spin


def _igo_widget_options(parent_mixin: Any, widget_id: str) -> QWidget | None:
    """Whatever else a widget has, on one line, or `None` for nothing."""
    if widget_id == "kps":
        holder, row = _options_row()
        selected = set(config.IN_GAME_OVERLAY["widgets"]["kps"].get("metrics", ["instant"]))
        for attribute, caption, key in (
            ("igo_kps_instant_cb", "KPS", "instant"),
            ("igo_kps_60s_cb", "60s", "60s"),
            ("igo_kps_5m_cb", "5m", "5m"),
            ("igo_kps_run_cb", "Run", "run"),
        ):
            checkbox = _build_checkbox(caption, key in selected, parent_mixin._on_igo_settings_changed)
            setattr(parent_mixin, attribute, checkbox)
            row.addWidget(checkbox)
        row.addStretch(1)
        return holder

    if widget_id == "luck_rarity":
        holder, row = _options_row()
        settings = config.IN_GAME_OVERLAY["widgets"]["luck_rarity"]
        parent_mixin.igo_luck_bar_cb = _build_checkbox(
            "Bar", bool(settings.get("show_bar", True)), parent_mixin._on_igo_settings_changed
        )
        row.addWidget(parent_mixin.igo_luck_bar_cb)
        # Independent of the bar, not nested under it: all four combinations are
        # valid, and the block anchors to the percentage row, which is always
        # drawn.
        parent_mixin.igo_luck_expected_cb = _build_checkbox(
            "Expected", bool(settings.get("show_expected", False)),
            parent_mixin._on_igo_settings_changed,
        )
        parent_mixin.igo_luck_expected_cb.setToolTip(LUCK_RARITY_MODEL_ATTRIBUTION)
        row.addWidget(parent_mixin.igo_luck_expected_cb)
        parent_mixin.igo_luck_layout_combo = QComboBox()
        for caption, value in (("Column", "column"), ("Row", "row")):
            parent_mixin.igo_luck_layout_combo.addItem(caption, value)
        parent_mixin.igo_luck_layout_combo.setCurrentIndex(
            max(0, parent_mixin.igo_luck_layout_combo.findData(
                settings.get("expected_layout", "column")))
        )
        parent_mixin.igo_luck_layout_combo.setMaximumWidth(108)
        parent_mixin.igo_luck_layout_combo.currentIndexChanged.connect(
            parent_mixin._on_igo_settings_changed
        )
        row.addWidget(parent_mixin.igo_luck_layout_combo)
        row.addStretch(1)
        return holder

    if widget_id == "event_timer":
        holder, row = _options_row()
        row.addWidget(QLabel("Warn at"))
        parent_mixin.igo_event_warning_spin = QSpinBox()
        parent_mixin.igo_event_warning_spin.setRange(1, 300)
        parent_mixin.igo_event_warning_spin.setMaximumWidth(78)
        parent_mixin.igo_event_warning_spin.setValue(
            config.IN_GAME_OVERLAY["widgets"]["event_timer"].get("warning_seconds", 15)
        )
        parent_mixin.igo_event_warning_spin.setSuffix(" s")
        parent_mixin.igo_event_warning_spin.valueChanged.connect(
            parent_mixin._on_igo_settings_changed
        )
        row.addWidget(parent_mixin.igo_event_warning_spin)
        row.addStretch(1)
        return holder

    if widget_id == "stats":
        holder, row = _options_row()
        parent_mixin.igo_widget_settings_btn = QPushButton("Choose stats…")
        parent_mixin.igo_widget_settings_btn.clicked.connect(
            parent_mixin._open_igo_widget_settings_dialog
        )
        row.addWidget(parent_mixin.igo_widget_settings_btn)
        parent_mixin.igo_stats_summary_label = QLabel("")
        parent_mixin.igo_stats_summary_label.setObjectName("tableRowEmpty")
        row.addWidget(parent_mixin.igo_stats_summary_label)
        row.addStretch(1)
        refresh_in_game_overlay_stats_summary(parent_mixin)
        return holder

    if widget_id == "build_progression":
        holder, row = _options_row()
        settings = config.IN_GAME_OVERLAY["widgets"]["build_progression"]
        configure = QPushButton("Configure build…")
        configure.clicked.connect(parent_mixin._open_build_progression_dialog)
        row.addWidget(configure)
        parent_mixin.igo_build_max_rows_spin = QSpinBox()
        parent_mixin.igo_build_max_rows_spin.setRange(1, 20)
        parent_mixin.igo_build_max_rows_spin.setValue(int(settings.get("max_rows", 5)))
        parent_mixin.igo_build_max_rows_spin.valueChanged.connect(parent_mixin._on_igo_settings_changed)
        parent_mixin.igo_build_max_rows_spin.setPrefix("Rows ")
        row.addWidget(parent_mixin.igo_build_max_rows_spin)
        parent_mixin.igo_build_completed_cb = _build_checkbox(
            "Completed", bool(settings.get("show_completed", False)), parent_mixin._on_igo_settings_changed
        )
        parent_mixin.igo_build_time_cb = _build_checkbox(
            "Time", bool(settings.get("show_target_time", True)), parent_mixin._on_igo_settings_changed
        )
        parent_mixin.igo_build_headings_cb = _build_checkbox(
            "Headings", bool(settings.get("show_section_headings", False)), parent_mixin._on_igo_settings_changed
        )
        row.addWidget(parent_mixin.igo_build_completed_cb)
        row.addWidget(parent_mixin.igo_build_time_cb)
        row.addWidget(parent_mixin.igo_build_headings_cb)
        row.addStretch(1)
        return holder

    return None


def _options_row() -> tuple[QWidget, QHBoxLayout]:
    holder = QWidget()
    holder.setObjectName("fieldRow")
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    return holder, row


def refresh_in_game_overlay_stats_summary(parent_mixin: Any) -> None:
    """How many stats the picker has selected, on the Stats row.

    "None selected" is a real state -- the widget falls back to four defaults --
    and a bare button would hide it.
    """
    label = getattr(parent_mixin, "igo_stats_summary_label", None)
    if label is None:
        return
    selected = config.IN_GAME_OVERLAY["widgets"]["stats"].get("selected_stats") or []
    label.setText(f"{len(selected)} selected" if selected else "defaults")


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


def refresh_in_game_overlay_target_window(parent_mixin: Any) -> None:
    """Say whether the game window is there, in card 1.

    All that is left of what used to be a canvas preview beside it. The preview
    was removed because it answered its question badly and only when it could
    not help: the frame of reference is the game's client rect, so with the game
    closed -- which is when you are usually in this tab -- there was nothing to
    scale against, and with the game open the hotkey shows the real layout over
    the real window at full size. This line is the part that was worth keeping.
    """
    label = getattr(parent_mixin, "igo_target_window_label", None)
    if label is None:
        return
    if not parent_mixin.is_in_game_overlay_tab_active():
        return

    detected = parent_mixin._in_game_overlay_target_geometry() is not None
    label.setText("Detected" if detected else "Not running")
    label.setProperty("state", STATE_OK if detected else STATE_OFF)
    style = label.style()
    if style is not None:
        style.unpolish(label)
        style.polish(label)


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


def _build_checkbox(label: str, checked: bool, handler) -> QCheckBox:
    checkbox = QCheckBox(label)
    checkbox.setChecked(checked)
    checkbox.stateChanged.connect(handler)
    return checkbox
