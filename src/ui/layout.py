"""The main window's layout, and the router that runs its tab bars.

``gui_layout.py`` until step 27b, which moved it here and closed the last two
``TOPLEVEL_DEBT`` entries. It could not move as one file: see
``ui/tabs/player_stats/metrics.py`` for what came out of it first and why the
split was the point rather than the move.

What is left reads ``app``, ``core`` and ``ui`` -- all of which §2 lets ``ui``
import -- plus ``ui.dialogs``, which was ``gui_dialogs`` until 27a. The two
builders that import ``ui.tabs.player_stats`` inside their bodies keep doing
so; with the metrics gone that is no longer covering a cycle, but it is also
not this step's to change, so the comments there now say which of the two
reasons still applies.
"""
from __future__ import annotations

import os
from functools import partial

from ui.footer import build_footer
from ui.log_view import LogView
from ui.scanner_toggle import ScannerToggle
from ui.status_indicators import LABEL_SPACING, PulsingDot, RecordingFlag
from ui.shared import (
    _apply_button_icon,
    _clear_layout,
    resource_path,
)

from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QDrag, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.template_colors import template_color_hex, template_color_tag

from ui.dialogs import (
    DeleteDialog,
    ScoresHelpDialog,
    ScoresSettingsDialog,
    TemplateDialog,
    TemplateManagerDialog,
)

from app import config
from app.snapshot_store import live_snapshot_store
from app.vod_capture import vod_capture


def _is_tab_active(tabview, label: str) -> bool:
    """Is `label` the tab currently showing in `tabview`?

    Module-level and handed its tab bar, rather than four one-line methods
    reading `self.tabview`, because it has two callers that are not the same
    object: `TabRouter`, which asks it about the bar it routes, and
    `MegabonkApp`, whose two surviving predicates are called *on the
    application* by `app/` modules that may not import a UI component
    (`player_stats_memory`, `player_stats_refresh`, `refresh_tasks`,
    `vod_capture`) and by `gui_overlay.build_overlay`. One implementation, two
    callers, no ambient `self` -- the shape steps 19 and 24a took for the same
    reason: a free function has no class to be orphaned from.

    The `None` guard is new and deliberate. The four predicates this replaces
    read `self.tabview.tabText(...)` unguarded, which raises before the tab bar
    exists -- and Qt **swallows exceptions raised inside a slot**, so a router
    firing early would degrade into a traceback on stderr with no other
    symptom. That is the failure shape steps 21 and 22c each shipped once.
    "No tab is active because there is no tab bar" is the same answer with no
    way to hide.
    """
    if tabview is None:
        return False
    current_index = tabview.currentIndex()
    if current_index < 0:
        return False
    return tabview.tabText(current_index) == label


class TabRouter:
    """What happens when the user switches a tab.

    The ports are suppliers because the heavy recording views are created
    after the router itself. The signals, however, are connected only after
    ``build_layout`` has registered every page. Construction must not
    masquerade as user navigation: adding the first tab used to write
    ``config.json`` and queue work against a half-built object graph.

    Right-tab work is one queued, coalesced pass. Several switches can happen
    before Qt returns to the event loop, and only the final visible page is
    useful then. Refreshing a recording list synchronously and again after the
    redraw merely doubled file/model work at the most timing-sensitive point.
    """

    def __init__(
        self,
        *,
        left_tabview,
        tabview,
        templates_panel,
        recordings_view,
        compare_runs_view,
        overlay,
        template_filters,
        update_status,
        refresh_live_player_stats,
        schedule_idle,
    ) -> None:
        self._left_tabview = left_tabview
        self._tabview = tabview
        self._templates_panel = templates_panel
        self._recordings_view = recordings_view
        self._compare_runs_view = compare_runs_view
        self._overlay = overlay
        self._template_filters = template_filters
        self._update_status = update_status
        self._refresh_live_player_stats = refresh_live_player_stats
        self._schedule_idle = schedule_idle
        self._right_refresh_generation = 0

    # -- the left bar: Templates <-> Scores --------------------------------
    def on_left_tab_changed(self) -> None:
        left_tabview = self._left_tabview()
        if left_tabview is None:
            return
        current_index = left_tabview.currentIndex()
        if current_index < 0:
            return
        tab_name = left_tabview.tabText(current_index)
        if tab_name not in {"Templates", "Scores"}:
            return
        evaluation_mode = "scores" if tab_name == "Scores" else "templates"
        mode_changed = (
            config.EVALUATION_MODE != evaluation_mode
            or config.user_config.get("EVALUATION_MODE") != evaluation_mode
        )
        config.EVALUATION_MODE = evaluation_mode
        config.user_config["EVALUATION_MODE"] = evaluation_mode
        if mode_changed:
            config.save_config(config.user_config)
        templates_panel = self._templates_panel()
        if templates_panel is not None:
            templates_panel.refresh_scores_ui()
        self._template_filters.sync(announce=True)
        self._update_status()

    # -- the right bar ------------------------------------------------------
    def on_right_tab_changed(self) -> None:
        self._right_refresh_generation += 1
        generation = self._right_refresh_generation
        self._schedule_idle(
            lambda: self._refresh_right_tab_after_switch(generation=generation)
        )

    def _refresh_right_tab_after_switch(self, *, generation: int | None = None) -> None:
        if generation is not None and generation != self._right_refresh_generation:
            return
        self._refresh_recording_tabs()
        if self.is_live_stats_tab_active():
            self._refresh_live_player_stats()
        if self.is_overlay_tab_active():
            self._overlay.refresh_overlay_ui()

    def _refresh_recording_tabs(self) -> None:
        """Refresh whichever recording-backed page is visible, once."""
        recordings_view = self._recordings_view()
        if recordings_view is not None and self.is_recordings_tab_active():
            recordings_view.refresh_vods_list()
            recordings_view.ensure_recordings_chooser_for_empty_selection()
        compare_runs_view = self._compare_runs_view()
        if compare_runs_view is not None and self.is_compare_runs_tab_active():
            compare_runs_view.refresh_compare_runs_list()
            compare_runs_view.ensure_compare_runs_chooser_for_empty_selection()

    def is_live_stats_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "Live Stats")

    def is_overlay_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "OBS Overlay")

    def is_recordings_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "Recordings")

    def is_compare_runs_tab_active(self) -> bool:
        return _is_tab_active(self._tabview(), "Compare Runs")

    # `RecordingsListView`'s single operation (`app/player_stats_view.py`).
    # The underscore is the protocol's, not a privacy claim: `vod_capture` and
    # `player_stats_refresh` call this name through `recordings_list_view()`,
    # whose fallback to the app object was scheduled to die with this step and
    # does -- `_build_tab_router` injects this object as `_recordings_list_view`.
    def _refresh_vods_list_if_visible(self) -> None:
        recordings_view = self._recordings_view()
        if recordings_view is not None and self.is_recordings_tab_active():
            recordings_view.refresh_vods_list()
        compare_runs_view = self._compare_runs_view()
        if compare_runs_view is not None and self.is_compare_runs_tab_active():
            compare_runs_view.refresh_compare_runs_list()


def build_layout(app):
    """Build the main window's layout. **`MegabonkApp`'s last base class.**

    This was `GuiLayoutMixin.setup_ui`, and the mixin existed for one reason:
    a method needs a `self`, and `self` was the application. Every widget it
    creates is assigned onto the app, every builder it calls was a sibling
    method found through the MRO, and the seventeen names it read but never
    assigned were the app's own API surface reached ambiently -- which is what
    made `MegabonkApp` a method namespace rather than a composition root.

    It is a function taking `app` now, which is the form the five view roots
    below have had since steps 19-23 and the form this file's own header has
    argued for since. Nothing about the sequence changed: same builders, same
    order, same tab positions. What changed is that `app` is a parameter with
    a name instead of an ambient `self`, so every one of those reads is
    visible at the call site and none of them is hidden.

    `app.window.setCentralWidget`, not `app.setCentralWidget`, is the only
    behavioural detail here worth a line. It was the one hidden read in this
    file whose owner was not the application: `MegabonkApp.__getattr__`
    forwards unknown names to `self.window`, so it resolved onto the
    `_AppWindow` by accident of the shell. Naming the window is the same call
    with the receiver written down.
    """
    app._tab_router = _build_tab_router(app)
    central = QWidget()
    central.setObjectName("centralWidget")
    app.window.setCentralWidget(central)

    # Two layouts where there was one, and only because of the footer. The
    # strip is the window's base edge, so it has to reach both side walls --
    # inset by the 16px content margins it would read as a floating bar with a
    # gap under it. So the margins move down onto an inner widget that holds
    # everything that had them before, and the root keeps none.
    root_layout = QVBoxLayout(central)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    content = QWidget()
    content.setObjectName("centralContent")
    root_layout.addWidget(content, 1)
    root_layout.addWidget(build_footer(app))

    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(16, 16, 16, 16)
    content_layout.setSpacing(14)

    _build_header(app, content_layout)

    splitter = QSplitter(Qt.Horizontal)
    splitter.setChildrenCollapsible(False)
    content_layout.addWidget(splitter, 1)

    _build_left_tabs(app, splitter)
    _build_right_panel(app, splitter)
    _build_logs_tab(app)
    app._scanner.build_session_stats_tab()
    app._player_stats_view = _build_live_stats_view(app)
    from ui.timeline_controls import TimelineSeriesSlots

    timeline_series_slots = TimelineSeriesSlots()
    app._recordings_view = _build_recordings_view(app, timeline_series_slots)
    app._compare_runs_view = _build_compare_runs_view(app, timeline_series_slots)
    app.tabview.addTab(app._overlay.build(), "OBS Overlay")
    # The ~240 lines that built the Twitch tab's widgets are
    # `TwitchTab.build()`'s now (step 23b).
    app._twitch_tab = _build_twitch_tab(app)
    # These two lines were the last two of `_build_twitch_bot_tab` (step
    # 23a). The Twitch tab builder built the In-Game Overlay tab as well and
    # added it to the tab bar, which is where two of `gui_twitch.py`'s nine
    # hidden reads came from -- `_build_in_game_overlay_tab` and
    # `tab_in_game_overlay`. The in-game overlay is step 24's subject, so
    # nothing about it moves here: only the call site, hoisted to the
    # builder list it belongs in, in the position that keeps the tab bar's
    # order identical.
    app.tabview.addTab(app._in_game_overlay.build(), "In-Game Overlay")
    for index in range(app.tabview.count()):
        app.tabview.widget(index).setObjectName("mainTabPage")

    # Adding the first tab emits ``currentChanged``. Connect only after every
    # supplier the router can reach exists, so construction never persists a
    # preference or queues refresh work as if the user had navigated.
    app.left_tabview.currentChanged.connect(app._tab_router.on_left_tab_changed)
    app.tabview.currentChanged.connect(app._tab_router.on_right_tab_changed)


def _build_header(app, parent_layout):
    header_wrap = QFrame()
    header_wrap.setObjectName("headerBar")
    header = QHBoxLayout(header_wrap)
    header.setContentsMargins(4, 2, 4, 9)
    header.setSpacing(12)

    logo_label = QLabel()
    app.logo_label = logo_label
    logo_label.setObjectName("appLogo")
    logo_label.setAlignment(Qt.AlignCenter)
    logo_path = resource_path("media/bonkscanner_icon2.png")
    if os.path.exists(logo_path):
        pixmap = QPixmap(logo_path)
        if not pixmap.isNull():
            logo_label.setPixmap(
                pixmap.scaled(34, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            logo_label.setText("BONK")
    else:
        logo_label.setText("BONK")
    header.addWidget(logo_label, 0, Qt.AlignVCenter)

    title = QLabel("BonkScanner")
    title.setObjectName("appTitle")
    header.addWidget(title, 0, Qt.AlignVCenter)

    divider = QFrame()
    divider.setObjectName("headerDivider")
    header.addWidget(divider, 0, Qt.AlignVCenter)

    # Status reads next to the logo: the dot for the colour, the text for which
    # of the four states it is. The scanner's switch stays at the far end of
    # the header, where `_build_header_controls` puts it.
    # The dot and its word go in together, on their own spacing. The header's
    # is 12px, and `PulsingDot` carries ~5px of transparent padding around the
    # circle so the ring has somewhere to expand, so side by side in the header
    # they sat 17px apart and read as two unrelated things.
    #
    # `PulsingDot` rather than a plain label: the colour still comes from the
    # stylesheet per `state`, but the widget has room around the dot to draw a
    # ring into, so a live scanner reads as live rather than as a green pixel.
    status_pair = QWidget()
    status_pair.setObjectName("statusPair")
    status_pair_layout = QHBoxLayout(status_pair)
    status_pair_layout.setContentsMargins(0, 0, 0, 0)
    status_pair_layout.setSpacing(LABEL_SPACING)

    app.status_dot = PulsingDot()
    app.status_dot.setObjectName("statusDot")
    app.status_dot.setProperty("state", "idle")
    status_pair_layout.addWidget(app.status_dot, 0, Qt.AlignVCenter)

    app.status_label = QLabel("IDLE")
    app.status_label.setObjectName("statusText")
    app.status_label.setProperty("state", "idle")
    status_pair_layout.addWidget(app.status_label, 0, Qt.AlignVCenter)

    header.addWidget(status_pair, 0, Qt.AlignVCenter)

    header.addStretch(1)

    # Whether a recording is running was readable only from the Live Stats tab.
    # It belongs on the header line for the same reason the scanner's status
    # does: it is a thing the app is doing that nothing else on screen shows.
    app.rec_flag = RecordingFlag()
    header.addWidget(app.rec_flag, 0, Qt.AlignVCenter)

    app.session_meta_label = QLabel("Session 00:00:00")
    app.session_meta_label.setObjectName("sessionMeta")
    header.addWidget(app.session_meta_label, 0, Qt.AlignVCenter)

    # Scanner owns the status updates; these private widget references keep its
    # existing two-port surface while letting it update the new header peers.
    app.status_label._status_dot = app.status_dot
    app.status_label._session_meta_label = app.session_meta_label
    app.status_label._rec_flag = app.rec_flag

    _build_header_controls(app, header)
    parent_layout.addWidget(header_wrap)


def _build_left_tabs(app, splitter):
    left_panel = QWidget()
    left_layout = QVBoxLayout(left_panel)
    left_layout.setContentsMargins(0, 0, 0, 0)
    left_layout.setSpacing(0)
    splitter.addWidget(left_panel)

    # The left column has two states the mockup calls for -- the full 280px
    # Templates/Scores panel, and a 52px icon rail. Both live in `left_panel`;
    # `_LeftRail` swaps which one is visible and clamps the splitter width.
    expanded = QWidget()
    expanded_layout = QVBoxLayout(expanded)
    expanded_layout.setContentsMargins(0, 0, 0, 0)

    app.left_tabview = QTabWidget()
    app.left_tabview.setObjectName("mainTabs")
    app.left_tabview.tabBar().setExpanding(True)
    app.left_tabview.tabBar().setUsesScrollButtons(False)

    # The `«` collapse control rides in the tab bar's corner, next to the
    # Templates/Scores pills, exactly where the mockup places it.
    collapse_btn = QPushButton("«")
    collapse_btn.setObjectName("railToggle")
    collapse_btn.setToolTip("Collapse")
    collapse_btn.setFixedSize(30, 30)
    app.left_tabview.setCornerWidget(collapse_btn, Qt.TopRightCorner)
    expanded_layout.addWidget(app.left_tabview)

    collapsed = _build_collapsed_rail(app)

    left_layout.addWidget(expanded)
    left_layout.addWidget(collapsed)

    app._left_rail = _LeftRail(
        splitter,
        left_panel,
        expanded,
        collapsed,
        refresh=lambda: _rebuild_rail_dots(collapsed, app),
    )
    collapse_btn.clicked.connect(app._left_rail.collapse)
    collapsed._expand_btn.clicked.connect(app._left_rail.expand)

    # The ~34 lines that built both left tabs are `TemplatesPanel.build()`'s
    # now (step 22c). Which tab opens remains a layout decision. The router is
    # connected after the full build, so restoring this index is not mistaken
    # for a user change and cannot rewrite the preference during startup.
    app._templates_panel = _build_templates_panel(app)
    app._templates_panel.set_preferred_width_changed(
        app._left_rail.set_preferred_expanded_width
    )
    app.left_tabview.setCurrentIndex(1 if config.EVALUATION_MODE == "scores" else 0)

    # The rail's bottom button follows the collapsed mode -- Add in Templates,
    # Edit in Scores -- so it is wired to the dispatcher rather than to either
    # dialog. It can only be wired once the panel it dispatches to exists.
    collapsed._add_btn.clicked.connect(lambda: _on_rail_action(app, collapsed))


class _VerticalRailLabel(QLabel):
    """A `QLabel` that paints its text rotated to read bottom-to-top.

    The collapsed rail's "TEMPLATES" eyebrow is vertical in the mockup, which
    Qt style sheets cannot express; a ten-line `paintEvent` is the whole cost
    of matching it.
    """

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            if not painter.isActive():
                return
            painter.setPen(QColor("#5C6675"))
            painter.setFont(self.font())
            painter.translate(0, self.height())
            painter.rotate(-90)
            painter.drawText(
                0, 0, self.height(), self.width(), Qt.AlignCenter, self.text()
            )
        finally:
            if painter.isActive():
                painter.end()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.height() + 2, metrics.horizontalAdvance(self.text()) + 10)


def _rail_mode(app) -> tuple[str, list[tuple[str, str, bool]], bool]:
    """The eyebrow, the tiles and the mode the rail is collapsing over.

    `EVALUATION_MODE` is the router's own record of which left tab is open --
    `TabRouter.on_left_tab_changed` writes it -- so the rail reads that rather
    than re-deriving the selection from the tab bar. It is read once per
    collapse and not watched: the tab bar is hidden while the rail is up, so
    the mode cannot change underneath it.
    """
    if config.EVALUATION_MODE == "scores":
        return "SCORES", app._templates_panel.rail_tier_entries(), True
    return "TEMPLATES", _template_rail_entries(), False


def _template_rail_entries() -> list[tuple[str, str, bool]]:
    """`(name, colour, is_active)` for every template, in panel order.

    Read fresh each time the rail is shown so it reflects adds, edits and
    activation toggles made while the panel was expanded. Activation only
    changes a tile's appearance; it must never move that tile to another slot.
    """
    active_names = set(config.ACTIVE_TEMPLATES)
    return [
        (
            template["name"],
            template_color_hex(template_color_tag(template)),
            template["name"] in active_names,
        )
        for template in config.TEMPLATES
    ]


_RAIL_TEMPLATE_DRAG_MIME = "application/x-megabonk-template-id"
_RAIL_REORDER_DURATION_MS = 140


class _DraggableRailTile(QPushButton):
    """A rail toggle that becomes a drag source after the move threshold."""

    def __init__(self, template_id: int | None = None) -> None:
        super().__init__()
        self.template_id = template_id
        self.color_hex = "#8A94A3"
        self.dot = None
        self._press_pos: QPoint | None = None
        self._drag_started = False
        self._dragging = False
        self._drop_edge = 0

    @property
    def draggable(self) -> bool:
        return self.template_id is not None

    def mousePressEvent(self, event) -> None:
        if self.draggable and event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._drag_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self.draggable
            and self._press_pos is not None
            and event.buttons() & Qt.LeftButton
        ):
            distance = (event.position().toPoint() - self._press_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._press_pos = None
                self._drag_started = True
                self.setDown(False)
                self.start_drag()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        if self._drag_started:
            self._drag_started = False
            self.setDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def start_drag(self) -> None:
        if not self.draggable:
            return
        source_pixmap = self.grab()
        ghost = QPixmap(source_pixmap.size())
        ghost.fill(Qt.transparent)
        painter = QPainter(ghost)
        try:
            if painter.isActive():
                painter.setOpacity(0.9)
                painter.drawPixmap(0, 0, source_pixmap)
        finally:
            if painter.isActive():
                painter.end()

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_RAIL_TEMPLATE_DRAG_MIME, str(self.template_id).encode("ascii"))
        drag.setMimeData(mime)
        drag.setPixmap(ghost)
        drag.setHotSpot(QPoint(self.width() // 2, self.height() // 2))

        holder = self.parentWidget()
        if not isinstance(holder, _RailDotsHolder):
            holder = None
        if holder is not None:
            holder.begin_live_drag(self)

        self._set_dragging(True)
        action = Qt.IgnoreAction
        try:
            action = drag.exec(Qt.MoveAction)
        finally:
            self._set_dragging(False)
            if holder is not None:
                ordered_ids = holder.finish_live_drag(
                    action == Qt.MoveAction and holder.drop_accepted
                )
                if ordered_ids is not None:
                    holder.persist_order(ordered_ids)
            self.setDown(False)
            # QDrag consumes the release that completes a drop; clearing this
            # here keeps the next ordinary click independent from that drag.
            self._drag_started = False

    def _set_dragging(self, dragging: bool) -> None:
        self._dragging = bool(dragging)
        if self.dot is not None:
            self.dot.setVisible(not self._dragging)
        self.setCursor(Qt.ClosedHandCursor if self._dragging else Qt.PointingHandCursor)
        self.setStyleSheet(
            _rail_tile_stylesheet(
                self.color_hex,
                self.isChecked(),
                dragging=self._dragging,
            )
        )
        self.update()

    def set_drop_edge(self, edge: int) -> None:
        edge = -1 if edge < 0 else (1 if edge > 0 else 0)
        if edge != self._drop_edge:
            self._drop_edge = edge
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._drop_edge:
            return
        painter = QPainter(self)
        try:
            if not painter.isActive():
                return
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#38BDF8"), 2, Qt.SolidLine, Qt.RoundCap))
            y = 1 if self._drop_edge < 0 else self.height() - 2
            painter.drawLine(3, y, self.width() - 3, y)
        finally:
            if painter.isActive():
                painter.end()


class _RailDotsHolder(QWidget):
    """Vertical drop target whose dots shift while one is being dragged."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("cardContent")
        self.setAcceptDrops(True)
        self._reorder = None
        self._drag_source: _DraggableRailTile | None = None
        self._original_order: list[int] = []
        self._drop_accepted = False
        self._standalone_drag = False
        self._reorder_animation: QParallelAnimationGroup | None = None
        self.dots_layout = QVBoxLayout(self)
        self.dots_layout.setContentsMargins(0, 0, 0, 0)
        self.dots_layout.setSpacing(10)

    def set_reorder_callback(self, callback) -> None:
        self._reorder = callback

    def tiles(self) -> list[_DraggableRailTile]:
        tiles = []
        for index in range(self.dots_layout.count()):
            widget = self.dots_layout.itemAt(index).widget()
            if isinstance(widget, _DraggableRailTile) and widget.draggable:
                tiles.append(widget)
        return tiles

    @property
    def drop_accepted(self) -> bool:
        return self._drop_accepted

    def persist_order(self, ordered_ids: list[int]) -> None:
        if self._reorder is not None:
            self._reorder(ordered_ids)

    def begin_live_drag(
        self, tile: _DraggableRailTile, *, standalone: bool = False
    ) -> None:
        if self._drag_source is tile:
            return
        if self._drag_source is not None:
            self.finish_live_drag(False)
        if tile not in self.tiles():
            return
        self._drag_source = tile
        self._original_order = [item.template_id for item in self.tiles()]
        self._drop_accepted = False
        self._standalone_drag = bool(standalone)
        policy = tile.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        tile.setSizePolicy(policy)
        self._animate_relayout(tile.hide)

    def finish_live_drag(self, accepted: bool) -> list[int] | None:
        source = self._drag_source
        if source is None:
            return None
        current = [tile.template_id for tile in self.tiles()]
        original = list(self._original_order)
        target = current if accepted else original

        def finish_layout() -> None:
            self._set_tile_order(target)
            source.show()
            policy = source.sizePolicy()
            policy.setRetainSizeWhenHidden(False)
            source.setSizePolicy(policy)

        self._animate_relayout(finish_layout)
        self._drag_source = None
        self._original_order = []
        self._drop_accepted = False
        self._standalone_drag = False
        return current if accepted and current != original else None

    def dragEnterEvent(self, event) -> None:
        template_id = self._event_template_id(event)
        if self._reorder is not None and template_id is not None:
            if self._drag_source is None:
                source = next(
                    (tile for tile in self.tiles() if tile.template_id == template_id),
                    None,
                )
                if source is not None:
                    self.begin_live_drag(source, standalone=True)
            if self._drag_source is None or self._drag_source.template_id != template_id:
                event.ignore()
                return
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        template_id = self._event_template_id(event)
        if (
            self._reorder is None
            or template_id is None
            or self._drag_source is None
            or self._drag_source.template_id != template_id
        ):
            event.ignore()
            return
        self._move_source_to_y(event.position().toPoint().y())
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        template_id = self._event_template_id(event)
        if (
            self._reorder is None
            or template_id is None
            or self._drag_source is None
            or self._drag_source.template_id != template_id
        ):
            event.ignore()
            return
        self._move_source_to_y(event.position().toPoint().y())
        self._drop_accepted = True
        event.setDropAction(Qt.MoveAction)
        event.accept()
        if self._standalone_drag:
            ordered_ids = self.finish_live_drag(True)
            if ordered_ids is not None:
                self.persist_order(ordered_ids)

    def _event_template_id(self, event) -> int | None:
        if not event.mimeData().hasFormat(_RAIL_TEMPLATE_DRAG_MIME):
            return None
        try:
            return int(
                bytes(event.mimeData().data(_RAIL_TEMPLATE_DRAG_MIME)).decode("ascii")
            )
        except (TypeError, ValueError, UnicodeDecodeError):
            return None

    def _move_source_to_y(self, y: int) -> None:
        source = self._drag_source
        if source is None:
            return
        other_tiles = [tile for tile in self.tiles() if tile is not source]
        target = len(other_tiles)
        for index, tile in enumerate(other_tiles):
            if y < tile.geometry().center().y():
                target = index
                break
        desired = list(other_tiles)
        desired.insert(target, source)
        if desired == self.tiles():
            return
        self._animate_relayout(lambda: self._set_tile_order(desired))

    def _set_tile_order(self, ordered) -> None:
        by_id = {tile.template_id: tile for tile in self.tiles()}
        tiles = [by_id[item] if isinstance(item, int) else item for item in ordered]
        for index, tile in enumerate(tiles):
            self.dots_layout.removeWidget(tile)
            self.dots_layout.insertWidget(index, tile, 0, Qt.AlignHCenter)

    def _animate_relayout(self, mutation) -> None:
        if self._reorder_animation is not None:
            self._reorder_animation.stop()
            self._reorder_animation.deleteLater()
            self._reorder_animation = None
        moving_tiles = [tile for tile in self.tiles() if not tile.isHidden()]
        old_positions = {tile: tile.pos() for tile in moving_tiles}
        mutation()
        self.dots_layout.invalidate()
        self.dots_layout.activate()

        group = QParallelAnimationGroup(self)
        for tile in moving_tiles:
            if tile.isHidden():
                continue
            start = old_positions[tile]
            end = tile.pos()
            if start == end:
                continue
            tile.move(start)
            animation = QPropertyAnimation(tile, b"pos", group)
            animation.setDuration(_RAIL_REORDER_DURATION_MS)
            animation.setStartValue(start)
            animation.setEndValue(end)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(animation)
        if group.animationCount() == 0:
            group.deleteLater()
            return
        self._reorder_animation = group
        group.finished.connect(lambda: self._animation_finished(group))
        group.start()

    def _animation_finished(self, group: QParallelAnimationGroup) -> None:
        if self._reorder_animation is group:
            self._reorder_animation = None
        group.deleteLater()


def _build_collapsed_rail(app):
    rail = QWidget()
    rail.setObjectName("leftRailCollapsed")
    rail_layout = QVBoxLayout(rail)
    rail_layout.setContentsMargins(0, 0, 0, 0)
    rail_layout.setSpacing(10)

    expand_btn = QPushButton("»")
    expand_btn.setObjectName("railToggle")
    expand_btn.setToolTip("Expand")
    expand_btn.setFixedSize(44, 30)
    rail_layout.addWidget(expand_btn, 0, Qt.AlignHCenter)

    panel = QFrame()
    panel.setObjectName("panel")
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(6, 12, 6, 12)
    panel_layout.setSpacing(10)

    eyebrow = _VerticalRailLabel("TEMPLATES")
    eyebrow_font = eyebrow.font()
    eyebrow_font.setPointSize(8)
    eyebrow_font.setBold(True)
    eyebrow.setFont(eyebrow_font)
    panel_layout.addWidget(eyebrow, 0, Qt.AlignHCenter)

    dots_holder = _RailDotsHolder()
    dots_layout = dots_holder.dots_layout
    panel_layout.addWidget(dots_holder, 0, Qt.AlignHCenter)
    panel_layout.addStretch(1)

    # `railAdd`, not `primary`. `primary` is a text button and inherits the base
    # rule's `padding: 9px 14px`, which on a square pinned to 34px leaves a 6px
    # content box -- so the `+` came out squeezed into the middle at the app's
    # 12.5px body size, next to a `»` toggle that sets its own `padding: 0`.
    # Both states of this button are a glyph in a square: `+` here, an 18px
    # pencil in Scores mode. `railAdd` gives it the icon-square geometry the
    # rail's other two controls already have, in the primary blue.
    add_btn = QPushButton("+")
    add_btn.setObjectName("railAdd")
    add_btn.setToolTip("Add template")
    add_btn.setFixedSize(34, 34)
    panel_layout.addWidget(add_btn, 0, Qt.AlignHCenter)

    rail_layout.addWidget(panel, 1)

    rail._expand_btn = expand_btn
    rail._add_btn = add_btn
    rail._eyebrow = eyebrow
    rail._dots_holder = dots_holder
    rail._dots_layout = dots_layout
    return rail


def _rail_tile_stylesheet(color_hex: str, active: bool, *, dragging: bool = False) -> str:
    """An active tile is outlined in its own colour; an inactive one is not.

    The pre-toggle rail separated the two states by background alone (`#141A22`
    against `#0B0F14`), which is a difference of about three percent lightness
    and reads as nothing at 34px. Now that the tiles are the control rather
    than a legend, the border carries the state and the fill only supports it.
    """
    if dragging:
        return (
            "QPushButton#railTile{background:#0D1218;border:1px dashed #38495E;"
            "border-radius:9px;}"
        )
    if active:
        return (
            "QPushButton#railTile{background:#141A22;border:1px solid "
            + color_hex
            + ";border-radius:9px;}"
            "QPushButton#railTile:hover{background:#1B2430;}"
        )
    return (
        "QPushButton#railTile{background:#0B0F14;border:1px solid #1B222B;"
        "border-radius:9px;}"
        "QPushButton#railTile:hover{background:#141A22;border-color:#2E3A48;}"
    )


def _rail_dot_stylesheet(color_hex: str, active: bool) -> str:
    """The dot at full strength when active, faded when not.

    Percentage alpha rather than a pre-mixed hex: the tile fill differs between
    the two states, so a colour mixed against one of them would band on the
    other.
    """
    if not active:
        colour = QColor(color_hex)
        return (
            "background:rgba("
            f"{colour.red()},{colour.green()},{colour.blue()},35%);"
            "border-radius:4px;"
        )
    return f"background:{color_hex};border-radius:4px;"


def _on_rail_tile_toggled(panel, tile, dot, name, color_hex, is_scores, checked) -> None:
    """Mirror a tile's click onto the panel's checkbox, then restyle in place.

    Restyling in place avoids needless widget churn. The rail itself also keeps
    a stable order across rebuilds, so expanding and collapsing cannot move a
    template just because its active state changed.

    Persistence is the checkbox's, not ours -- `set_template_active` fires
    `save_checkbox_state`, `set_tier_active` fires `refresh_scores_ui`.
    """
    if is_scores:
        panel.set_tier_active(name, checked)
    else:
        panel.set_template_active(name, checked)
    tile.setStyleSheet(_rail_tile_stylesheet(color_hex, checked))
    dot.setStyleSheet(_rail_dot_stylesheet(color_hex, checked))


def _on_rail_action(app, rail) -> None:
    """The rail's bottom button: Add template, or Edit in Scores mode.

    Scores has nothing to add -- its expanded tab offers only Edit -- so the
    one button follows the mode. Both dialogs rebuild the panel's checkbox
    dicts, so the tiles are rebuilt after either returns; without that the rail
    would keep showing the pre-dialog set, missing a template that was just
    added.
    """
    if config.EVALUATION_MODE == "scores":
        app._templates_panel.open_scores_settings_dialog()
    else:
        app._templates_panel.add_template_dialog()
    _rebuild_rail_dots(rail, app)


def _on_rail_templates_reordered(app, rail, ordered_ids) -> None:
    """Persist a compact-rail drop without replacing its settling widgets."""
    if app._templates_panel.save_template_order(list(ordered_ids)):
        live_order = [tile.template_id for tile in rail._dots_holder.tiles()]
        if live_order != list(ordered_ids):
            _rebuild_rail_dots(rail, app)


def _rebuild_rail_dots(rail, app) -> None:
    """Repaint the rail for the mode it is showing, tiles and eyebrow both.

    The tiles are checkable buttons rather than the frames they were: the rail
    is a control now, and a template can be armed or disarmed without expanding
    the panel to reach its checkbox.
    """
    eyebrow_text, entries, is_scores = _rail_mode(app)
    rail._eyebrow.setText(eyebrow_text)
    # The eyebrow paints rotated, so its *height* is the text's width --
    # `sizeHint` recomputes from the new string only if geometry is invalidated.
    rail._eyebrow.updateGeometry()

    if is_scores:
        rail._add_btn.setText("")
        _apply_button_icon(rail._add_btn, "media/edit_icon.svg", 18)
        rail._add_btn.setToolTip("Edit score system")
    else:
        rail._add_btn.setIcon(QIcon())
        rail._add_btn.setText("+")
        rail._add_btn.setToolTip("Add template")

    _clear_layout(rail._dots_layout)
    panel = app._templates_panel
    rail._dots_holder.set_reorder_callback(
        None if is_scores else partial(_on_rail_templates_reordered, app, rail)
    )
    template_ids = (
        [] if is_scores else [int(template.get("id", 0)) for template in config.TEMPLATES]
    )
    for index, (name, color_hex, is_active) in enumerate(entries):
        template_id = None if is_scores else template_ids[index]
        tile = _DraggableRailTile(template_id)
        tile.color_hex = color_hex
        tile.setObjectName("railTile")
        tile.setCheckable(True)
        tile.setChecked(is_active)
        tile.setCursor(Qt.PointingHandCursor)
        tile.setFixedSize(34, 34)
        tile.setToolTip(
            name if is_scores else f"{name}\nDrag to reorder · Click to enable/disable"
        )
        tile.setStyleSheet(_rail_tile_stylesheet(color_hex, is_active))

        tile_layout = QHBoxLayout(tile)
        tile_layout.setContentsMargins(0, 0, 0, 0)
        tile_layout.setAlignment(Qt.AlignCenter)
        dot = QLabel()
        dot.setFixedSize(9, 9)
        # Without this the dot swallows the press and the tile never toggles:
        # it is a child widget sitting over the button's whole hit area.
        dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        dot.setStyleSheet(_rail_dot_stylesheet(color_hex, is_active))
        tile_layout.addWidget(dot)
        tile.dot = dot

        # `partial`, not a closure: every tile in this loop would otherwise
        # share the last `name` and `tile` the loop bound.
        tile.toggled.connect(
            partial(_on_rail_tile_toggled, panel, tile, dot, name, color_hex, is_scores)
        )
        rail._dots_layout.addWidget(tile, 0, Qt.AlignHCenter)


def _save_rail_collapsed(collapsed: bool) -> None:
    """Persist which of its two states the left column is in.

    Same three lines as `TemplatesPanel.save_checkbox_state`: the live module
    attribute, the dict that gets written, and the write.
    """
    config.LEFT_RAIL_COLLAPSED = collapsed
    config.user_config["LEFT_RAIL_COLLAPSED"] = collapsed
    config.save_config(config.user_config)


class _LeftRail:
    """Swap the left column between its full panel and its 52px icon rail.

    Collapsing clamps `left_panel` to a fixed width and remembers the
    splitter's proportions so expanding restores them; the icon dots are
    rebuilt on each collapse so they mirror the current template selection.
    """

    _COLLAPSED_WIDTH = 58

    def __init__(self, splitter, left_panel, expanded, collapsed, refresh) -> None:
        self._splitter = splitter
        self._left_panel = left_panel
        self._expanded = expanded
        self._collapsed = collapsed
        # A callable rather than the app: the rail swaps two widgets and knows
        # nothing else, and taking `app` here to reach one panel would give it
        # the whole window to reach anything.
        self._refresh = refresh
        self._expanded_sizes = None
        self._preferred_expanded_width = 290
        self._applying_preferred_width = False
        self._user_resized = False
        self.collapsed = False
        collapsed.hide()
        splitter.splitterMoved.connect(self._on_splitter_moved)

    def set_preferred_expanded_width(self, width: int) -> None:
        """Auto-fit until the user explicitly moves the splitter handle."""
        self._preferred_expanded_width = max(1, int(width))
        if self._user_resized:
            return

        current = self._expanded_sizes if self.collapsed else self._splitter.sizes()
        fitted = self._sizes_with_left_width(
            self._preferred_expanded_width, current=current
        )
        if self.collapsed:
            self._expanded_sizes = fitted
            return

        self._applying_preferred_width = True
        try:
            self._splitter.setSizes(fitted)
        finally:
            self._applying_preferred_width = False

    def _sizes_with_left_width(self, width: int, *, current=None) -> list[int]:
        """Give width released by the left side to the right side, and vice versa."""
        current = list(current if current is not None else self._splitter.sizes())
        total_width = sum(current[:2]) if len(current) >= 2 else 0
        total_width = max(total_width, int(width) + 1)
        return [int(width), max(1, total_width - int(width))]

    def _on_splitter_moved(self, *_args) -> None:
        if not self.collapsed and not self._applying_preferred_width:
            self._user_resized = True

    def toggle(self) -> None:
        self.expand() if self.collapsed else self.collapse()

    def collapse(self, *, restoring: bool = False) -> None:
        """Swap to the icon rail. `restoring` replays the saved state at startup.

        A restore differs from a click in both directions. It must not record
        `_expanded_sizes`, because the window has not been shown yet and the
        splitter would hand back provisional sizeHint widths that expanding
        would then impose as if the user had chosen them. And it must not save,
        because it is reproducing what was already saved.
        """
        if self.collapsed:
            return
        if not restoring:
            self._expanded_sizes = self._splitter.sizes()
        self._refresh()
        self._expanded.hide()
        self._collapsed.show()
        self.collapsed = True
        self._left_panel.setFixedWidth(self._COLLAPSED_WIDTH)
        self._splitter.setSizes(
            self._sizes_with_left_width(self._COLLAPSED_WIDTH)
        )
        if not restoring:
            _save_rail_collapsed(True)

    def expand(self) -> None:
        if not self.collapsed:
            return
        self._left_panel.setMinimumWidth(0)
        self._left_panel.setMaximumWidth(16777215)
        self._collapsed.hide()
        self._expanded.show()
        if self._expanded_sizes:
            self._splitter.setSizes(self._expanded_sizes)
        else:
            self._splitter.setSizes(
                self._sizes_with_left_width(self._preferred_expanded_width)
            )
        self.collapsed = False
        _save_rail_collapsed(False)


def _build_right_panel(app, splitter):
    right_panel = QWidget()
    right_layout = QVBoxLayout(right_panel)
    right_layout.setContentsMargins(0, 0, 0, 0)
    splitter.addWidget(right_panel)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    splitter.setSizes([290, 970])

    app.tabview = QTabWidget()
    app.tabview.setObjectName("mainTabs")
    app.tabview.tabBar().setExpanding(True)
    app.tabview.tabBar().setUsesScrollButtons(False)
    right_layout.addWidget(app.tabview, 1)

    return right_layout


def _build_logs_tab(app):
    app.tab_logs = QWidget()
    logs_layout = QVBoxLayout(app.tab_logs)
    logs_layout.setContentsMargins(0, 0, 0, 0)
    # `app.log_box` still names whatever the scanner's `log_box` port returns,
    # and the scanner still calls one method on it -- but that method is
    # `append_log` now rather than `insertHtml`, because the panel owns records
    # and derives the document from them. See `ui/log_view.py` for why.
    app.log_box = LogView()
    logs_layout.addWidget(app.log_box)
    app.tabview.addTab(app.tab_logs, "Logs")







def _build_header_controls(app, controls):
    # Two segments rather than one caption-swapping button. The size floors
    # this line used to carry -- `setMinimumWidth(210)` / `setMinimumHeight(38)`
    # over a button that measured 199x34 as `Start Scanner` and 194x37 as
    # `Stop Scanner` -- are gone with the disagreement that needed them: the
    # segments keep their own captions, so the control is one width in both
    # states and the header no longer twitches on start and stop.
    app.toggle_btn = ScannerToggle()
    app.toggle_btn.toggle_requested.connect(app._scanner.toggle_main_loop)
    controls.addWidget(app.toggle_btn)

    app.settings_btn = QPushButton("")
    app.settings_btn.setObjectName("iconBtn")
    _apply_button_icon(app.settings_btn, "media/settings_icon.png", 20)
    app.settings_btn.setToolTip("Settings")
    app.settings_btn.clicked.connect(app.open_settings_dialog)

    app.help_btn = QPushButton("")
    app.help_btn.setObjectName("iconBtn")
    _apply_button_icon(app.help_btn, "media/help_icon.svg", 20)
    app.help_btn.setToolTip("Help")
    app.help_btn.clicked.connect(app.open_help_dialog)

    controls.addWidget(app.help_btn)
    controls.addWidget(app.settings_btn)


def _build_tab_router(app):
    """Construct the tab-switch router and name its ten collaborators.

    The composition root for `TabRouter` (step 26), called from the first line
    of `setup_ui` -- before `_build_left_tabs` and `_build_right_panel`. The
    router therefore takes suppliers for objects created later; its signals
    are connected only after every tab has been registered.

    Six of the ten are late-bound suppliers, for the reason `TabRouter`'s
    header records: they name objects that do not exist yet at this line. The
    remaining four are real references to collaborators `gui_app.__init__`
    built before it called `setup_ui` -- the overlay component, the runtime
    filters, and two pieces of application surface that survive this step
    because `app/` and `gui_dialogs` call them on the application.

    `_recordings_list_view` is assigned here rather than in `gui_app.__init__`
    for the same reason `_build_recordings_view` registers its tab with
    `VodLibrary` here: the implementer does not exist until the layout is
    built. This assignment is what closes `recordings_list_view()`'s fallback
    to the app object -- scheduled for this step by
    `app/player_stats_view.py`'s docstring since step 19, and the last of the
    three port fallbacks that split created.
    """
    router = TabRouter(
        left_tabview=lambda: app.left_tabview,
        tabview=lambda: app.tabview,
        templates_panel=lambda: app._templates_panel,
        recordings_view=lambda: app._recordings_view,
        compare_runs_view=lambda: app._compare_runs_view,
        overlay=app._overlay,
        template_filters=app._template_filters,
        update_status=app.update_status_ui,
        refresh_live_player_stats=app.refresh_live_player_stats_now,
        schedule_idle=app.after_idle,
    )
    app._recordings_list_view = router
    return router


def _build_twitch_tab(app):
    """Construct the Twitch tab and add it to the right-hand tab bar.

    The composition root for `TwitchTab` (step 23b), kept at the exact point in
    `setup_ui` where `self._build_twitch_bot_tab()` used to be called, so the
    tab keeps its position and label in the tab bar.

    The tab takes no collaborators. It builds widgets and reports what is on
    them; every decision -- which config key a value lands in, whether a token
    is valid, when a worker starts -- belongs to the session object that step
    23c introduces, and `bind()` hands it the handlers later, from
    `gui_app.__init__`, where `setup_twitch_bot_ui` connected them before.

    `addTab` is here rather than in `build()` because the tab bar is not the
    tab's to know about: reaching `self.tabview` from inside the Twitch code is
    one of the seven ambient reads step 23 exists to remove.
    """
    from ui.tabs.twitch import TwitchTab

    view = TwitchTab()
    app.tabview.addTab(view.build(), "Twitch Bot")
    return view


def _build_templates_panel(app):
    """Construct the templates panel and name its nine collaborators.

    The composition root for `TemplatesPanel` (step 22c), kept at the exact
    point in `_build_left_panel` where the two tabs used to be built inline, so
    they keep their position and order in the left tab bar.

    Five of the eight are dialog factories. That is not ceremony: the layer
    table lets `ui/` import `app`, `projections` and `core`, and `gui_dialogs`
    is none of those. `ui/tabs/player_stats/recordings.py` reaches it through a
    `TOPLEVEL_DEBT` entry and that allowlist may only shrink, so the panel takes
    the dialogs as arguments and this module -- which is top-level and may
    import them freely -- supplies them. It is also what the roadmap asks for in
    as many words: shared dialogs passed as narrow UI dependencies rather than
    discovered through `self`.

    `sync_filters` points at the step-22b owner, not at the app's delegator, so
    the panel does not reach back through `MegabonkApp` to get to an object the
    app already holds.

    `window` is a supplier rather than the widget, for the reason
    `_build_recordings_view` records: this runs during `setup_ui`, and a
    captured `app.window` would freeze whatever it was at that moment.
    """
    from ui.tabs.templates import TemplatesPanel

    view = TemplatesPanel(
        left_tabview=app.left_tabview,
        window=lambda: app.window,
        sync_filters=app._template_filters.sync,
        template_dialog=TemplateDialog,
        template_manager_dialog=TemplateManagerDialog,
        delete_dialog=DeleteDialog,
        scores_settings_dialog=ScoresSettingsDialog,
        scores_help_dialog=ScoresHelpDialog,
        no_custom_templates_message=lambda parent: QMessageBox.information(
            parent, "No Custom Templates", "There are no custom templates to delete."
        ),
    )
    view.build()
    return view


def _build_compare_runs_view(app, timeline_series_slots):
    """Construct the Compare Runs tab and name its three collaborators.

    The composition root for `CompareRunsTab` (step 21d), kept at the exact
    point in `setup_ui` where `self._build_compare_runs_tab()` used to be
    called so the tab keeps its position in the tab bar.

    The ~250 lines that built this tab's widgets moved *into* the tab. They were
    here because step 9 split the tab out as a mixin and left its construction
    behind; `_build_compare_run_panel` even had to import `ItemsSectionView`
    inside its body to dodge the resulting import cycle. Both are gone.

    Fewer collaborators than `RecordingsTab` needs, and that is the
    measurement, not an oversight: this tab opens no dialogs, so it needs no
    `window`, and it reads no recorder. Its logger is only the failure sink for
    config persistence and malformed recording render boundaries.
    """
    from ui.tabs.compare_runs import CompareRunsTab

    view = CompareRunsTab(
        tabview=app.tabview,
        vod_library=app.vod_library,
        is_active=app._tab_router.is_compare_runs_tab_active,
        schedule=app.marshal_to_ui,
        timeline_series_slots=timeline_series_slots,
        log=app.log,
    )
    view.build()
    app.vod_library.subscribe(
        invalidate=view.invalidate_compare_runs_list,
        repaint=view.refresh_compare_runs_list,
    )
    return view


def _build_recordings_view(app, timeline_series_slots):
    """Construct the Recordings tab and name its six collaborators.

    The composition root for `RecordingsTab` (step 21c), kept at the exact point
    in `setup_ui` where `self._build_recordings_tab()` used to be called so the
    tab keeps its position in the tab bar.

    This is also where the tab is registered with `VodLibrary`. Registration
    cannot happen in `MegabonkApp.__init__` alongside the library itself: the
    tabs do not exist until `setup_ui` runs, and a subscriber list built before
    its subscribers is the ambient-namespace habit in a new spelling.

    `is_active` hands the tab the tab-bar question without handing it the
    router. It named `app._is_recordings_tab_active` until step 26 made the
    router an object; it names the router's own predicate now, which is the
    same answer from the object that owns the question rather than from a
    delegator the application only carried because the router lived on it.

    Imported inside the function body for the reason `_build_live_stats_view`
    records -- but read that reason as history now. `recordings` imported this
    module for its layout helpers, which made a module-scope import here a
    cycle; step 27b moved those helpers into
    `ui/tabs/player_stats/metrics.py`, a leaf of the tab package, so the cycle
    no longer exists and `recordings` imports the metrics directly. What is
    left is a deferral with nothing behind it. Promoting it is a decision with
    its own startup-order risk and no debt entry demanding it, so 27b records
    the change rather than making it.
    """
    from ui.tabs.player_stats import RecordingsTab

    view = RecordingsTab(
        tabview=app.tabview,
        vod_library=app.vod_library,
        window=lambda: app.window,
        vod_recorder=lambda: app.player_stats_vod_recorder,
        is_active=app._tab_router.is_recordings_tab_active,
        log=app.log,
        schedule=app.marshal_to_ui,
        timeline_series_slots=timeline_series_slots,
    )
    view.build()
    app.vod_library.subscribe(
        invalidate=view.invalidate_vods_list,
        repaint=view.refresh_vods_list,
        failed=view.on_vod_metadata_refresh_failed,
    )
    return view


def _build_live_stats_view(app):
    """Construct the Live Stats tab and name its ten collaborators.

    The composition root for `LiveStatsTab`, kept at the exact point in
    `_build_layout` where `_build_live_stats_tab()` used to be called so the
    tab keeps its position in the tab bar.

    Every argument is a supplier rather than a value, for the reason
    `RecordingTimelineView` records: `live_run_tracker` is assigned by
    `initialize_overlay_runtime` after `__init__` starts, `vod_capture`
    reassigns the snapshot list, and `player_stats_refresh` moves the selected
    index. A component holding the value would go stale exactly where the
    mixin reading `self` did not.

    Imported inside the function body: `live_stats` imported this module for
    its layout helpers, which made a module-scope import here the cycle step 19
    already shipped once -- invisible to the suite *and* to
    `test_import_direction`, because both analyse ASTs rather than importing.
    Step 27b split those helpers into `ui/tabs/player_stats/metrics.py` and
    `live_stats` now takes them at module level, so the cycle is gone. The
    deferral stays for the reason `_build_recordings_view` records: nothing
    requires removing it, and `test_deferred_imports` pins it as its live
    sample.
    """
    from ui.tabs.player_stats import LiveStatsTab

    def _select_snapshot(index, *, pinned):
        app.player_stats_selected_snapshot_index = index
        app.player_stats_snapshot_pinned = pinned

    view = LiveStatsTab(
        tabview=app.tabview,
        live_run_tracker=lambda: app.live_run_tracker,
        vod_recorder=lambda: app.player_stats_vod_recorder,
        vod_snapshots=lambda: app.player_stats_vod_snapshots,
        selected_snapshot_index=lambda: app.player_stats_selected_snapshot_index,
        recording_waiting_mode=lambda: vod_capture(app).recording_waiting_mode,
        ensure_live_snapshot_store=lambda: live_snapshot_store(app),
        is_recording_armed=lambda: vod_capture(app).is_recording_armed(),
        on_toggle_recording=lambda: vod_capture(app).toggle_recording(),
        on_snapshot_selected=_select_snapshot,
        build_progression_snapshot=lambda: app.coordinator.build_progression_service.snapshot(),
        open_build_progression_settings=lambda: _open_build_progression_settings(app),
    )
    return view.build()


def _open_build_progression_settings(app) -> None:
    from ui.dialogs.build_progression import BuildProgressionManagerDialog

    dialog = BuildProgressionManagerDialog(
        app.coordinator.build_progression_settings,
        app.coordinator.build_progression_service,
        getattr(app, "window", None),
    )
    dialog.exec()
    if dialog.changed:
        view = getattr(app, "_player_stats_view", None)
        if view is not None:
            view.refresh_build_progression()
