"""Small mouse-transparent accents that never take space from the layout."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QTextEdit, QWidget



class _SvgDecoration(QWidget):
    def __init__(self, asset: str, parent: QWidget, *, package=None) -> None:
        super().__init__(parent)
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


class ThemeDecorations(QObject):
    def __init__(self, owner, *, package=None) -> None:
        super().__init__(owner.window)
        if package is None:
            from ui.themes.package import read_package
            package = read_package("halloween")
        self.package = package
        self.disposed = False
        self.owner = owner
        self.enabled = False
        self._pending = False
        self._skeleton_suppressed = False
        self.header = owner.window.findChild(QFrame, "headerBar")
        self.logo = owner.logo_label
        self.premium_badge = owner.premium_access_badge
        self.original_premium_icon = QIcon(self.premium_badge.icon())
        self.original_premium_icon_size = QSize(self.premium_badge.iconSize())
        self.premium_crown = QIcon(package.asset("premium-crown"))
        self.original_logo = QPixmap(self.logo.pixmap()) if self.logo.pixmap() is not None else QPixmap()
        from ui.themes.animation import HalloweenAnimation
        from ui.themes.header import FireHeader

        self.animation = HalloweenAnimation(owner.window, package=package)
        # The artwork extends through the header's outer top margin. Parenting
        # it to headerBar would clip the branches 16 px below the window edge.
        self.tree = _SvgDecoration("forest-left", self.header.parentWidget(), package=package)
        self.tree.resize(round(package.parameter("forest_left_width")), round(package.parameter("forest_height")))
        self.small_tree = _SvgDecoration("forest-right", self.header.parentWidget(), package=package)
        self.small_tree.resize(self.small_tree.renderer.defaultSize().width(), round(package.parameter("forest_height")))
        self.right_tabs = owner.tabview
        self.original_corner = self.right_tabs.cornerWidget(Qt.TopRightCorner)
        self.bats = _SvgDecoration("bats", self.right_tabs, package=package)
        self.bats.setFixedSize(50, 44)
        self.right_tabs.setCornerWidget(self.bats, Qt.TopRightCorner)
        self.left_tabs = owner.left_tabview
        self.web = _SvgDecoration("web", self.left_tabs, package=package)
        self.web.setFixedSize(round(package.parameter("web_width")), round(package.parameter("web_height")))
        self.log_edit = owner.log_box.findChild(QTextEdit)
        self.skeleton = _SvgDecoration("skeleton-reclining", self.log_edit, package=package)
        self.badge = FireHeader(self, self.animation)
        self.decorations = (self.badge, self.tree, self.small_tree, self.bats, self.web, self.skeleton)
        for widget in (owner.window, self.header, self.left_tabs, self.right_tabs, self.log_edit):
            widget.installEventFilter(self)
        self.left_tabs.currentChanged.connect(self._schedule)
        self.log_edit.document().contentsChanged.connect(self._schedule)
        self.log_edit.verticalScrollBar().valueChanged.connect(self._schedule)

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
        status = self.header.findChild(QWidget, "headerStatusCluster")
        right = self.owner.rec_flag.geometry().left()
        left = status.geometry().right() + 16
        badge_visible = self.badge.renderer.isValid() and right - left >= self.badge.width() + 16
        self.badge.setVisible(badge_visible)
        if badge_visible:
            center = self.header.width() // 2
            x = max(left, min(center - self.badge.width() // 2, right - self.badge.width() - 8))
            self.badge.move(x, max(0, (self.header.height() - 9 - self.badge.height()) // 2))
            self.badge.raise_()
        # header.svg's pill occupies x=40..206 inside the 246 px canvas.
        # Use the transparent padding for branches while leaving an 8 px gap.
        tree_right = self.badge.x() + 32
        tree_visible = badge_visible and tree_right - left > 100
        self.tree.setVisible(tree_visible)
        if tree_visible:
            width = min(round(self.package.parameter("forest_left_width")), tree_right - left)
            position = self.header.mapTo(self.tree.parentWidget(), QPoint(
                left + (tree_right - left - width) // 2,
                self.header.height() - self.tree.height() - 1,
            ))
            self.tree.setGeometry(position.x(), position.y(), width, round(self.package.parameter("forest_height")))
            self.tree.raise_()
        forest_left = self.badge.x() + 214
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
        self.bats.setVisible(self.bats.renderer.isValid() and self.right_tabs.width() >=
                             self.right_tabs.tabBar().sizeHint().width() + self.bats.width())
        web_visible = False
        page = self.left_tabs.currentWidget()
        if self.web.renderer.isValid() and self.left_tabs.isVisible() and self.left_tabs.currentIndex() == 0:
            add_button = self.owner._templates_panel.add_btn
            bottom = add_button.mapTo(self.left_tabs, add_button.rect().topLeft()).y() - 6
            top = bottom - self.web.height()
            rows = page.findChildren(QFrame, "TemplateRow")
            row_bottom = max((row.mapTo(self.left_tabs, row.rect().bottomLeft()).y() for row in rows if row.isVisible()), default=0)
            if row_bottom + 14 < top and self.left_tabs.width() > 150:
                self.web.move(2, top)
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
        self.set_enabled(False)
        self.disposed = True
        self.animation.dispose()
        self.badge.dispose()
        for widget in (self.owner.window, self.header, self.left_tabs, self.right_tabs, self.log_edit):
            widget.removeEventFilter(self)
        self.left_tabs.currentChanged.disconnect(self._schedule)
        self.log_edit.document().contentsChanged.disconnect(self._schedule)
        self.log_edit.verticalScrollBar().valueChanged.disconnect(self._schedule)
        self.right_tabs.setCornerWidget(self.original_corner, Qt.TopRightCorner)
        for decoration in self.decorations:
            decoration.hide()
            decoration._raster = QPixmap()
            decoration.deleteLater()
        self.deleteLater()
