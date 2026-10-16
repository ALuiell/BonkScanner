"""Native, non-interactive theme decorations attached to the desktop layout."""
from __future__ import annotations

from contextlib import ExitStack
from ui.themes.lifecycle import ThemeResources

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QTextEdit, QWidget


class _SvgDecoration(QWidget):
    def __init__(self, asset: str, parent: QWidget, *, package=None) -> None:
        super().__init__(parent)
        with ExitStack() as rollback:
            rollback.callback(self.deleteLater)
            rollback.callback(self.hide)
            self.setObjectName("seasonalDecoration")
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.setAttribute(Qt.WA_NoSystemBackground)
            self.setFocusPolicy(Qt.NoFocus)
            self.setStyleSheet("background: transparent; border: none;")
            if package is None:
                from ui.themes.package import read_package
                package = read_package("halloween")  # Standalone artwork previews.
            self.renderer = QSvgRenderer(package.asset(asset), self)
            self._raster_key = None
            self._raster = QPixmap()
            self.hide()
            rollback.pop_all()

    def paintEvent(self, _event) -> None:  # noqa: N802
        density = self.devicePixelRatioF()
        key = (self.width(), self.height(), density)
        if key != self._raster_key:
            self._raster = QPixmap(max(1, round(self.width() * density)),
                                   max(1, round(self.height() * density)))
            self._raster.setDevicePixelRatio(density)
            self._raster.fill(Qt.transparent)
            cache_painter = QPainter(self._raster)
            self.renderer.render(cache_painter, QRectF(self.rect()))
            cache_painter.end()
            self._raster_key = key
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._raster)
        painter.end()

    def sizeHint(self):  # noqa: N802
        # QTabWidget positions its corner from sizeHint, not fixedSize alone.
        return self.size()


class MoopForest(_SvgDecoration):
    """Reveal the face behind the same branches that receive reflected light."""

    FACE_RECT = QRectF(150, 29, 62, 55)

    def __init__(self, parent, *, package=None):
        if package is None:
            from ui.themes.package import read_package
            package = read_package("halloween")
        source = QPixmap(package.asset("dark-moop-face"))
        if source.isNull():
            raise ValueError("Invalid Dark Moop face image")
        super().__init__("forest-left", parent, package=package)
        self.face_source = source
        self.face_raster = QPixmap()
        self.face_key = None
        self.face_opacity = 0.0

    def set_face_level(self, level):
        # The two pumpkin bursts drive this directly; there is no extra timer.
        opacity = .62 * max(0.0, min(1.0, (level - .15) / .85)) ** 1.2
        if abs(opacity - self.face_opacity) > .001:
            self.face_opacity = opacity
            if self.isVisible():
                self.update(self.FACE_RECT.toAlignedRect())

    def paintEvent(self, event):  # noqa: N802
        if self.face_opacity > .003:
            density = self.devicePixelRatioF()
            key = (self.FACE_RECT.size(), density)
            if key != self.face_key:
                self.face_raster = QPixmap(max(1, round(self.FACE_RECT.width() * density)),
                                           max(1, round(self.FACE_RECT.height() * density)))
                self.face_raster.setDevicePixelRatio(density)
                self.face_raster.fill(Qt.transparent)
                cache = QPainter(self.face_raster)
                cache.setRenderHint(QPainter.SmoothPixmapTransform)
                cache.drawPixmap(QRectF(0, 0, self.FACE_RECT.width(), self.FACE_RECT.height()),
                                 self.face_source, QRectF(self.face_source.rect()))
                cache.end()
                self.face_key = key
            painter = QPainter(self)
            painter.setOpacity(self.face_opacity)
            painter.drawPixmap(self.FACE_RECT.topLeft(), self.face_raster)
            painter.end()
        super().paintEvent(event)


class ThemeDecorations(QObject):
    def __init__(self, host, *, package=None) -> None:
        super().__init__(host.window)
        self.resources = ThemeResources()
        with self.resources as rollback:
            rollback.callback(self._abort_construction)
            if package is None:
                from ui.themes.package import read_package
                package = read_package("halloween")
            self.package = package
            self.disposed = False
            self.host = host
            self.enabled = False
            self._pending = False
            self._skeleton_suppressed = False
            self.header = host.header.widget
            self.logo = host.logo
            self.premium_badge = host.premium_badge
            self.original_premium_icon = QIcon(self.premium_badge.icon())
            self.original_premium_icon_size = QSize(self.premium_badge.iconSize())
            self.premium_crown = QIcon(package.asset("premium-crown"))
            self.original_logo = QPixmap(self.logo.pixmap()) if self.logo.pixmap() is not None else QPixmap()
            from ui.themes.providers.halloween_effects.animation import HalloweenAnimation
            from ui.themes.providers.halloween_effects.header import FireHeader

            self.animation = HalloweenAnimation(host.window, package=package)
            rollback.callback(self.animation.dispose)
            # The artwork extends through the header's outer top margin. Parenting
            # it to headerBar would clip the branches 16 px below the window edge.
            self.tree = MoopForest(self.header.parentWidget(), package=package)
            rollback.callback(self.tree.deleteLater)
            self.tree.resize(round(package.parameter("forest_left_width")), round(package.parameter("forest_height")))
            self.small_tree = _SvgDecoration("forest-right", self.header.parentWidget(), package=package)
            rollback.callback(self.small_tree.deleteLater)
            self.small_tree.resize(self.small_tree.renderer.defaultSize().width(), round(package.parameter("forest_height")))
            self.right_tabs = host.corner_tabs
            self.original_corner = self.right_tabs.cornerWidget(Qt.TopRightCorner)
            self.original_corner_visible = self.original_corner is not None and not self.original_corner.isHidden()
            self.bats = _SvgDecoration("bats", self.right_tabs, package=package)
            rollback.callback(self.bats.deleteLater)
            self.bats.setFixedSize(50, 44)
            rollback.callback(self._restore_corner)
            self.right_tabs.setCornerWidget(self.bats, Qt.TopRightCorner)
            self.left_tabs = host.templates.widget
            self.web = _SvgDecoration("web", self.left_tabs, package=package)
            rollback.callback(self.web.deleteLater)
            self.web.setFixedSize(round(package.parameter("web_width")), round(package.parameter("web_height")))
            self.log_edit = host.log_view
            self.skeleton = _SvgDecoration("skeleton-reclining", self.log_edit, package=package)
            rollback.callback(self.skeleton.deleteLater)
            self.badge = FireHeader(self, self.animation)
            rollback.callback(self.badge.deleteLater)
            rollback.callback(self.badge.dispose)
            self.decorations = (self.badge, self.tree, self.small_tree, self.bats, self.web, self.skeleton)
            for widget in host.layout_widgets:
                rollback.event_filter(widget, self)
            for signal in host.layout_signals:
                rollback.connect(signal, self._schedule)

    def _abort_construction(self):
        # Queued zero-delay refreshes may outlive a failed constructor.
        self.disposed = True
        self.enabled = False
        self.deleteLater()

    def _restore_corner(self):
        self.right_tabs.setCornerWidget(self.original_corner, Qt.TopRightCorner)
        if self.original_corner is not None:
            self.original_corner.setVisible(self.original_corner_visible)

    def _schedule(self, *_args) -> None:
        if not self.disposed and not self._pending:
            self._pending = True
            QTimer.singleShot(0, self, self._refresh)

    def set_skeleton_suppressed(self, suppressed: bool) -> None:
        """Keep refreshes from exposing corner art behind a Support overlay."""
        if self._skeleton_suppressed == suppressed:
            return
        self._skeleton_suppressed = suppressed
        if suppressed:
            self.skeleton.hide()
        self._schedule()

    def eventFilter(self, _watched, event):  # noqa: N802
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            self._schedule()
        return False

    def set_enabled(self, enabled: bool) -> None:
        if self.disposed:
            return
        self.enabled = enabled
        if not enabled:
            self.animation.set_enabled(False)
        self.premium_badge.setIcon(self.premium_crown if enabled else self.original_premium_icon)
        self.premium_badge.setIconSize(QSize(16, 16) if enabled else self.original_premium_icon_size)
        if not self.original_logo.isNull():
            pixmap = self.original_logo
            if enabled:
                # Render at the actual display density: a 1x composite makes
                # both the curled hat and its orange band blurry on Windows.
                density = self.logo.devicePixelRatioF()
                pixmap = QPixmap(round(34 * density), round(42 * density))
                pixmap.setDevicePixelRatio(density)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(0, 18, self.original_logo)
                hat = QSvgRenderer(self.package.asset("hat"))
                hat.render(painter, QRectF(4, 0, 28, 26))
                painter.end()
            self.logo.setPixmap(pixmap)
        self._refresh()
        self.animation.set_enabled(enabled)

    def _refresh(self) -> None:
        self._pending = False
        if self.disposed:
            return
        if not self.enabled:
            for decoration in self.decorations:
                decoration.hide()
            return
        left, right = self.host.header.content_span()
        badge_visible = self.badge.renderer.isValid() and right - left >= self.badge.width() + 16
        self.badge.setVisible(badge_visible)
        if badge_visible:
            center = self.header.width() // 2
            badge_x = max(left, min(center - self.badge.width() // 2, right - self.badge.width() - 8))
            badge_y = max(0, (self.header.height() - 9 - self.badge.height()) // 2)
            self.badge.move(self.header.mapTo(self.badge.parentWidget(), QPoint(badge_x, badge_y)))
        # header.svg's pill occupies x=40..206 inside the 246 px canvas.
        # Keep the forest at its native width in narrow windows. Its right
        # branches can pass behind the translucent pill instead of shrinking or
        # appearing only in the reflected-light layer.
        tree_right = badge_x + 32 if badge_visible else left
        tree_visible = badge_visible
        self.tree.setVisible(tree_visible)
        if tree_visible:
            width = round(self.package.parameter("forest_left_width"))
            position = self.header.mapTo(self.tree.parentWidget(), QPoint(
                left + max(0, (tree_right - left - width) // 2),
                self.header.height() - self.tree.height() - 1,
            ))
            self.tree.setGeometry(position.x(), position.y(), width, round(self.package.parameter("forest_height")))
            self.tree.raise_()
        forest_left = badge_x + 214 if badge_visible else right
        forest_width = max(0, right - 8 - forest_left)
        small_visible = badge_visible and forest_width > 65
        self.small_tree.setVisible(small_visible)
        if small_visible:
            width = min(self.small_tree.renderer.defaultSize().width(), forest_width)
            position = self.header.mapTo(self.small_tree.parentWidget(), QPoint(
                forest_left + (forest_width - width) // 2,
                self.header.height() - self.small_tree.height() - 1,
            ))
            self.small_tree.setGeometry(position.x(), position.y(), width, round(self.package.parameter("forest_height")))
            self.small_tree.raise_()
        if badge_visible:
            self.badge.raise_()
        self.bats.setVisible(self.bats.renderer.isValid() and self.right_tabs.width() >=
                             self.right_tabs.tabBar().sizeHint().width() + self.bats.width())
        web_visible = False
        available = self.host.templates.available_rect()
        if (self.web.renderer.isValid() and available is not None
                and available.height() > self.web.height() and available.width() > 150):
            self.web.move(available.x(), available.y() + available.height() - self.web.height())
            web_visible = True
            self.web.raise_()
        self.web.setVisible(web_visible)
        viewport = self.log_edit.viewport()
        source_size = self.skeleton.renderer.defaultSize()
        width = min(round(self.package.parameter("skeleton_max_width")), max(250, viewport.width() // 3))
        height = round(width * source_size.height() / source_size.width()) if source_size.width() else 0
        y = self.log_edit.height() - height - round(self.package.parameter("skeleton_bottom_margin"))
        viewport_y = viewport.mapTo(self.log_edit, QPoint(0, 0)).y()
        skeleton_visible = (not self._skeleton_suppressed
                            and self.skeleton.renderer.isValid() and height > 0
                            and viewport.width() >= 380 and y > 0
                            and self.log_edit.document().size().height() + 16 < y - viewport_y)
        self.skeleton.setVisible(skeleton_visible)
        if skeleton_visible:
            self.skeleton.setGeometry(self.log_edit.width() - width - round(self.package.parameter("skeleton_right_margin")), y, width, height)
            self.skeleton.raise_()
        self.badge.refresh_scene()

    def dispose(self):
        if self.disposed:
            return
        try:
            self.set_enabled(False)
        finally:
            self.disposed = True
            # Inert immediately, not only after Qt processes DeferredDelete.
            for decoration in self.decorations:
                decoration.hide()
                decoration._raster = QPixmap()
            self.resources.close()
