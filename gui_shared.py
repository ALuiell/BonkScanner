from __future__ import annotations

import ctypes
import os
import sys

def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


enable_windows_dpi_awareness()

from PySide6.QtCore import QObject, QSize, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QFrame, QMainWindow, QPushButton, QScrollArea, QVBoxLayout, QWidget

TRACKED_ITEM_LIST_HEIGHT = 96

def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

def _read_text(widget) -> str:
    if widget is None:
        return ""
    if hasattr(widget, "text"):
        text_attr = getattr(widget, "text")
        return text_attr() if callable(text_attr) else str(text_attr)
    if hasattr(widget, "get"):
        return str(widget.get())
    return ""

def _set_text(widget, text: str) -> None:
    if widget is None:
        return
    if hasattr(widget, "setText"):
        widget.setText(text)
        return
    if hasattr(widget, "configure"):
        widget.configure(text=text)
        return

def _clear_text_input(widget) -> None:
    if widget is None:
        return
    if hasattr(widget, "clear"):
        widget.clear()
        return
    if hasattr(widget, "delete"):
        widget.delete(0, "end")

def _set_text_input(widget, text: str) -> None:
    if widget is None:
        return
    if hasattr(widget, "setText"):
        widget.setText(text)
        return
    if hasattr(widget, "insert"):
        widget.insert(0, text)

def _read_bool(widget) -> bool:
    if widget is None:
        return False
    if hasattr(widget, "isChecked"):
        return bool(widget.isChecked())
    if hasattr(widget, "get"):
        return bool(widget.get())
    return False

def _set_bool(widget, value: bool) -> None:
    if widget is None:
        return
    if hasattr(widget, "setChecked"):
        widget.setChecked(value)
        return
    if hasattr(widget, "set"):
        widget.set(value)

def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)

def _apply_button_icon(button: QPushButton, relative_path: str, size: int = 22) -> None:
    icon_path = resource_path(relative_path)
    if not os.path.exists(icon_path):
        return
    button.setIcon(QIcon(icon_path))
    button.setIconSize(QSize(size, size))

def _make_scroll_section() -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    scroll.setWidget(content)
    return scroll, content, layout


class CollapsibleSection(QWidget):
    def __init__(self, title: str, *, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title = str(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toggle_button = QPushButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(bool(expanded))
        self.toggle_button.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                padding: 8px 10px;
                font-weight: bold;
                border-radius: 6px;
            }
            """
        )
        self.toggle_button.toggled.connect(self.set_expanded)
        layout.addWidget(self.toggle_button)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 8, 10, 10)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        self.set_expanded(bool(expanded))

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if self.toggle_button.isChecked() != expanded:
            self.toggle_button.setChecked(expanded)
        prefix = "- " if expanded else "+ "
        self.toggle_button.setText(prefix + self._title)
        self.body.setVisible(expanded)


class CollapsibleSectionGroup:
    def __init__(self, sections=()):
        self._sections: list[CollapsibleSection] = []
        self._updating = False
        for section in sections:
            self.add_section(section)

    def add_section(self, section: CollapsibleSection) -> None:
        if section in self._sections:
            return
        self._sections.append(section)
        section.toggle_button.toggled.connect(lambda expanded, current=section: self._on_toggled(current, expanded))

    def _on_toggled(self, current: CollapsibleSection, expanded: bool) -> None:
        if self._updating or not expanded:
            return
        self._updating = True
        try:
            for section in self._sections:
                if section is not current:
                    section.set_expanded(False)
        finally:
            self._updating = False

def format_template_conditions(template: dict) -> str:
    parts = []
    sm_total = template.get("sm_total", 0)
    shady = template.get("shady", 0)
    moai = template.get("moai", 0)
    micro = template.get("micro", 0)
    boss = template.get("boss", 0)

    if sm_total > 0:
        parts.append(f"S+M: {sm_total}")
    if shady > 0:
        parts.append(f"S:{shady}")
    if moai > 0:
        parts.append(f"M:{moai}")
    if micro > 0:
        parts.append(f"Mic:{micro}")
    if boss > 0:
        parts.append(f"B:{boss}")

    return ", ".join(parts) if parts else "Any"

def build_template_payload(
    name: str,
    sm_total: str,
    shady: str,
    moai: str,
    micro: str,
    boss: str,
    source_template=None,
):
    name = name.strip()
    if not name:
        return None

    def parse_int(value: str) -> int:
        value = value.strip()
        return int(value) if value.isdigit() else 0

    result = {
        "name": name,
        "sm_total": parse_int(sm_total),
        "shady": parse_int(shady),
        "moai": parse_int(moai),
        "micro": parse_int(micro),
        "boss": parse_int(boss),
    }

    if result["sm_total"] <= 0 or result["shady"] > 0 or result["moai"] > 0:
        result.pop("sm_total", None)

    if source_template:
        for key, value in source_template.items():
            if key not in result and key not in ["sm_total", "shady", "moai", "micro", "boss"]:
                result[key] = value

    return result

class UiInvoker(QObject):
    call_now = Signal(object)
    call_later = Signal(int, object)

    def __init__(self) -> None:
        super().__init__()
        self.call_now.connect(self._execute_now)
        self.call_later.connect(self._execute_later)

    @Slot(object)
    def _execute_now(self, callback) -> None:
        callback()

    @Slot(int, object)
    def _execute_later(self, delay_ms: int, callback) -> None:
        QTimer.singleShot(max(0, int(delay_ms)), callback)

class _AppWindow(QMainWindow):
    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner

    def closeEvent(self, event: QCloseEvent) -> None:
        self.owner._handle_window_close(event)
