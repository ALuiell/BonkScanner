"""Self-contained example widgets for the Quick Guides prototype.

All values are illustrative; these widgets never connect to a game or account.
"""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .guide_locale import bind, game, message, ui
from ui.shared import resource_path
from ui import i18n as l10n

_MEDIA = Path(resource_path("media"))
_SWITCH_STYLE = """
QPushButton {color:#aabdd0; background:#1b2b3d; border:1px solid #344a60; border-radius:7px; padding:6px;}
QPushButton:checked {color:#eaffff; background:#23565d; border-color:#5cc6ca;}
QPushButton:focus {border-color:#89dee0;}
"""


def _label(text, color="#e7edf5", size=12, bold=False):
    label = QLabel()
    label.setStyleSheet(f"color:{color}; font-size:{size}px; font-weight:{'700' if bold else '400'}; background:transparent; border:0;")
    label.setWordWrap(True)
    if callable(text):
        return bind(label, text)
    label.setText(text)
    return label


def _panel():
    panel = QFrame()
    panel.setObjectName("guidePreviewPanel")
    panel.setStyleSheet("QFrame#guidePreviewPanel { background:#111b29; border:1px solid #2b3c50; border-radius:12px; }")
    return panel


def _heading(layout, title):
    row = QHBoxLayout()
    row.addWidget(_label(title, "#f1f6fb", 13, True))
    row.addStretch()
    row.addWidget(_label(lambda: message("guide.preview"), "#a6bbce", 11, True))
    layout.addLayout(row)


class _MinimapPreview(QWidget):
    """An illustrative game scene using the same screenshot and marker assets."""
    def __init__(self):
        super().__init__()
        self.show_markers = True
        self.scene = QPixmap(str(_MEDIA / "overlay" / "game_preview.jpg"))
        self.markers = [QPixmap(str(_MEDIA / "map_markers" / "pictograms" / "filled" / f)) for f in (
            "microwave_purple.png", "shady_guy_gold.png", "magnet_shrine.png")]
        self.setMinimumSize(220, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        l10n.RefreshBinding(self, self.update)

    def set_markers_visible(self, visible):
        self.show_markers = visible
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(bounds, 11, 11)
        p.setClipPath(clip)
        p.fillRect(bounds, QColor("#15232b"))
        if not self.scene.isNull():
            src = QRectF(self.scene.rect())
            src.adjust(src.width() * .07, src.height() * .17, -src.width() * .20, -src.height() * .10)
            aspect = bounds.width() / max(1, bounds.height())
            if src.width() / src.height() > aspect:
                inset = (src.width() - src.height() * aspect) / 2
                src.adjust(inset, 0, -inset, 0)
            else:
                inset = (src.height() - src.width() / aspect) / 2
                src.adjust(0, inset, 0, -inset)
            p.drawPixmap(bounds, self.scene, src)
        p.fillRect(bounds, QColor(3, 10, 17, 85))
        w, h = bounds.width(), bounds.height()
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.setPen(QColor("#d3e5ef"))
        p.drawText(QRectF(14, 10, w - 28, 20), Qt.AlignLeft | Qt.AlignVCenter, message("demo.game"))
        side = min(h - 40, w * .46, 204)
        cx, cy = w*.72, h*.56
        rect = QRectF(cx-side/2, cy-side/2, side, side)
        p.setPen(QPen(QColor("#b0a899"), 3))
        p.setBrush(QColor(11, 19, 33, 232))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor(94, 126, 139, 100), 1))
        p.drawLine(int(cx-side*.4), int(cy), int(cx+side*.4), int(cy))
        p.drawLine(int(cx), int(cy-side*.4), int(cx), int(cy+side*.4))
        p.setBrush(QColor("#54c8f2"))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(cx, cy - 10), QPointF(cx - 7, cy + 8), QPointF(cx, cy + 4), QPointF(cx + 7, cy + 8)]))
        if self.show_markers:
            for pix, dx, dy in zip(self.markers, (-.27, .20, .16), (-.18, -.22, .24)):
                if not pix.isNull():
                    target = QRectF(cx + side * dx - 13, cy + side * dy - 13, 26, 26)
                    p.drawPixmap(target, pix, QRectF(pix.rect()))
        self._box(p, QRectF(14, h-87, min(158,w*.43), 68))
        self._text(p, 25, h-65, ui("Map markers"), "#75dce2", 8)
        status = message("demo.markers_on" if self.show_markers else "demo.markers_off")
        self._text(p, 25, h - 44, status, "#ffffff", 10)
        p.end()

    @staticmethod
    def _box(p, rect):
        p.setPen(QPen(QColor(171, 211, 220, 65), 1))
        p.setBrush(QColor(7, 15, 23, 215))
        p.drawRoundedRect(rect, 7, 7)

    @staticmethod
    def _text(p, x, y, text, color, size):
        p.setFont(QFont("Segoe UI", size, QFont.Bold))
        p.setPen(QColor(color)); p.drawText(int(x), int(y), text)


def _access():
    rows = (
        ("1", lambda: "Patreon / " + ui("Crypto")),
        ("2", lambda: message("demo.access_key")),
        ("3", lambda: " → ".join(ui(name) for name in ("Settings", "Support", "Activate"))),
    )
    panel = _panel(); layout = QVBoxLayout(panel)
    layout.setContentsMargins(18, 16, 18, 16); layout.setSpacing(9)
    _heading(layout, lambda: message("topic.access.menu"))
    for icon, text in rows:
        row = QFrame(); row.setStyleSheet("QFrame {background:#182839; border:1px solid #2b4055; border-radius:8px;}")
        rl = QHBoxLayout(row); rl.setContentsMargins(10, 7, 10, 7)
        rl.addWidget(_label(icon, "#75d8d8", 12, True)); rl.addSpacing(8)
        rl.addWidget(_label(text, "#dbe7f2", 12), 1)
        layout.addWidget(row)
    layout.addStretch(1)
    return panel



def _restart():
    panel = _panel()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(8)
    def game_path():
        return " → ".join(("Megabonk", game("Main Menu", "MENU_BUTTON_SETTINGS"), game("SettingsHeaders", "GAME")))

    layout.addWidget(_label(game_path, "#8ccaff", 13, True))
    for setting in ("quick_reset", "skip_portal_animation", "super_quick_resets"):
        item = QFrame()
        item.setObjectName("GuideResetOption")
        item.setStyleSheet("QFrame#GuideResetOption {background:#182839; border:1px solid #2b4055; border-radius:6px;}")
        row = QHBoxLayout(item)
        row.setContentsMargins(10, 5, 10, 5)
        row.addWidget(_label(lambda key=setting: game("SettingsGame", key), size=13), 1)
        row.addWidget(_label(lambda: message("restart.enabled"), "#84ddb6", 12, True))
        layout.addWidget(item)

    layout.addSpacing(5)
    layout.addWidget(_label(lambda: message("restart.fast_title"), "#8ccaff", 13, True))
    layout.addWidget(_label(lambda: message(
        "restart.use", path=f"{ui('Settings')} → {ui('Restart')}", button=ui("Use recommended values…"),
    ), "#dbe7f2", 13))
    layout.addWidget(_label(lambda: message("restart.close_game"), "#a5b7ca"))
    layout.addStretch(1)
    return panel


def build_preview(topic: str) -> QWidget:
    """Return a standalone, width-responsive preview for a guide topic."""
    topic = str(topic).lower()
    if topic == "minimap":
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        view = _MinimapPreview()
        layout.addWidget(view, 1)
        button = bind(QPushButton(), lambda: message("demo.show_markers"))
        button.setCheckable(True)
        button.setChecked(True)
        button.setAutoDefault(False)
        button.setStyleSheet(_SWITCH_STYLE)
        button.toggled.connect(view.set_markers_visible)
        layout.addWidget(button, 0, Qt.AlignLeft)
        return panel
    if topic == "restart":
        return _restart()
    if topic == "access":
        return _access()
    raise ValueError(f"Unknown guide preview: {topic}")
