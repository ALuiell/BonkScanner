from __future__ import annotations

from unittest.mock import patch

import src  # noqa: F401 -- path bootstrap
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QTabWidget

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
    assert [row.height() for row in rows] == [62, 62]
    assert [row.name_label.text() for row in rows] == ["LIGHT", "Custom"]
    assert all("\n" not in row.conditions_label.text() for row in rows)


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
