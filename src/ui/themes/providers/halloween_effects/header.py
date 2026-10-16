"""Cached purple pumpkin flames and local reflected light from the selected mockup."""
from contextlib import ExitStack
import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QRegion, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from ui.themes.providers.halloween_effects.animation import FRAME_PHASES, flare_level, frame_index
from ui.themes.providers.halloween_effects.decorations import _SvgDecoration

ICON_RECT = QRect(43, 0, 42, 42)

class PumpkinArt:
    def __init__(self, svg, *, violet, color=None):
        self.color = color or QColor
        self.violet = violet
        self.renderer = QSvgRenderer(svg)
        self.raster = QPixmap()
        self.key = None

    def sprite(self, p, bounds):
        transform = p.worldTransform()
        scale = max(1.0, math.hypot(transform.m11(), transform.m12()),
                    math.hypot(transform.m21(), transform.m22()))
        density = p.device().devicePixelRatioF() * 2 * scale
        key = (bounds.width(), bounds.height(), density)
        if self.key != key:
            self.raster = QPixmap(round(bounds.width() * density), round(bounds.height() * density))
            self.raster.setDevicePixelRatio(density)
            self.raster.fill(Qt.transparent)
            cache = QPainter(self.raster)
            self.renderer.render(cache, QRectF(0, 0, bounds.width(), bounds.height()))
            cache.end()
            self.key = key
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(bounds, self.raster, QRectF(self.raster.rect()))

def _draw_eyes(p, x, y, t, art):
    beat = flare_level(t)
    p.save()
    p.translate(x, y)
    glow = QRadialGradient(0, 1, 22)
    glow.setColorAt(0, art.color(128, 88, 186, round(10 + 45 * beat)) if art.violet
                       else art.color(255, 145, 16, round(12 + 68 * beat)))
    glow.setColorAt(.65, art.color(128, 88, 186, round(4 + 16 * beat)) if art.violet
                         else art.color(255, 105, 0, round(5 + 22 * beat)))
    glow.setColorAt(1, art.color(128, 88, 186, 0) if art.violet else art.color(255, 105, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QRectF(-22, -21, 44, 44))
    art.sprite(p, QRectF(-16, -21, 32, 36))
    p.translate(-16, -21)
    p.scale(.2, .2)
    left = QPainterPath(QPointF(36, 82))
    left.quadTo(51, 85, 69, 96)
    left.lineTo(62, 111)
    left.quadTo(46, 112, 39, 102)
    left.closeSubpath()
    right = QPainterPath(QPointF(124, 82))
    right.quadTo(109, 85, 91, 96)
    right.lineTo(98, 111)
    right.quadTo(114, 112, 121, 102)
    right.closeSubpath()
    mouth = QPainterPath(QPointF(41, 137))
    for point in ((51, 139), (55, 133), (66, 148), (80, 139), (94, 148),
                  (105, 133), (109, 139), (119, 137)):
        mouth.lineTo(*point)
    mouth.cubicTo(109, 149, 96, 155, 80, 155)
    mouth.cubicTo(63, 155, 51, 149, 41, 137)
    mouth.closeSubpath()
    heat = QLinearGradient(0, 80, 0, 155)
    if art.violet:
        heat.setColorAt(0, art.color(255, round(186 + 62 * beat), round(95 + 100 * beat)))
        heat.setColorAt(1, art.color(round(221 + 34 * beat), round(128 + 100 * beat), round(47 + 60 * beat)))
    else:
        heat.setColorAt(0, art.color(255, round(153 + 94 * beat), round(20 + 144 * beat)))
        heat.setColorAt(1, art.color(255, round(111 + 112 * beat), round(6 + 61 * beat)))
    p.setBrush(heat)
    p.setPen(QPen(art.color('#170F21' if art.violet else '#251009'), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(left)
    p.drawPath(right)
    p.setPen(Qt.NoPen)
    p.drawPath(mouth)
    for side, cx in ((-1, 51), (1, 109)):
        top = 81 - 92 * beat
        sway = math.sin(t * 15 + side) * (2 + 3 * beat)
        fire = QPainterPath(QPointF(cx - 7, 105))
        fire.cubicTo(cx - 12, 96, cx + 4 + sway, 90, cx - 3 + sway, top)
        fire.cubicTo(cx + 15, top + 15, cx + 1, 92, cx + 9, 95)
        fire.cubicTo(cx + 13, 106, cx + 2, 111, cx - 7, 105)
        gradient = QLinearGradient(cx, top, cx, 109)
        gradient.setColorAt(0, art.color('#D68036' if art.violet else '#ff5c0a'))
        gradient.setColorAt(.45, art.color('#FFD27A' if art.violet else '#ffb51d'))
        gradient.setColorAt(1, art.color('#fff5b2'))
        p.setBrush(gradient)
        p.drawPath(fire)
        p.save()
        p.translate(cx, 107)
        p.scale(.48, .68)
        p.translate(-cx, -107)
        p.setBrush(art.color('#fff8ce'))
        p.drawPath(fire)
        p.restore()
    p.restore()

def _draw_fire(p, phase, art):
    _draw_eyes(p, 0, 0, phase, art)
    strength = flare_level(phase)
    if strength < .01:
        return
    p.save()
    p.translate(-16, -21)
    p.scale(.2, .2)
    p.setPen(Qt.NoPen)
    for side, cx in ((-1, 40), (1, 120)):
        top = 126 - 43 * strength
        sway = math.sin(phase * 13 + side) * 5
        flame = QPainterPath(QPointF(cx - 5, 145))
        flame.cubicTo(cx - 15, 134, cx + 6 + sway, 122, cx + sway, top)
        flame.cubicTo(cx + 20, top + 14, cx + 7, 128, cx + 11, 135)
        flame.cubicTo(cx + 11, 146, cx + 2, 150, cx - 5, 145)
        gradient = QLinearGradient(cx, top, cx, 147)
        gradient.setColorAt(0, art.color('#DF8739'))
        gradient.setColorAt(.5, art.color('#FFD37A'))
        gradient.setColorAt(1, art.color('#FFF5C0'))
        p.setOpacity(strength)
        p.setBrush(gradient)
        p.drawPath(flame)
        p.save()
        p.translate(cx, 145)
        p.scale(.45, .7)
        p.translate(-cx, -145)
        p.setBrush(art.color('#FFF8D6'))
        p.drawPath(flame)
        p.restore()
    p.restore()

class _AmbientLight(QWidget):
    """A cached background inside headerBar, below its labels and buttons."""
    def __init__(self, header):
        super().__init__(header)
        with ExitStack() as rollback:
            rollback.callback(self.deleteLater)
            rollback.callback(self.hide)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.setAttribute(Qt.WA_NoSystemBackground)
            self.setFocusPolicy(Qt.NoFocus)
            self.setStyleSheet('background:transparent;border:none;')
            self.raster = QPixmap()
            self.level = 0.0
            self.hide()
            rollback.pop_all()

    def set_level(self, level):
        self.level = level
        if level > .003:
            self.show()
            self.lower()
            self.update()
        elif self.isVisible():
            self.hide()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setOpacity(self.level)
        painter.drawPixmap(0, 0, self.raster)
        painter.end()


def _fill_light(painter, rect, source, reaches, stops, vertical_radius):
    """Stretch each cached half toward its forest, keeping the pumpkin as origin."""
    gradient = QRadialGradient(0, 0, 1)
    for position, color in stops:
        gradient.setColorAt(position, color)
    sx, sy = source.x(), source.y()
    halves = (QRectF(0, 0, sx, rect.height()),
              QRectF(sx, 0, rect.width() - sx, rect.height()))
    for reach, bounds in zip(reaches, halves):
        brush = QBrush(gradient)
        brush.setTransform(QTransform(reach, 0, 0, vertical_radius, sx, sy))
        painter.fillRect(bounds, brush)


class ReflectedLight(QWidget):
    """One cached local surface: ambient pool, tree tint, and header edge."""
    def __init__(self, decorations):
        super().__init__(decorations.header.parentWidget())
        with ExitStack() as rollback:
            rollback.callback(self.deleteLater)
            rollback.callback(self.hide)
            self.decorations = decorations
            self.color = getattr(getattr(decorations, "package", None), "color", QColor)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.setAttribute(Qt.WA_NoSystemBackground)
            self.setStyleSheet('background:transparent;border:none;')
            self.level = 0.0
            self.raster = QPixmap()
            self.ambient = _AmbientLight(decorations.header)
            rollback.callback(self.ambient.deleteLater)
            self.key = None
            self.builds = 0
            self._raising = False
            self.renderers = []
            for tree in (decorations.tree, decorations.small_tree):
                self.renderers.append((tree, tree.renderer))
                tree.installEventFilter(self)
                rollback.callback(tree.removeEventFilter, self)
            decorations.header.installEventFilter(self)
            rollback.callback(decorations.header.removeEventFilter, self)
            self.hide()
            rollback.pop_all()

    def prepare(self, badge):
        parent = self.parentWidget()
        header = self.decorations.header
        source = badge.mapTo(parent, QPoint(64, 23))
        left_limit = self.decorations.host.header.light_left(parent)
        right_limit = header.mapTo(parent, QPoint(header.width(), 0)).x()
        tree_rects = [(tree, tree.geometry(), tree.isVisible(), renderer) for tree, renderer in self.renderers]
        # Both forests receive the same falloff at their centres even when the
        # header stretches or the pumpkin sits off-centre inside its badge.
        reaches = [275.0, 275.0]
        for _, bounds, visible, _ in tree_rects:
            if visible:
                distance = bounds.center().x() - source.x()
                side = 0 if distance < 0 else 1
                reaches[side] = max(reaches[side], abs(distance) / .65)
        left = max(left_limit, math.floor(source.x() - reaches[0]))
        right = min(right_limit, math.ceil(source.x() + reaches[1]))
        bottom = header.mapTo(parent, QPoint(0, header.height())).y()
        rect = QRect(left, 0, max(1, right - left), bottom)
        density = self.devicePixelRatioF()
        key = (rect.x(), rect.width(), rect.height(), source.x(), source.y(), density,
               tuple((r.x(), r.y(), r.width(), r.height(), visible) for _, r, visible, _ in tree_rects))
        self.setGeometry(rect)
        self.ambient.setGeometry(QRect(header.mapFrom(parent, rect.topLeft()), rect.size()))
        if key == self.key:
            return
        self.key = key
        self.builds += 1
        self.raster = QPixmap(round(rect.width() * density), round(rect.height() * density))
        self.raster.setDevicePixelRatio(density)
        self.raster.fill(Qt.transparent)
        sx, sy = source.x() - left, source.y()
        p = QPainter(self.raster)
        local_source = QPointF(sx, sy)
        glow_stops = ((0, self.color(255, 197, 103, 27)),
                      (.45, self.color(221, 138, 71, 15)),
                      (1, self.color(221, 138, 71, 0)))
        self.ambient.raster = QPixmap(self.raster.size())
        self.ambient.raster.setDevicePixelRatio(density)
        self.ambient.raster.fill(Qt.transparent)
        ambient_painter = QPainter(self.ambient.raster)
        _fill_light(ambient_painter, self.rect(), local_source,
                    [reach * 265 / 275 for reach in reaches], glow_stops, 265)
        ambient_painter.end()
        # Only the outer header margin belongs to the root overlay. Inside
        # headerBar the glow is a child background, covered by all controls.
        header_rect = QRect(header.mapTo(parent, QPoint()), header.size()).translated(-left, 0)
        p.save()
        p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(header_rect)))
        p.drawPixmap(0, 0, self.ambient.raster)
        p.restore()
        trees = QPixmap(self.raster.size())
        trees.setDevicePixelRatio(density)
        trees.fill(Qt.transparent)
        tp = QPainter(trees)
        for tree, bounds, visible, renderer in tree_rects:
            if visible:
                renderer.render(tp, QRectF(bounds.translated(-left, 0)))
        tp.setCompositionMode(QPainter.CompositionMode_SourceIn)
        tp.fillRect(QRectF(0, 0, rect.width(), rect.height()), self.color('#DFA86A'))
        tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        _fill_light(tp, self.rect(), local_source, reaches,
                    ((0, self.color(255, 255, 255, 180)),
                     (.45, self.color(255, 255, 255, 100)),
                     (.85, self.color(255, 255, 255, 28)),
                     (1, self.color(255, 255, 255, 0))), 275)
        tp.end()
        p.drawPixmap(0, 0, trees)
        edge = QLinearGradient(0, 0, rect.width(), 0)
        edge.setColorAt(0, self.color(255, 217, 156, 0))
        edge.setColorAt(sx / rect.width(), self.color(255, 217, 156, 60))
        edge.setColorAt(1, self.color(255, 217, 156, 0))
        p.setPen(QPen(edge, 1))
        p.drawLine(0, rect.height() - 1, rect.width(), rect.height() - 1)
        p.end()

    def set_level(self, level):
        was_visible = self.isVisible()
        self.level = max(0.0, min(1.0, level))
        self.ambient.set_level(self.level)
        if self.level > .003:
            self.show()
            self.raise_()
            badge = getattr(self.decorations, 'badge', None)
            if badge is not None and badge.parentWidget() is self.parentWidget():
                badge.raise_()
            self.update()
        elif was_visible:
            self.hide()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setOpacity(self.level)
        p.drawPixmap(0, 0, self.raster)
        p.end()

    def eventFilter(self, watched, event):
        if self.isVisible() and event.type() == QEvent.ZOrderChange and not self._raising:
            self._raising = True
            self.raise_()
            badge = getattr(self.decorations, 'badge', None)
            if badge is not None and badge.parentWidget() is self.parentWidget():
                badge.raise_()
            self._raising = False
        return False

    def dispose(self):
        self.set_level(0)
        for tree, _renderer in self.renderers:
            tree.removeEventFilter(self)
        self.decorations.header.removeEventFilter(self)
        self.raster = QPixmap()
        self.ambient.raster = QPixmap()
        self.ambient.deleteLater()
        self.deleteLater()

class FireHeader(_SvgDecoration):
    """The shared clock owns scheduling; this widget only selects cached frames."""
    def __init__(self, decorations, animation):
        self.animation = animation
        self.light = None
        self.tree = decorations.tree
        package = getattr(decorations, 'package', None)
        if package is None:
            from ui.themes.package import read_package
            package = read_package('halloween')
        # Share the forest's parent so the pill can stay in front of branches
        # that extend into it when the header is narrow.
        super().__init__('header-fire-base', decorations.header.parentWidget(), package=package)
        with ExitStack() as rollback:
            rollback.callback(self.deleteLater)
            rollback.callback(self.hide)
            self.setFixedSize(246, 42)
            self.animation = animation
            self.art = PumpkinArt(package.asset('header-pumpkin'), violet=True, color=package.color)
            self.light = ReflectedLight(decorations)
            rollback.callback(self.light.dispose)
            self.phase = -1.0
            self.frames = []
            self.bank_key = None
            self.bank_builds = 0
            animation.add_surface(self)
            rollback.callback(animation.remove_surface, self)
            animation.phaseChanged.connect(self.show_phase)
            rollback.callback(animation.phaseChanged.disconnect, self.show_phase)
            rollback.pop_all()

    def prepare(self):
        density = self.devicePixelRatioF()
        key = (ICON_RECT.width(), ICON_RECT.height(), density)
        if key != self.bank_key:
            self.bank_key = key
            self.bank_builds += 1
            self.frames = []
            for phase in FRAME_PHASES:
                pixmap = QPixmap(round(ICON_RECT.width() * density), round(ICON_RECT.height() * density))
                pixmap.setDevicePixelRatio(density)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.translate(64 - ICON_RECT.x(), 23)
                painter.scale(.78, .78)
                _draw_fire(painter, phase, self.art)
                painter.end()
                self.frames.append(pixmap)
        self.light.prepare(self)

    def dispose(self):
        self.animation.phaseChanged.disconnect(self.show_phase)
        self.animation.remove_surface(self)
        self.frames.clear()
        self.art.raster = QPixmap()
        self.light.dispose()

    def show_phase(self, phase):
        self.phase = phase
        if self.isVisible():
            self.prepare()
            level = flare_level(phase)
            self.tree.set_face_level(level)
            self.light.set_level(level)
            self.update(ICON_RECT)
        else:
            self.tree.set_face_level(0)
            self.light.set_level(0)

    def refresh_scene(self):
        self.show_phase(self.animation.phase)
        self.animation.refresh()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.animation.refresh()

    def hideEvent(self, event):  # noqa: N802
        if self.light is not None and not QApplication.closingDown():
            self.light.set_level(0)
            self.tree.set_face_level(0)
        super().hideEvent(event)
        if not QApplication.closingDown():
            self.animation.refresh()

    def paintEvent(self, event):  # noqa: N802
        self.prepare()
        super().paintEvent(event)
        painter = QPainter(self)
        painter.drawPixmap(ICON_RECT.topLeft(), self.frames[frame_index(self.phase)])
        painter.end()
