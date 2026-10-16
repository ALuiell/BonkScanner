"""One window-owned burst clock and bounded raster caches for Halloween."""
import math
import time

from PySide6.QtCore import QObject, QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from ui.themes.lifecycle import ThemeResources

BURST_SECONDS = 1.17
PAUSE_MS = 4500
FRAME_MS = 33
BURSTS = ((0.0, .50, 1.0), (.68, .44, .85))
FRAME_PHASES = (-1.0, *(i / 30 for i in range(36)))


def flare_level(phase):
    level = 0.0
    for start, duration, strength in BURSTS:
        u = (phase - start) / duration
        if 0 <= u <= 1:
            level = max(level, strength * math.sin(math.pi * u) ** 2)
    return level


def web_phase(phase):
    for start, duration, strength in BURSTS:
        u = (phase - start) / duration
        if 0 <= u < 1:
            return u * 1.15, strength
    return 2.0, 0.0


def frame_index(phase):
    return 0 if phase < 0 else min(36, 1 + round(phase * 30))


class HalloweenAnimation(QObject):
    """Tick only during bursts; all consumers receive the same elapsed phase."""
    phaseChanged = Signal(float)

    def __init__(self, window, *, package=None):
        super().__init__(window)
        self.window = window
        self.enabled = False
        self.phase = -1.0
        self.started = 0.0
        self.surfaces = []
        self._refreshing = False
        self._closing = False
        self.disposed = False
        self.resources = ThemeResources()
        with self.resources as resources:
            resources.callback(self._abort_construction)
            self.pause_ms = package.parameter("pulse_pause_ms") if package else PAUSE_MS
            self.timer = resources.own(QTimer(self))
            self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.setInterval(package.parameter("pulse_frame_ms") if package else FRAME_MS)
            resources.connect(self.timer.timeout, self.tick)
            self.wake = resources.own(QTimer(self))
            self.wake.setSingleShot(True)
            resources.connect(self.wake.timeout, self.restart)
            resources.event_filter(window, self)
            resources.connect(QApplication.instance().applicationStateChanged, self.refresh)

    def _abort_construction(self):
        self.enabled = False
        self.disposed = True
        self.deleteLater()

    def add_surface(self, widget):
        if widget not in self.surfaces:
            self.surfaces.append(widget)
            widget.installEventFilter(self)

    def remove_surface(self, widget):
        if widget in self.surfaces:
            self.surfaces.remove(widget)
            widget.removeEventFilter(self)

    def dispose(self):
        if self.disposed:
            return
        self.enabled = False
        self.disposed = True
        for surface in tuple(self.surfaces):
            self.remove_surface(surface)
        self.resources.close()

    def ready(self):
        return (self.enabled and not self.disposed and not self._closing and self.window.isVisible() and not self.window.isMinimized()
                and QApplication.instance().applicationState() == Qt.ApplicationActive
                and any(surface.isVisible() for surface in self.surfaces))

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.refresh()

    def show_phase(self, phase):
        if self.phase != phase:
            self.phase = phase
            self.phaseChanged.emit(phase)

    def restart(self):
        if not self.ready():
            self.refresh()
            return
        self.wake.stop()
        self.started = time.monotonic()
        self.show_phase(0.0)
        self.timer.start()

    def tick(self):
        if not self.ready():
            self.refresh()
            return
        phase = time.monotonic() - self.started
        if phase >= BURST_SECONDS:
            self.timer.stop()
            self.show_phase(-1.0)
            self.wake.start(self.pause_ms)
        else:
            self.show_phase(phase)

    def refresh(self, *_args):
        if self.disposed or self._refreshing or QApplication.closingDown():
            return
        self._refreshing = True
        try:
            if not self.ready():
                self.timer.stop()
                self.wake.stop()
                self.show_phase(-1.0)
            elif not self.timer.isActive() and not self.wake.isActive():
                self.restart()
        finally:
            self._refreshing = False

    def _after_close(self):
        # A cancelled window-close request keeps the visible app animating.
        self._closing = False
        self.refresh()

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.window and event.type() == QEvent.Close:
            self._closing = True
            self.refresh()
            QTimer.singleShot(0, self, self._after_close)
        elif event.type() in (QEvent.Show, QEvent.Hide, QEvent.WindowStateChange):
            self.refresh()
        return False


class WebPulseFrames:
    """Replace the current DPI cache; never accumulate sizes or animation cycles."""
    def __init__(self, *, color=None):
        self.color = color
        self.key = None
        self.frames = []
        self.builds = 0

    def frame(self, density, scale, phase):
        from ui.themes.providers.halloween_effects.support import draw_web_icon

        key = (density, scale)
        if key != self.key:
            self.key = key
            self.builds += 1
            self.frames = []
            for sample in FRAME_PHASES:
                raster = QPixmap(max(1, round(40 * density)), max(1, round(40 * density)))
                raster.setDevicePixelRatio(density)
                raster.fill(Qt.transparent)
                painter = QPainter(raster)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.translate(20, 20)
                painter.scale(scale, scale)
                t, strength = web_phase(sample)
                draw_web_icon(painter, 0, 0, 2.0, color=self.color)
                if strength:
                    painter.setOpacity(strength)
                    draw_web_icon(painter, 0, 0, t, color=self.color)
                painter.end()
                self.frames.append(raster)
        return self.frames[frame_index(phase)]
