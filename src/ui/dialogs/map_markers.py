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
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
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
from ui.shared import _make_scroll_section, resource_path


def _action_icon(action: MapMarkerAction) -> QIcon:
    return QIcon(resource_path(f"media/map_markers/pictograms/{action.icon_name}.svg"))


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
        QTimer.singleShot(0, self._grab_inputs)

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
    """Manual Full Map bindings and the opt-in automatic-discovery policy."""

    def __init__(
        self,
        bindings: Any,
        parent: QWidget | None = None,
        *,
        automatic_discovery: bool = False,
        binding_dialog_factory=MapMarkerBindingDialog,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Map Activity Markers")
        self.setModal(True)
        self._bindings = deepcopy(normalize_map_marker_hotkeys(bindings))
        self._binding_dialog_factory = binding_dialog_factory

        layout = dialog_body(
            self,
            title="Map Activity Markers",
            subtitle="Configure manual placement and optionally enable automatic discovery for supported activities.",
            width=DIALOG_WIDE,
            height=520,
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

        automatic_card = QFrame()
        automatic_card.setObjectName("card")
        automatic_layout = QVBoxLayout(automatic_card)
        automatic_layout.setContentsMargins(14, 11, 14, 11)
        automatic_layout.setSpacing(4)
        self.automatic_discovery_cb = QCheckBox(
            "Automatically mark discovered activities"
        )
        self.automatic_discovery_cb.setObjectName("automaticDiscoveryCheck")
        self.automatic_discovery_cb.setChecked(bool(automatic_discovery))
        automatic_layout.addWidget(self.automatic_discovery_cb)
        automatic_note = QLabel(
            "Off keeps manual hotkeys only. When enabled, supported activities are "
            "added after the game's normal interaction system selects them nearby."
        )
        automatic_note.setObjectName("dialogNote")
        automatic_note.setWordWrap(True)
        automatic_layout.addWidget(automatic_note)
        layout.addWidget(automatic_card)

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

    def _remove(self, index: int) -> None:
        if 0 <= index < len(self._bindings):
            self._bindings.pop(index)
            self._refresh_rows()
