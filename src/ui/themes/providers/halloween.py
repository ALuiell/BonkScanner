"""Halloween entry point. Scene implementation lives in halloween_effects/."""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImageReader
from PySide6.QtSvg import QSvgRenderer

from ui.themes.contracts import AppearanceProvider, SupportContext
from ui.themes.lifecycle import ThemeResources
from ui.themes.providers.halloween_effects.animation import WebPulseFrames
from ui.themes.providers.halloween_effects.decorations import ThemeDecorations
from ui.themes.providers.halloween_effects.support import SpiderSupport


class WebFooterIcon:
    """Footer sees attach/paint/pulse, never the shared Halloween clock."""
    def __init__(self, clock, package):
        self.clock = clock
        self.slot_width = package.parameter("footer_icon_slot")
        self.height = package.parameter("footer_link_height")
        self.scale = package.parameter("footer_icon_scale")
        self.frames = WebPulseFrames(color=package.color)
        self._binding = None
        self.disposed = False

    def attach(self, surface, request_update):
        self.detach()
        if self.disposed:
            raise RuntimeError("Cannot attach a disposed footer icon")
        self._binding = ThemeResources()
        with self._binding as binding:
            self.clock.add_surface(surface)
            binding.callback(self.clock.remove_surface, surface)
            binding.connect(self.clock.phaseChanged, lambda _phase: request_update())
        self.refresh()

    def detach(self):
        if self._binding is not None:
            self._binding.close()
            self._binding = None

    def refresh(self):
        if not self.disposed:
            self.clock.refresh()

    def pulse(self):
        if not self.disposed:
            self.clock.restart()

    def paint(self, painter, start, center_y, density):
        frame = self.frames.frame(density, self.scale, self.clock.phase)
        painter.drawPixmap(QPointF(start + self.slot_width / 2 - 22, center_y - 19), frame)

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        self.detach()
        self.frames.frames.clear()


class HalloweenProvider(AppearanceProvider):
    def __init__(self, host, package):
        super().__init__(host, package)
        self.presentations = []

    def validate_host(self):
        for name in ("header", "logo", "premium_badge", "corner_tabs", "templates", "log_view"):
            if getattr(self.host, name) is None:
                raise ValueError(f"Missing appearance host capability: {name}")
        for item in self.package.preset["assets"].values():
            if not item.get("required", True):
                continue
            path = self.package.root / item["path"]
            valid = (QSvgRenderer(str(path)).isValid() if path.suffix == ".svg"
                     else QImageReader(str(path)).canRead())
            if not valid:
                raise ValueError("Invalid required Halloween image")

    def prepare(self):
        with self.resources:
            self.decorations = self.resources.own(ThemeDecorations(self.host, package=self.package))
            self.footer_icon = self.resources.own(WebFooterIcon(self.decorations.animation, self.package))
            self.footer_height = self.package.parameter("footer_height")

    def activate(self):
        self.decorations.set_enabled(True)

    def create_support(self, context: SupportContext):
        if self.disposed:
            raise RuntimeError("Cannot create a presentation for a disposed appearance")
        presentation = self.resources.own(SpiderSupport(
            package=self.package, host=context.host, footer=context.footer,
            activate=context.activate, dismiss=context.dismiss, finished=context.finished,
        ))
        self.presentations.append(presentation)
        return presentation

    def dispose(self):
        super().dispose()
        self.presentations.clear()
