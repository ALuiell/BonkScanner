from __future__ import annotations

import os
import sys

from PySide6.QtCore import (
    Property,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

TRACKED_ITEM_LIST_HEIGHT = 96


class LabeledSwitch(QCheckBox):
    """A checkbox painted as the compact label-and-track control used in mocks.

    Painted rather than styled, because a QSS rule cannot reach inside a custom
    ``paintEvent`` -- but its *colours* still come from the stylesheet, through
    ``qproperty-`` on the eight properties below. That distinction is the point:
    with the values inlined in ``paintEvent`` this was the one control on the
    Live Stats tab that a palette change in `bonkscanner_redesign.qss` could not
    reach, so it would drift away from the segments and the selected sub-tab
    silently, with nothing in the stylesheet to say why.

    Selected by the ``labeledSwitch`` property rather than by objectName: there
    are two instances with two different names (Live Stats and Recordings), and
    the design intent is one control, not two. Same idiom as `SegmentedToggle`.

    The defaults below are the current design values, so the widget still looks
    right when the QSS asset is missing -- `build_stylesheet` already treats it
    as optional.
    """

    TRACK_WIDTH = 32
    TRACK_HEIGHT = 18
    KNOB_SIZE = 12
    LABEL_GAP = 8

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(24)
        self.setProperty("labeledSwitch", "true")
        self._label_color = QColor("#8A94A3")
        self._label_disabled_color = QColor("#5C6675")
        self._track_on_color = QColor("#2F6FB0")
        self._track_on_border_color = QColor("#3E82C6")
        self._knob_on_color = QColor("#EDF1F5")
        self._track_off_color = QColor("#141A22")
        self._track_off_border_color = QColor("#2E3A48")
        self._track_hover_border_color = QColor("#38495E")
        self._knob_off_color = QColor("#5C6675")

    # -- stylesheet-settable palette ------------------------------------------
    # `qproperty-labelColor: #8A94A3;` and friends. Each getter/setter pair is
    # what makes one colour reachable from QSS; there is no shorter form.

    # The accessors take `widget`, not `self`, and that is deliberate: they are
    # closures handed to `Property`, not methods, and
    # `test_no_mixin_method_is_nested_inside_a_function` reads a nested `def`
    # whose first argument is `self` as a method that missed its class. Naming
    # the parameter for what it actually is keeps that guard meaningful instead
    # of teaching it an exception.
    def _color_property(name: str):  # noqa: N805 - a definition-time helper
        attribute = f"_{name}"

        def getter(widget) -> QColor:
            return getattr(widget, attribute)

        def setter(widget, value: QColor) -> None:
            setattr(widget, attribute, QColor(value))
            widget.update()

        return Property(QColor, getter, setter)

    labelColor = _color_property("label_color")
    labelDisabledColor = _color_property("label_disabled_color")
    trackOnColor = _color_property("track_on_color")
    trackOnBorderColor = _color_property("track_on_border_color")
    knobOnColor = _color_property("knob_on_color")
    trackOffColor = _color_property("track_off_color")
    trackOffBorderColor = _color_property("track_off_border_color")
    trackHoverBorderColor = _color_property("track_hover_border_color")
    knobOffColor = _color_property("knob_off_color")

    del _color_property

    def sizeHint(self) -> QSize:
        label_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(
            label_width + self.LABEL_GAP + self.TRACK_WIDTH,
            max(24, self.fontMetrics().height()),
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        label_width = max(0, self.width() - self.LABEL_GAP - self.TRACK_WIDTH)
        label_rect = QRect(0, 0, label_width, self.height())
        label_color = QColor(
            self._label_color if self.isEnabled() else self._label_disabled_color
        )
        painter.setPen(label_color)
        painter.drawText(label_rect, Qt.AlignLeft | Qt.AlignVCenter, self.text())

        track_x = self.width() - self.TRACK_WIDTH
        track_y = (self.height() - self.TRACK_HEIGHT) / 2
        track = QRectF(track_x, track_y, self.TRACK_WIDTH, self.TRACK_HEIGHT)
        if self.isChecked():
            track_fill = QColor(self._track_on_color)
            track_border = QColor(self._track_on_border_color)
            knob_fill = QColor(self._knob_on_color)
            knob_x = track.right() - 3 - self.KNOB_SIZE
        else:
            track_fill = QColor(self._track_off_color)
            track_border = QColor(
                self._track_hover_border_color
                if self.underMouse()
                else self._track_off_border_color
            )
            knob_fill = QColor(self._knob_off_color)
            knob_x = track.left() + 3

        if not self.isEnabled():
            track_fill.setAlpha(150)
            track_border.setAlpha(150)
            knob_fill.setAlpha(150)

        painter.setPen(QPen(track_border, 1))
        painter.setBrush(track_fill)
        painter.drawRoundedRect(track, self.TRACK_HEIGHT / 2, self.TRACK_HEIGHT / 2)

        knob_y = track.top() + (self.TRACK_HEIGHT - self.KNOB_SIZE) / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob_fill)
        painter.drawEllipse(QRectF(knob_x, knob_y, self.KNOB_SIZE, self.KNOB_SIZE))


class _TabHeaderCorner(QWidget):
    """Keep a corner control centred inside the tab bar's full-height shell."""

    def __init__(self, tab_widget: QTabWidget, control: QWidget) -> None:
        super().__init__(tab_widget)
        self._tab_widget = tab_widget
        self._control = control
        self.setObjectName("SubTabsCorner")
        control.setParent(self)

    def sizeHint(self) -> QSize:
        control_hint = self._control.sizeHint()
        tab_height = self._tab_widget.tabBar().sizeHint().height()
        # QTabWidget reserves one pixel for the pane edge when sizing a corner
        # widget. Asking for one extra pixel gives the wrapper the exact visible
        # height of the tab bar instead of clipping the centred control.
        return QSize(
            control_hint.width() + 18,
            max(tab_height, control_hint.height()) + 1,
        )

    def _centre_control(self) -> None:
        hint = self._control.sizeHint()
        tab_center = self._tab_widget.tabBar().geometry().center().y()
        local_center = tab_center - self.geometry().top()
        control_center = QRect(0, 0, hint.width(), hint.height()).center().y()
        self._control.setGeometry(
            8,
            local_center - control_center,
            hint.width(),
            hint.height(),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._centre_control()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._centre_control()


class FullWidthTabWidget(QTabWidget):
    """A tab widget whose tab bar and corner control share one full-width frame."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._header_frame = QFrame(self)
        self._header_frame.setObjectName("SubTabsHeader")
        self._header_frame.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._header_frame.lower()
        self._header_control = None
        self._header_corner = None

    def setHeaderControl(self, control: QWidget) -> None:
        """Place a control vertically centred in the shared tab-header shell."""
        self._header_control = control
        self._header_corner = _TabHeaderCorner(self, control)
        self.setCornerWidget(self._header_corner, Qt.TopRightCorner)

    def headerControl(self) -> QWidget | None:
        return self._header_control

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        tab_bar = self.tabBar()
        # During QTabWidget's first resize the tab bar can still carry its
        # provisional pre-layout height (often the whole widget). Its size hint
        # is already the final pill-bar height and keeps the frame to one row.
        header_height = tab_bar.sizeHint().height()
        self._header_frame.setGeometry(0, tab_bar.y(), self.width(), header_height)
        self._header_frame.lower()

def resource_path(relative_path: str) -> str:
    bundle_path = getattr(sys, "_MEIPASS", None)
    if bundle_path is not None:
        base_path = bundle_path
    else:
        # This module moved from src/gui_shared.py to src/ui/shared.py in step
        # 17a, but both anchors it resolves against are unchanged: media/ sits
        # under src/, and everything else under the repository root. So src/ is
        # derived two levels up, not one. Left as dirname(__file__), the move
        # would have silently repointed media/ at src/ui/media and the user's
        # config.json at src/config.json -- which is exactly what step 10b did,
        # undetected for two commits. ResourcePathAnchorTests pins both values.
        source_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        repo_root = os.path.dirname(source_path)
        normalized = relative_path.replace("\\", "/")
        base_path = source_path if normalized == "media" or normalized.startswith("media/") else repo_root
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
    """Empty `layout`, and take its widgets off the screen while doing it.

    `deleteLater` only *schedules* destruction, so hide each widget immediately
    while keeping its parent. Unparenting a visible widget promotes it to a
    temporary top-level window until the deferred deletion runs.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)

def _apply_button_icon(button: QPushButton, relative_path: str, size: int = 22) -> None:
    icon_path = resource_path(relative_path)
    if not os.path.exists(icon_path):
        return
    button.setIcon(QIcon(icon_path))
    button.setIconSize(QSize(size, size))

# `background: transparent` is load-bearing, not decoration: giving a QLabel
# any per-widget stylesheet at all makes this Qt build stop inheriting the
# app-wide `QLabel { background: transparent; }` rule for that instance, and
# it paints an opaque box instead -- visible as a seam once a card's own
# background differs from the app background.
SUMMARY_LABEL_PADDING_STYLESHEET = "padding-left: 4px; background: transparent;"


def _apply_summary_label_padding(*labels) -> None:
    """Indent a summary label by one gutter.

    Lived in `gui_layout.py` until step 21. It moved here because the Compare
    Runs tab builds its own panels now, and `ui/tabs/compare_runs/tab.py`
    importing `gui_layout` for a two-line stylesheet setter would have opened a
    new `ui -> <top-level>` edge -- a `TOPLEVEL_DEBT` entry, on a list that may
    only shrink. `gui_layout` already imports from `ui.shared`, so re-exporting
    it there costs no edge in either direction.
    """
    for label in labels:
        label.setStyleSheet(SUMMARY_LABEL_PADDING_STYLESHEET)


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
                background-color: #161C24;
            }
            """
        )
        self.toggle_button.toggled.connect(self.set_expanded)
        layout.addWidget(self.toggle_button)

        self.body = QWidget()
        self.body.setObjectName("cardContent")
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
        self._normalize_expanded_sections()

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

    def _normalize_expanded_sections(self) -> None:
        first_expanded = None
        self._updating = True
        try:
            for section in self._sections:
                if not section.toggle_button.isChecked():
                    continue
                if first_expanded is None:
                    first_expanded = section
                else:
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
    magnet = template.get("magnet", template.get("magnet_shrines", 0))
    bald_heads = template.get("bald_heads", 0)

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
    if magnet > 0:
        parts.append(f"Mag:{magnet}")
    if bald_heads > 0:
        parts.append(f"BH:{bald_heads}")

    return ", ".join(parts) if parts else "Any"

def build_template_payload(
    name: str,
    sm_total: str,
    shady: str,
    moai: str,
    micro: str,
    boss: str,
    bald_heads: str = "",
    magnet: str = "",
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
        "bald_heads": parse_int(bald_heads),
        "magnet": parse_int(magnet),
    }

    if result["sm_total"] <= 0 or result["shady"] > 0 or result["moai"] > 0:
        result.pop("sm_total", None)

    if source_template:
        for key, value in source_template.items():
            if key not in result and key not in ["sm_total", "shady", "moai", "micro", "boss", "bald_heads", "magnet", "magnet_shrines"]:
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.owner._handle_window_shown()


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0

        for item in self.itemList:
            wid = item.widget()
            spaceX = self.spacing()
            spaceY = self.spacing()
            if wid:
                spaceX = self.spacing() if self.spacing() != -1 else wid.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal)
                spaceY = self.spacing() if self.spacing() != -1 else wid.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical)

            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        height = y + lineHeight - rect.y()
        if not testOnly and self.parentWidget():
            self.parentWidget().setMinimumHeight(height)

        return height

class TrackedRuleTagWidget(QFrame):
    remove_clicked = Signal(str)

    def __init__(
        self,
        rule_id: str,
        label_text: str,
        parent=None,
        *,
        text_color: str = "#E2E8F0",
        border_color: str = "#4B4B5A",
        background_color: str = "#2D2D35",
    ):
        super().__init__(parent)
        self.rule_id = rule_id
        self.setObjectName("TrackedRuleTag")

        self.setStyleSheet(f"""
            QFrame#TrackedRuleTag {{
                background-color: {background_color};
                border: 1px solid {border_color};
                border-radius: 4px;
            }}
            QLabel {{
                color: {text_color};
                font-weight: bold;
                font-size: 11px;
                padding-left: 6px;
                padding-right: 2px;
                padding-top: 4px;
                padding-bottom: 4px;
            }}
            QPushButton#TagCloseBtn {{
                color: #A0AEC0;
                background: transparent;
                border: none;
                font-weight: bold;
                font-size: 11px;
                padding-left: 4px;
                padding-right: 6px;
                padding-top: 4px;
                padding-bottom: 4px;
            }}
            QPushButton#TagCloseBtn:hover {{
                color: #F87171;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        lbl = QLabel(label_text)
        layout.addWidget(lbl)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("TagCloseBtn")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.remove_clicked.emit(self.rule_id))
        layout.addWidget(close_btn)
