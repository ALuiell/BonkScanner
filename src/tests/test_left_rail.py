from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from app import config
from ui.layout import (
    _LeftRail,
    _build_collapsed_rail,
    _rebuild_rail_dots,
    _template_rail_entries,
)


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _FakeSplitter:
    def __init__(self) -> None:
        self.splitterMoved = _Signal()
        self.current_sizes = [290, 970]
        self.set_calls = []

    def sizes(self):
        return list(self.current_sizes)

    def setSizes(self, sizes) -> None:
        self.current_sizes = list(sizes)
        self.set_calls.append(list(sizes))
        if self.splitterMoved.callback is not None:
            self.splitterMoved.callback(sizes[0], 1)


class _FakeRailWidget:
    def __init__(self) -> None:
        self.fixed_width = None

    def hide(self) -> None:
        pass

    def show(self) -> None:
        pass

    def setFixedWidth(self, width) -> None:
        self.fixed_width = width

    def setMinimumWidth(self, _width) -> None:
        pass

    def setMaximumWidth(self, _width) -> None:
        pass


class _RecordingTemplatesPanel:
    def __init__(self) -> None:
        self.active_calls = []
        self.saved_orders = []

    def set_template_active(self, name, checked) -> None:
        self.active_calls.append((name, checked))

    def save_template_order(self, ordered_ids) -> bool:
        ordered_ids = list(ordered_ids)
        self.saved_orders.append(ordered_ids)
        by_id = {template["id"]: template for template in config.TEMPLATES}
        config.TEMPLATES = [by_id[template_id] for template_id in ordered_ids]
        return True


class LeftRailTests(unittest.TestCase):
    def test_content_auto_fit_stops_after_a_manual_splitter_move(self) -> None:
        splitter = _FakeSplitter()
        rail = _LeftRail(
            splitter,
            SimpleNamespace(),
            SimpleNamespace(),
            _FakeRailWidget(),
            lambda: None,
        )

        rail.set_preferred_expanded_width(410)
        splitter.splitterMoved.callback(395, 1)
        rail.set_preferred_expanded_width(380)

        self.assertEqual(splitter.set_calls, [[410, 850]])

    def test_collapse_releases_the_expanded_width_and_expand_restores_it(self) -> None:
        splitter = _FakeSplitter()
        splitter.current_sizes = [420, 1000]
        left_panel = _FakeRailWidget()
        expanded = _FakeRailWidget()
        collapsed = _FakeRailWidget()
        rail = _LeftRail(
            splitter,
            left_panel,
            expanded,
            collapsed,
            lambda: None,
        )

        with patch("ui.layout._save_rail_collapsed"):
            rail.collapse()
            collapsed_sizes = list(splitter.current_sizes)
            rail.expand()

        self.assertEqual(left_panel.fixed_width, 58)
        self.assertEqual(collapsed_sizes, [58, 1362])
        self.assertEqual(splitter.current_sizes, [420, 1000])

    def test_template_tiles_keep_panel_order_and_include_inactive_entries(self) -> None:
        templates = [
            {"name": "LIGHT", "color": "WHITE"},
            {"name": "MERCHANT", "color": "CYAN"},
            {"name": "GOOD", "color": "GREEN"},
            {"name": "PERFECT", "color": "YELLOW"},
        ]

        with patch.object(config, "TEMPLATES", templates), patch.object(
            config, "ACTIVE_TEMPLATES", ["PERFECT", "LIGHT"]
        ):
            entries = _template_rail_entries()

        self.assertEqual(
            [(name, active) for name, _colour, active in entries],
            [
                ("LIGHT", True),
                ("MERCHANT", False),
                ("GOOD", False),
                ("PERFECT", True),
            ],
        )


def _template_rail(qtbot):
    panel = _RecordingTemplatesPanel()
    app = SimpleNamespace(_templates_panel=panel)
    rail = _build_collapsed_rail(app)
    qtbot.addWidget(rail)
    _rebuild_rail_dots(rail, app)
    rail.resize(58, 360)
    rail.show()
    qtbot.wait(1)
    return rail, panel


def test_collapsed_template_tile_still_toggles_on_a_normal_click(qtbot) -> None:
    templates = [{"id": 1, "name": "One", "color": "WHITE"}]
    with patch.object(config, "EVALUATION_MODE", "templates"):
        with patch.object(config, "TEMPLATES", templates):
            with patch.object(config, "ACTIVE_TEMPLATES", []):
                rail, panel = _template_rail(qtbot)
                qtbot.mouseClick(rail._dots_holder.tiles()[0], Qt.LeftButton)

    assert panel.active_calls == [("One", True)]


def test_collapsed_template_tile_starts_drag_after_mouse_threshold(qtbot) -> None:
    templates = [{"id": 1, "name": "One", "color": "WHITE"}]
    with patch.object(config, "EVALUATION_MODE", "templates"):
        with patch.object(config, "TEMPLATES", templates):
            with patch.object(config, "ACTIVE_TEMPLATES", []):
                rail, _panel = _template_rail(qtbot)
                tile = rail._dots_holder.tiles()[0]
                with patch.object(tile, "start_drag") as start_drag:
                    qtbot.mousePress(tile, Qt.LeftButton, pos=QPoint(8, 17))
                    qtbot.mouseMove(tile, pos=QPoint(28, 17))
                    qtbot.mouseRelease(tile, Qt.LeftButton, pos=QPoint(28, 17))

    start_drag.assert_called_once_with()


def test_collapsed_rail_drop_reorders_tiles(qtbot) -> None:
    templates = [
        {"id": 1, "name": "One", "color": "WHITE"},
        {"id": 2, "name": "Two", "color": "CYAN"},
        {"id": 3, "name": "Three", "color": "GREEN"},
    ]
    with patch.object(config, "EVALUATION_MODE", "templates"):
        with patch.object(config, "TEMPLATES", templates):
            with patch.object(config, "ACTIVE_TEMPLATES", []):
                rail, panel = _template_rail(qtbot)
                holder = rail._dots_holder
                mime = QMimeData()
                mime.setData("application/x-megabonk-template-id", b"1")
                target = QPoint(17, holder.height() - 2)
                QApplication.sendEvent(
                    holder,
                    QDragEnterEvent(
                        target, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
                    ),
                )
                QApplication.sendEvent(
                    holder,
                    QDragMoveEvent(
                        target, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
                    ),
                )
                QApplication.sendEvent(
                    holder,
                    QDropEvent(
                        QPointF(target),
                        Qt.MoveAction,
                        mime,
                        Qt.LeftButton,
                        Qt.NoModifier,
                    ),
                )
                tile_ids = [tile.template_id for tile in rail._dots_holder.tiles()]

    assert panel.saved_orders == [[2, 3, 1]]
    assert tile_ids == [2, 3, 1]


def test_collapsed_drag_hides_the_source_dot_until_drag_finishes(qtbot) -> None:
    templates = [{"id": 1, "name": "One", "color": "WHITE"}]
    with patch.object(config, "EVALUATION_MODE", "templates"):
        with patch.object(config, "TEMPLATES", templates):
            with patch.object(config, "ACTIVE_TEMPLATES", []):
                rail, _panel = _template_rail(qtbot)
                tile = rail._dots_holder.tiles()[0]
                hidden_during_drag = []
                with patch("ui.layout.QDrag") as drag_type:
                    drag_type.return_value.exec.side_effect = (
                        lambda _action: hidden_during_drag.append(tile.dot.isHidden())
                    )
                    tile.start_drag()

    assert hidden_during_drag == [True]
    assert tile.dot.isHidden() is False


def test_collapsed_live_drag_moves_the_slot_and_animates_neighbours(qtbot) -> None:
    templates = [
        {"id": 1, "name": "One", "color": "WHITE"},
        {"id": 2, "name": "Two", "color": "CYAN"},
        {"id": 3, "name": "Three", "color": "GREEN"},
    ]
    with patch.object(config, "EVALUATION_MODE", "templates"):
        with patch.object(config, "TEMPLATES", templates):
            with patch.object(config, "ACTIVE_TEMPLATES", []):
                rail, _panel = _template_rail(qtbot)
                holder = rail._dots_holder
                first, second, _third = holder.tiles()
                second_start_y = second.y()

                holder.begin_live_drag(first)
                holder._move_source_to_y(holder.height())

                assert [tile.template_id for tile in holder.tiles()] == [2, 3, 1]
                assert first.isHidden() is True
                assert holder._reorder_animation is not None
                assert {
                    holder._reorder_animation.animationAt(index).duration()
                    for index in range(holder._reorder_animation.animationCount())
                } == {140}
                qtbot.wait(160)
                assert second.y() < second_start_y

                holder.finish_live_drag(False)
                qtbot.wait(160)

    assert [tile.template_id for tile in holder.tiles()] == [1, 2, 3]
    assert first.isHidden() is False
