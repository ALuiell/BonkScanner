"""`ui.tabs.templates.TemplatesPanel` -- what step 22c converted.

Three tests here came whole from `test_gui_run_control.py`, where each needed
`object.__new__(MegabonkApp)` to reach a mixin method. They call the panel's
real constructor now, which is the migration the componentization plan
describes: a call site is migrated by the step that converts its subject.

Widgets are assigned directly rather than built. `build()` needs real offscreen
Qt and is driven by `tools/step22_templates_trace.py`.
"""

from __future__ import annotations

import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app import config
from app.template_filters import TemplateRuntimeFilters
from tests.support.templates_panel import RecordingDialog, build_templates_panel


class FakeCheckbox:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def get(self) -> bool:
        return self._checked


class FakeLayout:
    """Enough of a QLayout for `_clear_layout` and the two `add*` calls."""

    def __init__(self) -> None:
        self.widgets = []
        self.stretches = 0

    def count(self) -> int:
        return 0

    def takeAt(self, _index):
        return None

    def addWidget(self, widget) -> None:
        self.widgets.append(widget)

    def addStretch(self, _factor) -> None:
        self.stretches += 1


class FakeAliveThread:
    def is_alive(self) -> bool:
        return True


def _panel_with_filters(**filter_ports):
    """A panel whose `sync_filters` is a real `TemplateRuntimeFilters`.

    The panel supplies `selected_template_names` to the filters, and the filters
    are what the panel calls back into -- that loop is the seam step 22 built,
    so both halves are real here.
    """
    holder = {}

    def selected():
        return holder["panel"].selected_template_names()

    ports = {
        "selected_template_names": selected,
        "refresh_stats": lambda: None,
        "log": lambda _message: None,
        "is_scanning": lambda: False,
    }
    ports.update(filter_ports)
    filters = TemplateRuntimeFilters(**ports)
    panel = build_templates_panel(sync_filters=filters.sync)
    holder["panel"] = panel
    return panel, filters


class CheckboxSyncTests(unittest.TestCase):
    def test_save_checkbox_state_updates_runtime_templates_without_restart(self) -> None:
        """Moved from `test_gui_run_control.py` by step 22c."""
        logs: list[str] = []
        panel, filters = _panel_with_filters(
            log=logs.append,
            is_scanning=lambda: True,
        )
        panel._checkboxes = {
            "Alpha": FakeCheckbox(True),
            "Beta": FakeCheckbox(False),
            "Gamma": FakeCheckbox(True),
        }
        filters.active_templates = ["Alpha"]
        filters.template_stats = {
            "Alpha": {"rerolls_since_last": 2, "history": [3]},
            "Beta": {"rerolls_since_last": 1, "history": [4]},
        }

        original_active = list(config.ACTIVE_TEMPLATES)
        try:
            with patch.object(config, "EVALUATION_MODE", "templates"):
                with patch.object(config, "save_config") as save_config:
                    panel.save_checkbox_state()

            self.assertEqual(config.ACTIVE_TEMPLATES, ["Alpha", "Gamma"])
            self.assertEqual(filters.active_templates, ["Alpha", "Gamma"])
            self.assertEqual(filters.template_stats["Alpha"]["history"], [3])
            self.assertEqual(
                filters.template_stats["Gamma"], {"rerolls_since_last": 0, "history": []}
            )
            self.assertEqual(
                filters.template_stats["Beta"], {"rerolls_since_last": 1, "history": [4]}
            )
            self.assertEqual(logs, ["[*] Active templates updated live: Alpha, Gamma"])
            save_config.assert_called_once_with(config.user_config)
        finally:
            config.ACTIVE_TEMPLATES = original_active

    def test_unchecking_removes_the_template_from_active_templates(self) -> None:
        """The mutation the step's verification list names."""
        panel, filters = _panel_with_filters()
        panel._checkboxes = {"Alpha": FakeCheckbox(True), "Beta": FakeCheckbox(True)}

        original_active = list(config.ACTIVE_TEMPLATES)
        try:
            with patch.object(config, "EVALUATION_MODE", "templates"):
                with patch.object(config, "save_config"):
                    panel.save_checkbox_state()
                    self.assertEqual(filters.active_templates, ["Alpha", "Beta"])

                    panel._checkboxes["Beta"] = FakeCheckbox(False)
                    panel.save_checkbox_state()

            self.assertEqual(filters.active_templates, ["Alpha"])
        finally:
            config.ACTIVE_TEMPLATES = original_active

    def test_an_empty_template_list_selects_nothing(self) -> None:
        """Empty state: no templates configured at all."""
        panel, filters = _panel_with_filters()
        panel._checkboxes = {}
        self.assertEqual(panel.selected_template_names(), [])

        original_active = list(config.ACTIVE_TEMPLATES)
        try:
            with patch.object(config, "EVALUATION_MODE", "templates"):
                with patch.object(config, "save_config"):
                    panel.save_checkbox_state()
            self.assertEqual(filters.active_templates, [])
        finally:
            config.ACTIVE_TEMPLATES = original_active


class ScoresTests(unittest.TestCase):
    def test_refresh_scores_ui_updates_runtime_tiers_without_restart(self) -> None:
        """Moved from `test_gui_run_control.py` by step 22c."""
        rendered: list[str] = []
        logs: list[str] = []
        panel, filters = _panel_with_filters(log=logs.append, is_scanning=lambda: True)
        panel._scores_desc_label = SimpleNamespace(setHtml=rendered.append)
        panel._scores_checkboxes = {
            "Light": FakeCheckbox(True),
            "Good": FakeCheckbox(False),
            "Perfect": FakeCheckbox(True),
            "Perfect+": FakeCheckbox(False),
        }
        filters.template_stats = {"Good": {"rerolls_since_last": 4, "history": [2]}}

        original_scores = deepcopy(config.SCORES_SYSTEM)
        updated_scores = deepcopy(config.SCORES_SYSTEM)
        updated_scores["active_tiers"] = ["Good"]
        config.SCORES_SYSTEM = updated_scores
        config.user_config["SCORES_SYSTEM"] = updated_scores
        try:
            with patch.object(config, "EVALUATION_MODE", "scores"):
                with patch.object(config, "save_config") as save_config:
                    panel.refresh_scores_ui()

            self.assertEqual(config.SCORES_SYSTEM["active_tiers"], ["Light", "Perfect"])
            self.assertEqual(
                filters.template_stats,
                {
                    "Good": {"rerolls_since_last": 4, "history": [2]},
                    "Light": {"rerolls_since_last": 0, "history": []},
                    "Perfect": {"rerolls_since_last": 0, "history": []},
                },
            )
            self.assertEqual(logs, ["[*] Active tiers updated live: Light, Perfect"])
            save_config.assert_called_once_with(config.user_config)
        finally:
            config.SCORES_SYSTEM = original_scores
            config.user_config["SCORES_SYSTEM"] = original_scores

        # The tier order and colours are what the description renders from.
        self.assertEqual(len(rendered), 1)
        self.assertIn("Light, Perfect", rendered[0])

    def test_refresh_scores_ui_is_a_no_op_before_the_label_exists(self) -> None:
        panel, _filters = _panel_with_filters()
        panel._scores_desc_label = None
        with patch.object(config, "save_config") as save_config:
            panel.refresh_scores_ui()
        save_config.assert_not_called()

    def test_an_empty_tier_selection_writes_no_config(self) -> None:
        """Empty state: every tier unchecked. The `if active_tiers` guard."""
        rendered: list[str] = []
        panel, _filters = _panel_with_filters()
        panel._scores_desc_label = SimpleNamespace(setHtml=rendered.append)
        panel._scores_checkboxes = {tier: FakeCheckbox(False) for tier in
                                    ("Light", "Good", "Perfect", "Perfect+")}

        with patch.object(config, "EVALUATION_MODE", "scores"):
            with patch.object(config, "save_config") as save_config:
                panel.refresh_scores_ui()
        save_config.assert_not_called()
        self.assertEqual(len(rendered), 1)


class DialogTests(unittest.TestCase):
    def test_edit_template_dialog_opens_template_manager(self) -> None:
        """Moved from `test_gui_run_control.py` by step 22c."""
        opened: list[object] = []
        dialog = RecordingDialog()
        window = SimpleNamespace()
        calls: list[tuple] = []

        def manager(parent, templates, apply):
            calls.append((parent, templates, apply))
            return dialog

        panel = build_templates_panel(
            window=lambda: window,
            template_manager_dialog=manager,
        )
        templates = [{"id": 1, "name": "LIGHT"}]

        with patch.object(config, "TEMPLATES", templates):
            panel.edit_template_dialog()

        self.assertEqual(calls, [(window, templates, panel.apply_template_edit)])
        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(opened, [])

    def test_a_cancelled_add_writes_no_config(self) -> None:
        from PySide6.QtWidgets import QDialog

        dialog = RecordingDialog(result=QDialog.Rejected)
        panel = build_templates_panel(template_dialog=lambda _parent: dialog)

        with patch.object(config, "save_config") as save_config:
            panel.add_template_dialog()
        save_config.assert_not_called()
        self.assertEqual(dialog.exec_calls, 1)

    def test_an_accepted_add_with_no_payload_writes_no_config(self) -> None:
        """`Accepted` and `result_payload is None` is a real path, not a typo."""
        from PySide6.QtWidgets import QDialog

        dialog = RecordingDialog(result=QDialog.Accepted, result_payload=None)
        panel = build_templates_panel(template_dialog=lambda _parent: dialog)

        with patch.object(config, "save_config") as save_config:
            panel.add_template_dialog()
        save_config.assert_not_called()

    def test_a_cancelled_delete_does_not_refresh(self) -> None:
        from PySide6.QtWidgets import QDialog

        dialog = RecordingDialog(result=QDialog.Rejected)
        panel = build_templates_panel(delete_dialog=lambda _parent, _templates: dialog)
        panel._template_layout = FakeLayout()

        with patch.object(config, "TEMPLATES", [{"id": 9, "name": "Custom"}]):
            panel.del_template_dialog()

        self.assertEqual(dialog.exec_calls, 1)
        # `refresh_templates` would have added the stretch.
        self.assertEqual(panel._template_layout.stretches, 0)

    def test_delete_with_no_custom_templates_says_so_and_opens_nothing(self) -> None:
        """Empty state: only the shipped defaults exist."""
        told: list[object] = []
        panel = build_templates_panel(no_custom_templates_message=told.append)

        with patch.object(config, "TEMPLATES", [{"id": 1, "name": "LIGHT"}]):
            panel.del_template_dialog()

        self.assertEqual(len(told), 1)

    def test_a_cancelled_scores_settings_dialog_does_not_repaint(self) -> None:
        from PySide6.QtWidgets import QDialog

        dialog = RecordingDialog(result=QDialog.Rejected)
        rendered: list[str] = []
        panel = build_templates_panel(scores_settings_dialog=lambda _parent: dialog)
        panel._scores_desc_label = SimpleNamespace(setHtml=rendered.append)

        panel.open_scores_settings_dialog()

        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(rendered, [])


class TemplateEditTests(unittest.TestCase):
    def test_apply_template_edit_renames_in_active_templates(self) -> None:
        panel, _filters = _panel_with_filters()
        panel._template_layout = FakeLayout()

        templates = [{"id": 1, "name": "OLD", "color": "GREEN"}]
        original_active = list(config.ACTIVE_TEMPLATES)
        try:
            with patch.object(config, "TEMPLATES", templates):
                with patch.object(config, "ACTIVE_TEMPLATES", ["OLD"]):
                    with patch.object(config, "save_config"):
                        applied = panel.apply_template_edit(
                            {"id": 1, "name": "OLD"},
                            {"name": "NEW", "color": "GREEN"},
                        )
                    self.assertTrue(applied)
                    self.assertEqual(config.ACTIVE_TEMPLATES, ["NEW"])
                    self.assertEqual(config.TEMPLATES[0]["name"], "NEW")
                    self.assertEqual(config.TEMPLATES[0]["id"], 1)
        finally:
            config.ACTIVE_TEMPLATES = original_active

    def test_apply_template_edit_returns_false_for_an_unknown_id(self) -> None:
        panel = build_templates_panel()
        with patch.object(config, "TEMPLATES", [{"id": 1, "name": "OLD"}]):
            with patch.object(config, "save_config") as save_config:
                applied = panel.apply_template_edit(
                    {"id": 99, "name": "GHOST"}, {"name": "NEW"}
                )
        self.assertFalse(applied)
        save_config.assert_not_called()


class PortTests(unittest.TestCase):
    def test_the_constructor_takes_exactly_its_eight_collaborators(self) -> None:
        """A silently-absorbed dependency is what `object.__new__` was retired for."""
        from ui.tabs.templates import TemplatesPanel

        # The builder refuses a name that is not a constructor argument...
        with self.assertRaises(AssertionError):
            build_templates_panel(app=object())
        # ...and so does the constructor itself, which is what makes the
        # builder's assertion a convenience rather than the only guard.
        with self.assertRaises(TypeError):
            TemplatesPanel(
                left_tabview=None,
                window=lambda: None,
                sync_filters=lambda **_kwargs: None,
                template_dialog=None,
                template_manager_dialog=None,
                delete_dialog=None,
                scores_settings_dialog=None,
                no_custom_templates_message=None,
                app=object(),
            )

    def test_the_panel_reaches_no_layout_window_or_log_through_an_app(self) -> None:
        """The step's third exit criterion, checked structurally."""
        import ast
        import inspect

        import ui.tabs.templates.panel as panel_module

        tree = ast.parse(inspect.getsource(panel_module))
        reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        for forbidden in ("window", "log", "layouts", "template_layout",
                          "scores_desc_label", "checkboxes", "scores_checkboxes"):
            self.assertNotIn(
                forbidden,
                reads,
                f"`self.{forbidden}` is an ambient read; the panel owns its own "
                "widgets under private names and takes the rest as ports",
            )


if __name__ == "__main__":
    unittest.main()
