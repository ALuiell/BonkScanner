"""Settings dialogs for manual Full Map activity markers."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeyEvent, QKeySequence, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionGroupBox,
    QVBoxLayout,
    QWidget,
)

from core.map_markers import (
    MAP_MARKER_ACTIONS,
    MAP_MARKER_ACTION_BY_ID,
    MapMarkerAction,
    display_input_binding,
    normalize_input_binding,
    normalize_map_marker_hotkeys,
)
from ui.dialogs.shell import (
    DIALOG_REGULAR,
    DIALOG_WIDE,
    dialog_body,
    dialog_footer,
    dialog_note,
)
from ui.shared import PremiumFeatureBadge, _make_scroll_section, resource_path


class _PremiumMapGroup(QGroupBox):
    """Use the native group-title gap for a transparent, clickable title."""

    def __init__(self):
        super().__init__("Premium")
        self.title_badge = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.title_badge is not None:
            option = QStyleOptionGroupBox()
            self.initStyleOption(option)
            bounds = self.style().subControlRect(
                QStyle.CC_GroupBox, option, QStyle.SC_GroupBoxLabel, self
            )
            # The native title only reserves the border gap. Give the visible
            # title its own full size so neither the icon nor text can be
            # clipped by the native label rectangle.
            title_size = self.title_badge.sizeHint()
            title_height = max(title_size.height(), self.title_badge.minimumHeight())
            self.title_badge.setGeometry(
                14,
                max(0, bounds.center().y() - title_height // 2),
                title_size.width(),
                title_height,
            )


def _premium_map_option(checkbox, description, control, parent):
    option = QWidget(parent)
    option.setObjectName("mapMarkerBehaviorOption")
    column = QVBoxLayout(option)
    column.setContentsMargins(14, 0, 14, 0)
    column.setSpacing(4)
    title = QHBoxLayout()
    title.setSpacing(8)
    if control is not None:
        control.setMinimumHeight(36)
    checkbox.setObjectName("PremiumFeatureCheck")
    title.addWidget(checkbox)
    title.addStretch(1)
    if control is not None:
        title.addWidget(control)
    column.addLayout(title)
    note = QLabel(description, option)
    note.setObjectName("PremiumFeatureNote")
    note.setContentsMargins(24, 0, 0, 0)
    note.setWordWrap(True)
    column.addWidget(note)
    return option


def _action_icon(action: MapMarkerAction) -> QIcon:
    return QIcon(
        resource_path(
            f"media/map_markers/pictograms/{action.settings_pictogram_file}"
        )
    )


class InputBindingRecorder(QPushButton):
    """A focused recorder for one keyboard or supported mouse input."""

    bindingChanged = Signal(str)

    def __init__(self, binding: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binding = normalize_input_binding(binding) or ""
        self._recording = False
        self.setMinimumHeight(38)
        self.setToolTip("Click, then press a keyboard key, Middle Mouse, Mouse 4 or Mouse 5.")
        self.clicked.connect(self.start_recording)
        self._refresh_text()

    @property
    def binding(self) -> str:
        return self._binding

    def set_binding(self, value: str) -> None:
        self._binding = normalize_input_binding(value) or ""
        self._finish_recording()
        self._refresh_text()

    def start_recording(self) -> None:
        if self._recording:
            return
        self._recording = True
        self.setProperty("recording", True)
        self.setText("Press a key or mouse button…")
        self.setFocus(Qt.OtherFocusReason)
        self.style().unpolish(self)
        self.style().polish(self)
        # The click that entered recording must finish before the mouse grab;
        # otherwise that same Left click would be interpreted as the binding.
        QTimer.singleShot(0, self, self._grab_inputs)

    def _grab_inputs(self) -> None:
        if not self._recording or not self.isVisible():
            return
        self.grabKeyboard()
        self.grabMouse()

    def _finish_recording(self) -> None:
        self._recording = False
        self.setProperty("recording", False)
        if QWidget.keyboardGrabber() is self:
            self.releaseKeyboard()
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.style().unpolish(self)
        self.style().polish(self)

    def _refresh_text(self) -> None:
        self.setText(display_input_binding(self._binding) if self._binding else "Record input")

    def _record(self, candidate: str) -> None:
        normalized = normalize_input_binding(candidate)
        if normalized is None:
            self.setText("Reserved or unsupported — try another input")
            return
        self._binding = normalized
        self._finish_recording()
        self._refresh_text()
        self.bindingChanged.emit(normalized)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape:
            self._finish_recording()
            self._refresh_text()
            event.accept()
            return
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            self._binding = ""
            self._finish_recording()
            self._refresh_text()
            self.bindingChanged.emit("")
            event.accept()
            return
        if event.key() in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            event.accept()
            return

        base = QKeySequence(event.key()).toString(QKeySequence.PortableText).strip().lower()
        if not base:
            event.accept()
            return
        modifiers = event.modifiers()
        parts: list[str] = []
        for flag, token in (
            (Qt.ControlModifier, "ctrl"),
            (Qt.AltModifier, "alt"),
            (Qt.ShiftModifier, "shift"),
            (Qt.MetaModifier, "win"),
        ):
            if modifiers & flag:
                parts.append(token)
        parts.append(base)
        self._record("+".join(parts))
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._recording:
            super().mousePressEvent(event)
            return
        token = {
            Qt.MiddleButton: "mouse_middle",
            Qt.BackButton: "mouse4",
            Qt.ForwardButton: "mouse5",
        }.get(event.button())
        if token is None:
            self.setText("Use Middle Mouse, Mouse 4 or Mouse 5")
        else:
            self._record(token)
        event.accept()

    def hideEvent(self, event: QEvent) -> None:
        self._finish_recording()
        super().hideEvent(event)


class MapMarkerBindingDialog(QDialog):
    """Add or edit one exact tap action."""

    def __init__(
        self,
        binding: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        current = dict(binding or {})
        editing = bool(binding)
        self.setWindowTitle("Edit Marker Hotkey" if editing else "Add Marker Hotkey")
        self.setModal(True)

        layout = dialog_body(
            self,
            title="Edit hotkey" if editing else "Add hotkey",
            subtitle="A tap places the selected marker. Holding the same input opens the full marker palette.",
            width=DIALOG_REGULAR,
        )

        input_label = QLabel("1  Input")
        input_label.setObjectName("tableHeader")
        layout.addWidget(input_label)
        self.input_recorder = InputBindingRecorder(current.get("input", ""))
        layout.addWidget(self.input_recorder)
        layout.addWidget(
            dialog_note(
                "Supported: keyboard, Middle Mouse, Mouse 4 and Mouse 5. "
                "Tab, Escape, Left/Right click, wheel and plain movement keys stay reserved."
            )
        )

        activity_label = QLabel("2  Activity")
        activity_label.setObjectName("tableHeader")
        layout.addWidget(activity_label)
        self.action_combo = QComboBox()
        for index, action in enumerate(MAP_MARKER_ACTIONS):
            if index in (4, 8):
                self.action_combo.insertSeparator(self.action_combo.count())
            self.action_combo.addItem(_action_icon(action), action.display_name, action.id)
        requested_action = current.get("action", "")
        requested_index = self.action_combo.findData(requested_action)
        self.action_combo.setCurrentIndex(requested_index if requested_index >= 0 else 0)
        self.action_combo.setIconSize(QSize(24, 24))
        self.action_combo.setMinimumHeight(38)
        layout.addWidget(self.action_combo)

        layout.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save Hotkey")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(bool(self.input_recorder.binding))
        self.input_recorder.bindingChanged.connect(
            lambda value: self.save_btn.setEnabled(bool(value))
        )
        dialog_footer(self, primary=self.save_btn, secondary=cancel_btn)

    @property
    def binding(self) -> dict[str, str]:
        return {
            "input": self.input_recorder.binding,
            "action": str(self.action_combo.currentData() or ""),
        }

    def _save(self) -> None:
        if not self.input_recorder.binding:
            return
        self.accept()


class MapMarkerSettingsDialog(QDialog):
    """Manual Full Map bindings and the automatic-discovery policy."""

    def __init__(
        self,
        bindings: Any,
        parent: QWidget | None = None,
        *,
        automatic_discovery: bool = False,
        style: str = "modern",
        minimap_enabled: bool = False,
        minimap_scale: float = 1.0,
        merchant_memory_enabled: bool = False,
        merchant_stock_display: str = "smart",
        merchant_prices_enabled: bool = False,
        has_premium_access: bool = False,
        open_support_settings=lambda: None,
        binding_dialog_factory=MapMarkerBindingDialog,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Map Activity Markers")
        self.setModal(True)
        self._bindings = deepcopy(normalize_map_marker_hotkeys(bindings))
        self._binding_dialog_factory = binding_dialog_factory
        self._has_premium_access = bool(has_premium_access)
        self._open_support_settings = open_support_settings

        layout = dialog_body(
            self,
            title="Map Activity Markers",
            subtitle="Configure manual placement and optionally enable automatic discovery for supported activities.",
            width=DIALOG_WIDE,
            height=700,
        )

        explanation = QFrame()
        explanation.setObjectName("InfoCard")
        explanation_layout = QHBoxLayout(explanation)
        explanation_layout.setContentsMargins(14, 11, 14, 11)
        explanation_layout.setSpacing(18)
        tap = QLabel("<b>Tap</b><br>Place the assigned marker")
        hold = QLabel("<b>Hold</b><br>Open all marker types")
        for label in (tap, hold):
            label.setTextFormat(Qt.RichText)
            explanation_layout.addWidget(label, 1)
        layout.addWidget(explanation)

        behavior_card = QFrame()
        self.behavior_card = behavior_card
        behavior_card.setObjectName("mapMarkerBehaviorCard")
        behavior_layout = QHBoxLayout(behavior_card)
        behavior_layout.setContentsMargins(14, 10, 14, 10)
        behavior_layout.setSpacing(14)

        automatic_option = QWidget(behavior_card)
        automatic_option.setObjectName("mapMarkerBehaviorOption")
        automatic_layout = QVBoxLayout(automatic_option)
        automatic_layout.setContentsMargins(0, 0, 0, 0)
        automatic_layout.setSpacing(3)
        self.automatic_discovery_cb = QCheckBox(
            "Automatically mark discovered activities"
        )
        self.automatic_discovery_cb.setObjectName("automaticDiscoveryCheck")
        self.automatic_discovery_cb.setChecked(bool(automatic_discovery))
        automatic_layout.addWidget(self.automatic_discovery_cb)
        automatic_note = QLabel(
            "Adds supported activities after the game's interaction system detects "
            "them. Off keeps manual hotkeys only."
        )
        automatic_note.setObjectName("dialogNote")
        automatic_note.setWordWrap(True)
        automatic_layout.addWidget(automatic_note)

        behavior_divider = QFrame(behavior_card)
        behavior_divider.setObjectName("mapMarkerBehaviorDivider")
        behavior_divider.setFixedWidth(1)

        appearance_option = QWidget(behavior_card)
        appearance_option.setObjectName("mapMarkerBehaviorOption")
        appearance_layout = QVBoxLayout(appearance_option)
        appearance_layout.setContentsMargins(0, 0, 0, 0)
        appearance_layout.setSpacing(3)
        self.classic_style_cb = QCheckBox("Use classic circle marker style")
        self.classic_style_cb.setObjectName("classicMarkerStyleCheck")
        self.classic_style_cb.setChecked(str(style).lower() == "classic")
        appearance_layout.addWidget(self.classic_style_cb)
        appearance_note = QLabel(
            "Uses colored circles with dark activity symbols instead of detailed "
            "pictograms."
        )
        appearance_note.setObjectName("dialogNote")
        appearance_note.setWordWrap(True)
        appearance_layout.addWidget(appearance_note)

        behavior_layout.addWidget(automatic_option, 1)
        behavior_layout.addWidget(behavior_divider)
        behavior_layout.addWidget(appearance_option, 1)
        layout.addWidget(behavior_card)

        premium_card = _PremiumMapGroup()
        self.premium_card = premium_card
        premium_card.setObjectName("mapMarkerPremiumGroup")
        premium_layout = QVBoxLayout(premium_card)
        premium_layout.setContentsMargins(0, 14, 0, 12)
        premium_layout.setSpacing(8)
        premium_options = QHBoxLayout()
        premium_options.setSpacing(0)
        premium_layout.addLayout(premium_options)

        self.minimap_enabled_switch = QCheckBox("Minimap markers")
        self.minimap_enabled_switch.setChecked(bool(minimap_enabled))
        self.minimap_scale_spin = QDoubleSpinBox(premium_card)
        self.minimap_scale_spin.setRange(0.5, 2.0)
        self.minimap_scale_spin.setSingleStep(0.1)
        self.minimap_scale_spin.setSuffix("×")
        self.minimap_scale_spin.setMaximumWidth(82)
        self.minimap_scale_spin.setValue(float(minimap_scale))
        self.minimap_row = _premium_map_option(
            self.minimap_enabled_switch,
            "Live activity icons, clipped to the minimap circle.",
            self.minimap_scale_spin,
            premium_card,
        )
        premium_options.addWidget(self.minimap_row, 1)

        row_divider = QFrame(premium_card)
        row_divider.setObjectName("PremiumFeatureDivider")
        row_divider.setFixedWidth(1)
        premium_options.addWidget(row_divider)

        self.merchant_memory_switch = QCheckBox("Shady Guy stock memory")
        self.merchant_memory_switch.setChecked(bool(merchant_memory_enabled))
        self.merchant_stock_display_combo = QComboBox(premium_card)
        for label, value in (
            ("Smart", "smart"),
            ("Always", "always"),
            ("Near cursor", "cursor"),
        ):
            self.merchant_stock_display_combo.addItem(label, value)
        self.merchant_stock_display_combo.setToolTip(
            "Nearby merchants share one stock card.\n"
            "Smart: avoids overlapping cards; hover to expand crowded groups.\n"
            "Always: keeps grouped stock lists visible where space allows.\n"
            "Near cursor: shows the nearest merchant's group and highlights its stock."
        )
        requested_display = str(merchant_stock_display).lower()
        display_index = self.merchant_stock_display_combo.findData(requested_display)
        self.merchant_stock_display_combo.setCurrentIndex(
            display_index if display_index >= 0 else 0
        )
        self.merchant_row = _premium_map_option(
            self.merchant_memory_switch,
            "Remembers visible item names after opening the shop.",
            self.merchant_stock_display_combo,
            premium_card,
        )
        premium_options.addWidget(self.merchant_row, 1)

        self.merchant_prices_switch = QCheckBox("Shady Guy item prices")
        self.merchant_prices_switch.setChecked(bool(merchant_prices_enabled))
        self.merchant_prices_row = _premium_map_option(
            self.merchant_prices_switch,
            "Shows the prices last seen when opening each shop. Reopen the shop to refresh them. Requires stock memory.",
            None,
            premium_card,
        )
        self.merchant_prices_switch.setEnabled(
            self._has_premium_access and bool(merchant_memory_enabled)
        )
        self.merchant_memory_switch.toggled.connect(
            lambda checked: self.merchant_prices_switch.setEnabled(self._has_premium_access and checked)
        )

        # The microwave counter follows Premium access without its own switch.
        self.microwave_uses_row = QWidget(premium_card)
        self.microwave_uses_row.setObjectName("mapMarkerBehaviorOption")
        microwave_layout = QVBoxLayout(self.microwave_uses_row)
        microwave_layout.setContentsMargins(14, 0, 14, 0)
        microwave_layout.setSpacing(10)
        microwave_divider = QFrame(self.microwave_uses_row)
        microwave_divider.setObjectName("PremiumFeatureDivider")
        microwave_divider.setFixedHeight(1)
        premium_layout.addWidget(microwave_divider)
        microwave_content = QHBoxLayout()
        microwave_content.setSpacing(8)
        microwave_icon = QLabel(self.microwave_uses_row)
        microwave_icon.setObjectName("mapMarkerMicrowaveIcon")
        microwave_icon.setFixedSize(20, 20)
        microwave_icon.setPixmap(QIcon(resource_path(
            "media/map_markers/pictograms/microwave.svg"
        )).pixmap(QSize(20, 20), self.devicePixelRatioF()))
        microwave_content.addWidget(microwave_icon, 0, Qt.AlignTop)
        microwave_copy = QVBoxLayout()
        microwave_copy.setSpacing(3)
        microwave_heading = QHBoxLayout()
        microwave_heading.setSpacing(8)
        self.microwave_uses_title = QLabel("Microwave uses counter")
        self.microwave_uses_title.setObjectName("mapMarkerAutomaticFeatureTitle")
        microwave_heading.addWidget(self.microwave_uses_title)
        self.microwave_uses_status = QLabel(
            "· Automatic" if self._has_premium_access else "· Requires Premium"
        )
        self.microwave_uses_status.setObjectName("mapMarkerAutomaticFeatureStatus")
        microwave_heading.addWidget(self.microwave_uses_status)
        microwave_heading.addStretch(1)
        microwave_copy.addLayout(microwave_heading)
        self.microwave_uses_note = QLabel(
            "Shows remaining uses on discovered microwaves."
        )
        self.microwave_uses_note.setObjectName("PremiumFeatureNote")
        self.microwave_uses_note.setWordWrap(True)
        microwave_copy.addWidget(self.microwave_uses_note)
        microwave_content.addLayout(microwave_copy, 1)
        microwave_layout.addLayout(microwave_content)
        self.microwave_uses_row.setToolTip(
            "Included automatically with Premium. Counts appear on automatically "
            "discovered microwaves, not unlinked manual markers."
        )
        extra_options = QHBoxLayout()
        extra_options.setSpacing(0)
        extra_options.addWidget(self.microwave_uses_row, 1)
        extra_divider = QFrame(premium_card)
        extra_divider.setObjectName("PremiumFeatureDivider")
        extra_divider.setFixedWidth(1)
        extra_options.addWidget(extra_divider)
        extra_options.addWidget(self.merchant_prices_row, 1)
        premium_layout.addLayout(extra_options)
        self.premium_group_badge = PremiumFeatureBadge(
            has_access=self._has_premium_access,
            open_support=self._open_support,
            parent=premium_card,
        )
        self.premium_group_badge.setProperty("mapPremiumTitle", True)
        self.premium_group_badge.setIconSize(QSize(15, 15))
        self.premium_group_badge.setFixedHeight(26)
        premium_card.title_badge = self.premium_group_badge
        self.premium_group_badge.ensurePolished()
        self.premium_group_badge.adjustSize()
        self.premium_group_badge.move(14, 0)
        self.premium_group_badge.raise_()

        for control in (
            self.minimap_enabled_switch,
            self.minimap_scale_spin,
            self.merchant_memory_switch,
            self.merchant_stock_display_combo,
        ):
            control.setEnabled(self._has_premium_access)
        self.minimap_enabled_switch.stateChanged.connect(
            lambda *_args: self.minimap_scale_spin.setEnabled(
                self._has_premium_access
                and self.minimap_enabled_switch.isChecked()
            )
        )
        self.merchant_memory_switch.stateChanged.connect(
            lambda *_args: self.merchant_stock_display_combo.setEnabled(
                self._has_premium_access
                and self.merchant_memory_switch.isChecked()
            )
        )
        self.minimap_scale_spin.setEnabled(
            self._has_premium_access and bool(minimap_enabled)
        )
        self.merchant_stock_display_combo.setEnabled(
            self._has_premium_access and bool(merchant_memory_enabled)
        )
        layout.addWidget(premium_card)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(12, 0, 12, 0)
        hotkey_header = QLabel("Hotkey")
        marker_header = QLabel("Marker")
        action_header = QLabel("Actions")
        for label in (hotkey_header, marker_header, action_header):
            label.setObjectName("tableHeader")
        hotkey_header.setFixedWidth(126)
        marker_header.setMinimumWidth(250)
        action_header.setFixedWidth(154)
        header_row.addWidget(hotkey_header)
        header_row.addWidget(marker_header, 1)
        header_row.addWidget(action_header)
        layout.addWidget(header)

        scroll, _content, self.bindings_layout = _make_scroll_section()
        self.bindings_layout.setContentsMargins(0, 0, 0, 0)
        self.bindings_layout.setSpacing(8)
        layout.addWidget(scroll, 1)

        self.add_btn = QPushButton("+  Add Hotkey")
        self.add_btn.clicked.connect(lambda: self._open_editor(None))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        dialog_footer(
            self,
            primary=save_btn,
            secondary=cancel_btn,
            leading=self.add_btn,
        )
        self._refresh_rows()

    @property
    def bindings(self) -> list[dict[str, str]]:
        return deepcopy(self._bindings)

    @property
    def automatic_discovery(self) -> bool:
        return self.automatic_discovery_cb.isChecked()

    @property
    def marker_style(self) -> str:
        return "classic" if self.classic_style_cb.isChecked() else "modern"

    @property
    def minimap_enabled(self) -> bool:
        return self.minimap_enabled_switch.isChecked()

    @property
    def minimap_scale(self) -> float:
        return self.minimap_scale_spin.value()

    @property
    def merchant_memory_enabled(self) -> bool:
        return self.merchant_memory_switch.isChecked()

    @property
    def merchant_prices_enabled(self) -> bool:
        return self.merchant_prices_switch.isChecked()

    @property
    def merchant_stock_display(self) -> str:
        return str(self.merchant_stock_display_combo.currentData() or "smart")

    def _open_support(self) -> None:
        self.reject()
        self._open_support_settings()

    def _clear_rows(self) -> None:
        while self.bindings_layout.count():
            item = self.bindings_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _refresh_rows(self) -> None:
        self._clear_rows()
        if not self._bindings:
            empty = QFrame()
            empty.setObjectName("card")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(18, 24, 18, 24)
            title = QLabel("No marker hotkeys yet")
            title.setObjectName("emptyTitle")
            note = QLabel("Add one exact marker for a quick tap; holding it will still expose the complete palette.")
            note.setObjectName("dialogNote")
            note.setWordWrap(True)
            note.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            empty_layout.addWidget(title, 0, Qt.AlignHCenter)
            # Do not align the widget itself horizontally. An aligned word-wrap
            # QLabel keeps its narrow size hint, then wraps into a height the
            # layout did not reserve; the second line is clipped. Let it consume
            # the card width and centre only the text inside it.
            empty_layout.addWidget(note)
            self.bindings_layout.addWidget(empty)
            self.bindings_layout.addStretch(1)
            return

        for index, binding in enumerate(self._bindings):
            self.bindings_layout.addWidget(self._binding_row(index, binding))
        self.bindings_layout.addStretch(1)

    def _binding_row(self, index: int, binding: dict[str, str]) -> QWidget:
        action = MAP_MARKER_ACTION_BY_ID[binding["action"]]
        row = QFrame()
        row.setObjectName("mapMarkerBindingRow")
        row.setStyleSheet(
            "QFrame#mapMarkerBindingRow { background:#111A27; border:1px solid #26364A; border-radius:7px; }"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 9, 10, 9)
        layout.setSpacing(10)

        hotkey = QLabel(display_input_binding(binding["input"]))
        hotkey.setObjectName("hotkeyBadge")
        hotkey.setFixedWidth(126)
        hotkey.setStyleSheet(
            "background:#1C2A3C; border:1px solid #35506E; border-radius:5px; "
            "padding:5px 8px; font-weight:700; color:#DDEBFA;"
        )
        layout.addWidget(hotkey)

        icon = QLabel()
        icon.setPixmap(_action_icon(action).pixmap(26, 26))
        icon.setFixedSize(30, 30)
        layout.addWidget(icon)

        marker = QLabel(
            f"<span style='color:{action.color};'>●</span>&nbsp; {action.display_name}"
        )
        marker.setTextFormat(Qt.RichText)
        marker.setMinimumWidth(210)
        layout.addWidget(marker, 1)

        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(lambda _checked=False, row_index=index: self._open_editor(row_index))
        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("danger")
        remove_btn.clicked.connect(lambda _checked=False, row_index=index: self._remove(row_index))
        layout.addWidget(edit_btn)
        layout.addWidget(remove_btn)
        return row

    def _open_editor(self, index: int | None) -> None:
        current = self._bindings[index] if index is not None else None
        dialog = self._binding_dialog_factory(current, self)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            candidate = dialog.binding
            duplicate = next(
                (
                    row_index
                    for row_index, binding in enumerate(self._bindings)
                    if binding["input"] == candidate["input"] and row_index != index
                ),
                None,
            )
            if duplicate is not None:
                QMessageBox.warning(
                    self,
                    "Hotkey Already Assigned",
                    f"{display_input_binding(candidate['input'])} already places another marker. Edit that row instead.",
                )
                return
            if index is None:
                self._bindings.append(candidate)
            else:
                self._bindings[index] = candidate
            self._refresh_rows()
        finally:
            dialog.deleteLater()

    def _remove(self, index: int) -> None:
        if 0 <= index < len(self._bindings):
            self._bindings.pop(index)
            self._refresh_rows()
