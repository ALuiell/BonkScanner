"""Halloween Support art; bounded paints and a monotonic, pausable timeline."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from ui.themes.lifecycle import ThemeResources


CLIMB_SECONDS = 5.05
READ_SECONDS = 8.0
EXIT_SECONDS = .45
TOTAL_SECONDS = CLIMB_SECONDS + READ_SECONDS + EXIT_SECONDS


def polygon(points):
    result = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        result.lineTo(*point)
    result.closeSubpath()
    return result

def draw_web_icon(p, x, y, t, *, color=None):
    color = color or QColor
    p.save()
    p.translate(x, y)
    u = max(0.0, min(1.0, t / 1.15))
    active = 0 <= t < 1.15
    wave = 2 + 16 * u
    fade = math.sin(math.pi * u) ** .6 if active else 0
    p.setPen(Qt.NoPen)
    halo = QRadialGradient(0, 0, 21)
    halo.setColorAt(0, color(151, 92, 232, round(24 * fade)))
    halo.setColorAt(.75, color(151, 92, 232, round(8 * fade)))
    halo.setColorAt(1, color(151, 92, 232, 0))
    p.setBrush(halo)
    p.drawEllipse(QRectF(-21,-21,42,42))
    radius = 15
    for i in range(8):
        angle = i * math.pi / 4
        gradient = QLinearGradient(0, 0, radius * math.cos(angle), radius * math.sin(angle))
        gradient.setColorAt(0, color('#8768b1'))
        gradient.setColorAt(1, color('#8768b1'))
        if active:
            band = min(.98, wave / radius)
            gradient.setColorAt(max(.001, band-.20), color('#8768b1'))
            gradient.setColorAt(band, color(218, 182, 255, round(180 + 75*fade)))
            gradient.setColorAt(min(.999, band+.20), color('#8768b1'))
        p.setPen(QPen(gradient, 1.15, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(0,0), QPointF(radius*math.cos(angle),radius*math.sin(angle)))
    for r in (4.5, 9.5, 15):
        light = math.exp(-((r-wave)/2.5)**2) * fade
        points = [(r*math.cos(i*math.pi/4), r*math.sin(i*math.pi/4)) for i in range(8)]
        ring = polygon(points)
        p.setBrush(Qt.NoBrush)
        if light > .01:
            p.setPen(QPen(color(168,107,255,round(55*light)), 3.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(ring)
        p.setPen(QPen(color(round(135+103*light),round(104+95*light),round(177+78*light)),
                      1.05 + .25*light, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(ring)
    p.setBrush(color(221,181,255,round(140+100*fade)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(0,0), 1.6, 1.6)
    p.restore()


class _SpiderArt(QWidget):
    def __init__(self, controller):
        super().__init__(controller.host)
        with ThemeResources() as rollback:
            rollback.callback(self.deleteLater)
            rollback.callback(self.hide)
            self.controller = controller
            self.setObjectName("supportSpiderArt")
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.setAttribute(Qt.WA_NoSystemBackground)
            self.setStyleSheet("background:transparent;border:none;")
            self.renderer = QSvgRenderer(controller.package.asset("support-spider"), self)
            self.asset_name = "support-spider.svg"
            self.raster = QPixmap()
            self.raster_density = None
            self.hide()

    def set_thank_you(self, thank_you):
        asset = "support-spider-thank-you.svg" if thank_you else "support-spider.svg"
        if asset == self.asset_name:
            return
        if not self.renderer.load(self.controller.package.asset(asset.removesuffix(".svg"))):
            asset = "support-spider.svg"
            self.renderer.load(self.controller.package.asset(asset.removesuffix(".svg")))
        self.asset_name = asset
        # Replace the single cached face only on an expression/DPI change.
        self.raster_density = None
        self.raster = QPixmap()

    def _draw_gripping_legs(self, painter):
        c = self.controller
        climb = c.elapsed - c.thread_seconds
        if 0 <= climb < c.climb_seconds:
            phase = math.sin(climb * (2 * math.pi / 1.36))
            blend = min(1.0, climb / .3, (c.climb_seconds - climb) / .4)
            left_grip = .6 + (phase - .6) * blend
            right_grip = -.3 + (-phase + .3) * blend
        else:
            left_grip, right_grip = .6, -.3

        gradient = QLinearGradient(0, 0, 320, 280)
        gradient.setColorAt(0, QColor("#73504b"))
        gradient.setColorAt(.35, QColor("#332939"))
        gradient.setColorAt(1, QColor("#180a28"))
        for left, grip in ((True, left_grip), (False, right_grip)):
            sx, elbow_x = (96, 54) if left else (224, 266)
            tip_x = 154 if left else 166
            tip_y = 4 + grip * 14
            leg = QPainterPath(QPointF(sx, 133))
            leg.lineTo(elbow_x, 79 - grip * 14 * .48)
            leg.lineTo(101 if left else 219, 28 + grip * 3)
            leg.lineTo(tip_x, tip_y)
            painter.setPen(QPen(QColor("#080609"), 22, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(leg)
            painter.setPen(QPen(gradient, 14, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(leg)
            painter.setPen(QPen(QColor("#ec8844"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(leg)
            claw = QPainterPath(QPointF(tip_x + (-4 if left else 4), tip_y - 6))
            claw.lineTo(160, tip_y + 3)
            claw.lineTo(tip_x + (-2 if left else 2), tip_y + 12)
            painter.setPen(QPen(QColor("#1d1124"), 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(claw)

    def paintEvent(self, _event):  # noqa: N802
        c = self.controller
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x, y = c.x - self.x(), c.y
        p.setPen(QPen(c.package.color("#b7a2c9"), 1.2))
        if c.elapsed < c.thread_seconds:
            bottom = self.height() + 10
            progress = min(1.0, c.elapsed / (c.thread_seconds * .55 / .65))
            end = bottom - (bottom - 3) * (1 - (1 - progress) ** 3)
            p.drawLine(QPointF(x, bottom), QPointF(x, end))
        else:
            p.drawLine(QPointF(x, 0), QPointF(x, y))
            p.setPen(QPen(c.package.color("#63536e"), 1))
            p.drawLine(QPointF(x - 6, 0), QPointF(x + 5, 9))
            p.drawLine(QPointF(x + 7, 0), QPointF(x - 5, 9))
            density = self.devicePixelRatioF() * 2
            if density != self.raster_density:
                self.raster = QPixmap(round(180 * density), round(157.5 * density))
                self.raster.setDevicePixelRatio(density)
                self.raster.fill(Qt.transparent)
                cache = QPainter(self.raster)
                self.renderer.render(cache, QRectF(0, 0, 180, 157.5))
                cache.end()
                self.raster_density = density
            p.save()
            p.translate(x, y)
            p.rotate(.65 * math.sin(c.elapsed * 1.7))
            p.save()
            p.translate(-90, -85)
            p.scale(.5625, .5625)
            self._draw_gripping_legs(p)
            p.restore()
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(QRectF(-90, -85, 180, 157.5), self.raster, QRectF(self.raster.rect()))
            p.restore()
            p.setPen(QPen(c.package.color("#b99bcc"), 1.1))
            p.drawLine(QPointF(x - 49, y + 65), QPointF(x - 111, y + 70))
            p.drawLine(QPointF(x + 49, y + 65), QPointF(x + 111, y + 70))
        p.end()


class _SpiderPlaque(QWidget):
    def __init__(self, controller):
        super().__init__(controller.host)
        with ThemeResources() as rollback:
            rollback.callback(self.deleteLater)
            rollback.callback(self.hide)
            self.controller = controller
            self.setObjectName("supportSpiderPlaque")
            self.setAttribute(Qt.WA_NoSystemBackground)
            self.setStyleSheet("background:transparent;border:none;")
            self.resize(296, 124)
            self.raster = QPixmap()
            self.raster_key = None
            self.action = QPushButton("Support", self)
            self.action.setCursor(Qt.PointingHandCursor)
            self.action.setFocusPolicy(Qt.NoFocus)
            self.action.setGeometry(178, 66, 100, 42)
            self.action.clicked.connect(controller.activate)
            from ui.themes import remap_colors
            colors = controller.package.preset.get("effect_color_map", {})
            self.action.setStyleSheet(remap_colors(
                "QPushButton {background:#8252b0;color:#fff0d9;border:1px solid #b58ace;"
                "border-radius:8px;font-weight:600;padding:0;min-height:0;min-width:0}"
                "QPushButton:hover {background:#ab78c6}", colors
            ))
            self.close_button = QPushButton("×", self)
            self.close_button.setGeometry(263, 8, 26, 26)
            self.close_button.setAccessibleName("Dismiss Support message")
            self.close_button.setToolTip("Close")
            self.close_button.setFocusPolicy(Qt.NoFocus)
            self.close_button.clicked.connect(controller.dismiss)
            self.close_button.setStyleSheet(remap_colors(
                "QPushButton {background:transparent;border:0;color:#aa94b9;padding:0;"
                "min-height:0;min-width:0;font-size:18px} QPushButton:hover {color:white}", colors
            ))
            self.hide()

    def _paint_static(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        gradient = QLinearGradient(0, 0, 0, 124)
        gradient.setColorAt(0, self.controller.package.color("#302035"))
        gradient.setColorAt(1, self.controller.package.color("#1b1425"))
        p.setBrush(gradient)
        p.setPen(QPen(self.controller.package.color("#8861ac"), 1.2))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, 122), 15, 15)
        thanks = self.controller.thank_you
        for text, rect, size, weight, color in (
            ("Thank you for your support!" if thanks else "Support BonkScanner",
             QRectF(15, 12, self.width() - 51, 26), 10, QFont.Bold, "#e4caff"),
            ("You help make every update possible." if thanks else "Keep the updates coming.",
             QRectF(15, 40, self.width() - 30, 24), 9, QFont.Normal, "#c3b5ce"),
            ("Enjoy your Premium features." if thanks else "Thank you for your support!",
             QRectF(15, 77, self.width() - 30 if thanks else 156, 22), 8, QFont.Normal, "#aa83cf"),
        ):
            p.setFont(QFont("Segoe UI", size, weight))
            p.setPen(self.controller.package.color(color))
            p.drawText(rect, Qt.AlignVCenter, text)

    def _ensure_raster(self):
        # Glyph hinting at a new fractional Y on every frame makes the text
        # shimmer. Rasterize the stationary card once at 2x display density.
        density = self.devicePixelRatioF() * 2
        key = (self.width(), self.height(), self.controller.thank_you, density)
        if key != self.raster_key:
            self.raster = QPixmap(max(1, round(self.width() * density)),
                                  max(1, round(self.height() * density)))
            self.raster.setDevicePixelRatio(density)
            self.raster.fill(Qt.transparent)
            cache = QPainter(self.raster)
            self._paint_static(cache)
            cache.end()
            self.raster_key = key

    def paintEvent(self, _event):  # noqa: N802
        self._ensure_raster()
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(QRectF(0, self.controller.plaque_offset, self.width(), self.height()),
                     self.raster, QRectF(self.raster.rect()))
        p.end()


class SpiderSupport(QObject):
    """Presentation only: the footer still owns eligibility and cooldowns."""

    def __init__(self, *, host, footer, activate, dismiss, finished, package=None):
        super().__init__(host)
        self.resources = ThemeResources()
        with self.resources as resources:
            resources.callback(self._abort_construction)
            if package is None:
                from ui.themes.package import read_package
                package = read_package("halloween")
            self.package = package
            self.disposed = False
            self.thread_seconds = package.parameter("support_thread_seconds")
            self.climb_seconds = package.parameter("support_climb_seconds")
            self.read_seconds = package.parameter("support_read_seconds")
            self.exit_seconds = package.parameter("support_exit_seconds")
            self.settle_seconds = self.thread_seconds + self.climb_seconds
            self.total_seconds = self.settle_seconds + self.read_seconds + self.exit_seconds
            self.host = host
            self.footer = footer
            self.activate = activate
            self.dismiss = dismiss
            self.finished = finished
            self.elapsed = 0.0
            self.x = self.y = self.plaque_offset = 0.0
            self.thank_you = False
            self.running = False
            self._paused = False
            self._last = 0.0
            self.art = resources.own(_SpiderArt(self))
            self.plaque = resources.own(_SpiderPlaque(self))
            self.timer = resources.own(QTimer(self))
            self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.setInterval(16)
            resources.connect(self.timer.timeout, self._tick)
            resources.event_filter(host, self)
            self.window = host.window()
            if self.window is not host:
                resources.event_filter(self.window, self)
            app = QApplication.instance()
            if app is not None:
                resources.connect(app.applicationStateChanged, self._application_state_changed)

    def _abort_construction(self):
        self.disposed = True
        self.running = False
        self.deleteLater()

    def start(self, *, thank_you=False):
        if self.disposed:
            return
        self.thank_you = thank_you
        self.art.set_thank_you(thank_you)
        self.plaque.action.setVisible(not thank_you)
        self.plaque.setAccessibleName("Thank you for your support" if thank_you else "Support BonkScanner")
        self.running = True
        self.elapsed = 0.0
        self._last = time.monotonic()
        # Corner artwork stays cached inside Logs; these root overlays cover
        # only the pixels occupied by the moving spider and opaque plaque.
        self._render()
        self.plaque._ensure_raster()
        self.art.show()
        self.art.raise_()
        self.plaque.raise_()
        self._paused = False
        self.timer.start()
        self._application_state_changed(QApplication.instance().applicationState())

    def stop(self):
        self.timer.stop()
        self.running = False
        self.art.hide()
        self.plaque.hide()

    def dispose(self):
        if self.disposed:
            return
        self.stop()
        self.disposed = True
        self.art.raster = QPixmap()
        self.plaque.raster = QPixmap()
        self.resources.close()

    def _tick(self):
        now = time.monotonic()
        self.elapsed += max(0.0, now - self._last)
        self._last = now
        if self.elapsed >= self.total_seconds:
            self.stop()
            self.finished()
            return
        self._render()

    def _render(self):
        old_y, old_x = self.y, self.x
        w, h = self.host.width(), self.host.height()
        self.art.setGeometry(max(0, w - 340), 0, min(340, w), h)
        width = min(296, max(100, w - 34))
        self.plaque.resize(width, 124)
        self.plaque.close_button.move(width - 33, 8)
        self.plaque.action.move(width - 118, 66)
        plaque_x = w - 17 - width
        self.x = plaque_x + width / 2
        footer_top = self.footer.mapTo(self.host, QPoint(0, 0)).y()
        target = footer_top - 124 - 18 - 70
        u = max(0.0, min(1.0, (self.elapsed - self.thread_seconds) / self.climb_seconds))
        u = u ** 3 * (u * (u * 6 - 15) + 10)
        self.y = h + 70 - (h + 70 - target) * u
        if self.elapsed > self.settle_seconds + self.read_seconds:
            exit_u = min(1.0, (self.elapsed - self.settle_seconds - self.read_seconds) / self.exit_seconds)
            self.y += (h + 70 - target) * exit_u ** 3
        plaque_y = self.y + 70
        self.plaque_offset = plaque_y - math.floor(plaque_y)
        self.plaque.move(round(plaque_x), math.floor(plaque_y))
        self.plaque.setVisible(self.running and self.elapsed > self.thread_seconds)
        if self.elapsed < self.thread_seconds + .05 or old_x != self.x:
            self.art.update()
        else:
            # The anchored thread is unchanged; update only the moving sprite.
            top = math.floor(min(old_y, self.y) - 94)
            bottom = math.ceil(max(old_y, self.y) + 92)
            self.art.update(QRect(round(self.x - self.art.x() - 119), top, 238, bottom - top))
        if old_y != self.y:
            self.plaque.update()

    def _application_state_changed(self, state):
        if self.disposed:
            return
        self.set_paused(state != Qt.ApplicationActive or self.window.isMinimized() or not self.window.isVisible())

    def set_paused(self, paused):
        if not self.running or self._paused == paused:
            return
        self._paused = paused
        if paused:
            self.timer.stop()
        else:
            self._last = time.monotonic()
            self.timer.start()

    def eventFilter(self, watched, event):  # noqa: N802
        if self.running:
            if watched is self.window and event.type() in (QEvent.Hide, QEvent.Show, QEvent.WindowStateChange):
                app = QApplication.instance()
                self.set_paused(not self.window.isVisible() or self.window.isMinimized()
                                or app.applicationState() != Qt.ApplicationActive)
            if event.type() in (QEvent.Resize, QEvent.LayoutRequest):
                self._render()
        return False
