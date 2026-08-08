from __future__ import annotations

from unittest.mock import patch

import src  # noqa: F401 -- path bootstrap
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget

from app import config
from core.template_colors import template_color_hex, template_color_hex_or_none
from ui.dialogs import DeleteDialog, TemplateFormFrame
from tests.support.templates_panel import build_templates_panel


def test_custom_hex_colors_are_normalized_and_resolved() -> None:
    assert template_color_hex("#a1b2c3") == "#A1B2C3"
    assert template_color_hex_or_none("#a1b2c3") == "#A1B2C3"
    assert template_color_hex_or_none("#not-a-color") is None


def test_an_intentionally_empty_template_config_stays_empty() -> None:
    assert config.normalize_templates_config([]) == []
    defaults = config.normalize_templates_config(None)
    assert defaults == config.DEFAULT_TEMPLATES
    assert defaults is not config.DEFAULT_TEMPLATES
    assert defaults[0] is not config.DEFAULT_TEMPLATES[0]


def test_templates_panel_builds_approved_single_line_rows(qtbot) -> None:
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    panel = build_templates_panel(left_tabview=tabs)
    templates = [
        {"id": 1, "name": "LIGHT", "color": "WHITE", "sm_total": 7, "micro": 2},
        {"id": 9, "name": "Custom", "color": "#123456", "boss": 3},
    ]
    with patch.object(config, "TEMPLATES", templates):
        with patch.object(config, "ACTIVE_TEMPLATES", ["LIGHT"]):
            panel.build()
            panel.refresh_templates()

    rows = panel._template_surface.rows()
    assert [row.height() for row in rows] == [48, 48]
    assert [row.name_label.text() for row in rows] == ["LIGHT", "Custom"]
    assert all("\n" not in row.conditions_label.text() for row in rows)


def test_templates_panel_reports_a_capped_content_width_and_elides_overflow(qtbot) -> None:
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    panel = build_templates_panel(left_tabview=tabs)
    templates = [
        {"id": 1, "name": "SHORT", "color": "WHITE", "boss": 1},
        {
            "id": 2,
            "name": "LONG",
            "color": "CYAN",
            "sm_total": 123,
            "micro": 45,
            "boss": 67,
            "magnet": 89,
        },
    ]
    measured = []
    with patch.object(config, "TEMPLATES", templates):
        with patch.object(config, "ACTIVE_TEMPLATES", []):
            panel.build()
            panel.set_preferred_width_changed(measured.append)
            panel.refresh_templates()

    assert measured == [420]
    tabs.resize(measured[0], 240)
    tabs.show()
    qtbot.wait(1)
    short_row, long_row = panel._template_surface.rows()
    assert short_row.conditions_label.toolTip() == ""
    assert long_row.conditions_label.text().endswith("…")
    assert long_row.conditions_label.toolTip() == long_row.conditions_label.full_text


def test_drag_can_start_from_the_whole_template_row(qtbot) -> None:
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    panel = build_templates_panel(left_tabview=tabs)
    template = {"id": 1, "name": "LIGHT", "color": "WHITE"}
    with patch.object(config, "TEMPLATES", [template]):
        with patch.object(config, "ACTIVE_TEMPLATES", []):
            panel.build()
            panel.refresh_templates()

    tabs.resize(560, 240)
    tabs.show()
    row = panel._template_surface.rows()[0]
    with patch.object(row, "start_drag") as start_drag:
        qtbot.mousePress(row, Qt.LeftButton, pos=QPoint(180, 24))
        qtbot.mouseMove(row, pos=QPoint(230, 24))
        qtbot.mouseRelease(row, Qt.LeftButton, pos=QPoint(230, 24))

    start_drag.assert_called_once_with()


def test_drag_source_becomes_an_empty_placeholder_until_drag_finishes(qtbot) -> None:
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    panel = build_templates_panel(left_tabview=tabs)
    template = {"id": 1, "name": "LIGHT", "color": "WHITE"}
    with patch.object(config, "TEMPLATES", [template]):
        with patch.object(config, "ACTIVE_TEMPLATES", []):
            panel.build()
            panel.refresh_templates()

    row = panel._template_surface.rows()[0]
    content = (row.drag_handle, row.checkbox, row.name_label, row.conditions_label)
    hidden_during_drag = []
    with patch("ui.tabs.templates.panel.QDrag") as drag_type:
        drag_type.return_value.exec.side_effect = lambda _action: hidden_during_drag.append(
            [widget.isHidden() for widget in content]
        )
        row.start_drag()

    assert hidden_during_drag == [[True, True, True, True]]
    assert [widget.isHidden() for widget in content] == [False, False, False, False]


def test_live_drag_moves_the_slot_and_animates_neighbouring_rows(qtbot) -> None:
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    panel = build_templates_panel(left_tabview=tabs)
    templates = [
        {"id": 1, "name": "One", "color": "WHITE"},
        {"id": 2, "name": "Two", "color": "CYAN"},
        {"id": 3, "name": "Three", "color": "GREEN"},
    ]
    with patch.object(config, "TEMPLATES", templates):
        with patch.object(config, "ACTIVE_TEMPLATES", []):
            panel.build()
            panel.refresh_templates()

    tabs.resize(420, 300)
    tabs.show()
    qtbot.wait(1)
    surface = panel._template_surface
    first, second, _third = surface.rows()
    second_start_y = second.y()

    surface.begin_live_drag(first)
    surface._move_source_to_y(surface.height())

    assert [row.template_id for row in surface.rows()] == [2, 3, 1]
    assert first.isHidden() is True
    assert surface._reorder_animation is not None
    assert {
        surface._reorder_animation.animationAt(index).duration()
        for index in range(surface._reorder_animation.animationCount())
    } == {140}
    qtbot.wait(160)
    assert second.y() < second_start_y

    surface.finish_live_drag(False)
    qtbot.wait(160)
    assert [row.template_id for row in surface.rows()] == [1, 2, 3]
    assert first.isHidden() is False


def test_drop_event_reorders_and_persists_templates(qtbot) -> None:
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    panel = build_templates_panel(left_tabview=tabs)
    templates = [
        {"id": 1, "name": "One", "color": "WHITE"},
        {"id": 2, "name": "Two", "color": "CYAN"},
        {"id": 3, "name": "Three", "color": "GREEN"},
    ]
    with patch.object(config, "TEMPLATES", templates):
        with patch.object(config, "ACTIVE_TEMPLATES", []):
            with patch.dict(config.user_config, {"TEMPLATES": templates}, clear=False):
                with patch.object(config, "save_config") as save_config:
                    panel.build()
                    panel.refresh_templates()
                    tabs.resize(560, 300)
                    tabs.show()
                    qtbot.wait(1)

                    surface = panel._template_surface
                    mime = QMimeData()
                    mime.setData("application/x-megabonk-template-id", b"1")
                    target = QPoint(100, surface.height() - 4)
                    QApplication.sendEvent(
                        surface,
                        QDragEnterEvent(
                            target,
                            Qt.MoveAction,
                            mime,
                            Qt.LeftButton,
                            Qt.NoModifier,
                        ),
                    )
                    QApplication.sendEvent(
                        surface,
                        QDragMoveEvent(
                            target,
                            Qt.MoveAction,
                            mime,
                            Qt.LeftButton,
                            Qt.NoModifier,
                        ),
                    )
                    QApplication.sendEvent(
                        surface,
                        QDropEvent(
                            QPointF(target),
                            Qt.MoveAction,
                            mime,
                            Qt.LeftButton,
                            Qt.NoModifier,
                        ),
                    )
                    reordered = [template["id"] for template in config.TEMPLATES]
                    checkbox_order = list(panel._checkboxes)

    assert reordered == [2, 3, 1]
    assert checkbox_order == ["Two", "Three", "One"]
    save_config.assert_called_once_with(config.user_config)


def test_template_form_saves_a_system_dialog_color(qtbot) -> None:
    form = TemplateFormFrame(template_data={"id": 9, "name": "Custom", "color": "BLUE"})
    qtbot.addWidget(form)

    with patch("ui.dialogs.QColorDialog.getColor", return_value=QColor("#123456")):
        form._choose_color()

    assert form.get_payload()["color"] == "#123456"


def test_reset_color_uses_the_shipped_builtin_color(qtbot) -> None:
    form = TemplateFormFrame(
        template_data={"id": 1, "name": "LIGHT", "color": "#123456"}
    )
    qtbot.addWidget(form)

    form._reset_color()

    assert form.get_payload()["color"] == "WHITE"


def test_invalid_saved_color_falls_back_before_the_form_is_saved(qtbot) -> None:
    form = TemplateFormFrame(
        template_data={"id": 9, "name": "Custom", "color": "not-a-color"}
    )
    qtbot.addWidget(form)

    assert form.get_payload()["color"] == "BLUE"


def test_template_form_keeps_blank_and_zero_maximum_distinct(qtbot) -> None:
    form = TemplateFormFrame(
        template_data={
            "id": 9,
            "name": "Strict",
            "magnet_max": 0,
        }
    )
    qtbot.addWidget(form)

    assert form.magnet_max_entry.text() == "0"
    assert form.challenges_max_entry.text() == ""
    payload = form.get_payload()
    assert payload["magnet_max"] == 0
    assert "challenges_max" not in payload


def test_template_form_saves_challenges_and_rejects_invalid_range(qtbot) -> None:
    form = TemplateFormFrame(template_data={"id": 9, "name": "Strict"})
    qtbot.addWidget(form)
    form.challenges_entry.setText("2")
    form.challenges_max_entry.setText("3")

    payload = form.get_payload()
    assert payload["challenges"] == 2
    assert payload["challenges_max"] == 3

    form.challenges_max_entry.setText("1")
    assert form.get_payload() is None


def test_delete_dialog_can_remove_a_builtin_and_cleans_active_names(qtbot) -> None:
    templates = [
        {"id": 1, "name": "LIGHT", "color": "WHITE"},
        {"id": 9, "name": "Custom", "color": "BLUE"},
    ]
    active = ["LIGHT", "Custom"]
    with patch.object(config, "TEMPLATES", templates):
        with patch.object(config, "ACTIVE_TEMPLATES", active):
            with patch.dict(config.user_config, {}, clear=False):
                with patch.object(config, "save_config") as save_config:
                    dialog = DeleteDialog(None, templates)
                    qtbot.addWidget(dialog)
                    dialog.checks[1].setChecked(True)
                    dialog.delete()
                    remaining = list(config.TEMPLATES)
                    active_after = list(config.ACTIVE_TEMPLATES)

    assert [template["id"] for template in remaining] == [9]
    assert active_after == ["Custom"]
    assert dialog.result() == QDialog.Accepted
    save_config.assert_called_once_with(config.user_config)


def test_restore_adds_only_missing_builtins_to_the_end_and_keeps_them_inactive(qtbot) -> None:
    custom = {"id": 9, "name": "Custom", "color": "#123456"}
    existing_builtin = dict(config.DEFAULT_TEMPLATES[2])
    templates = [custom, existing_builtin]
    active = ["Custom"]
    with patch.object(config, "TEMPLATES", templates):
        with patch.object(config, "ACTIVE_TEMPLATES", active):
            with patch.dict(config.user_config, {}, clear=False):
                with patch.object(config, "save_config") as save_config:
                    dialog = DeleteDialog(None, templates)
                    qtbot.addWidget(dialog)
                    dialog.restore_builtins()
                    restored = list(config.TEMPLATES)
                    active_after = list(config.ACTIVE_TEMPLATES)

    assert [template["id"] for template in restored] == [9, 3, 1, 2, 4, 5, 6, 7]
    assert active_after == ["Custom"]
    assert dialog.result() == QDialog.Accepted
    save_config.assert_called_once_with(config.user_config)
