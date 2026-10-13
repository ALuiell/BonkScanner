"""Halloween's entire visual integration, independent of selection/access policy."""
from PySide6.QtCore import QPointF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QTextEdit

from ui.themes.animation import WebPulseFrames
from ui.themes.decorations import ThemeDecorations
from ui.themes.runtime import AppearanceProvider
from ui.themes.support import SpiderSupport


class WebFooterIcon:
    def __init__(self, clock, package):
        self.clock = clock
        self.slot_width = package.parameter("footer_icon_slot")
        self.height = package.parameter("footer_link_height")
        self.scale = package.parameter("footer_icon_scale")
        self.frames = WebPulseFrames(color=package.color)

    def paint(self, painter, start, center_y, density):
        frame = self.frames.frame(density, self.scale, self.clock.phase)
        painter.drawPixmap(QPointF(start + self.slot_width / 2 - 22, center_y - 19), frame)


class HalloweenProvider(AppearanceProvider):
    def __init__(self, owner, package):
        super().__init__(owner, package)
        # Validate before allocating UI so a malformed required SVG falls back cleanly.
        for item in package.preset["assets"].values():
            if item.get("required", True) and not QSvgRenderer(str(package.root / item["path"])).isValid():
                raise ValueError("Invalid required Halloween SVG")
        if (owner.window.findChild(QFrame, "headerBar") is None
                or owner.log_box.findChild(QTextEdit) is None):
            raise ValueError("Required desktop appearance anchors are unavailable")
        # Resolve all required anchors before allocating clocks or artwork.
        for name in ("logo_label", "premium_access_badge", "tabview", "left_tabview", "rec_flag", "_templates_panel"):
            if getattr(owner, name, None) is None:
                raise ValueError(f"Missing desktop appearance anchor: {name}")
        self.decorations = ThemeDecorations(owner, package=package)
        self.footer_icon = WebFooterIcon(self.decorations.animation, package)
        self.footer_height = package.parameter("footer_height")
        self.presentations = []

    def activate(self):
        self.decorations.set_enabled(True)

    def create_support(self, **callbacks):
        presentation = SpiderSupport(package=self.package, **callbacks)
        self.presentations.append(presentation)
        return presentation

    def dispose(self):
        for presentation in self.presentations:
            presentation.dispose()
        self.presentations.clear()
        self.decorations.dispose()
        self.footer_icon.frames.frames.clear()
