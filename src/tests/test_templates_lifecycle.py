from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest

import src  # noqa: F401 -- repository path bootstrap


class TemplatesQtLifecycleTests(unittest.TestCase):
    def test_dialog_timers_and_failed_saves_are_safe_offscreen(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from copy import deepcopy
            from unittest.mock import patch

            from PySide6.QtCore import QCoreApplication, QEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QTabWidget

            from app import config
            from tests.support.templates_panel import build_templates_panel
            from ui.dialogs import DeleteDialog, ScoresSettingsDialog, TemplateManagerDialog

            app = QApplication([])
            warnings = []

            tabs = QTabWidget()
            panel = build_templates_panel(left_tabview=tabs)
            config.TEMPLATES = [
                {"id": 1, "name": "LIGHT", "color": "WHITE", "sm_total": 5},
                {"id": 9, "name": "Custom", "color": "BLUE", "boss": 2},
            ]
            config.ACTIVE_TEMPLATES = ["LIGHT"]
            with patch.object(
                config,
                "save_config",
                return_value=config.ConfigSaveResult(True),
            ):
                panel.build()
                panel.refresh_templates()
                panel.refresh_scores_templates_list()
                panel.refresh_scores_ui()
            tabs.resize(440, 700)
            tabs.show()
            QCoreApplication.processEvents()
            assert tabs.count() == 2
            assert len(panel._template_surface.rows()) == 2
            assert len(panel._score_tier_rows) == 4

            # The manager queues a scroll after expanding a card. Destroying
            # the dialog before the event loop turns must cancel that callback.
            manager = TemplateManagerDialog(
                None,
                [{"id": 9, "name": "Custom", "color": "BLUE"}],
                lambda _old, _new: True,
            )
            manager.toggle_template(9)
            manager.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QTest.qWait(10)
            QCoreApplication.processEvents()

            original_scores = deepcopy(config.SCORES_SYSTEM)
            original_scores["active_tiers"] = ["Light"]
            config.SCORES_SYSTEM = original_scores
            config.user_config["SCORES_SYSTEM"] = original_scores
            scores = ScoresSettingsDialog(None)
            with patch.object(
                config,
                "save_config",
                return_value=config.ConfigSaveResult(False, "scores disk full"),
            ), patch.object(
                QMessageBox,
                "warning",
                side_effect=lambda _parent, title, text: warnings.append((title, text)),
            ):
                scores.save()
            assert scores.result() != QDialog.Accepted
            assert config.SCORES_SYSTEM is original_scores
            assert warnings[-1][0] == "Could Not Save Settings"

            templates = [
                {"id": 1, "name": "LIGHT", "color": "WHITE"},
                {"id": 9, "name": "Custom", "color": "BLUE"},
            ]
            active = ["LIGHT", "Custom"]
            config.TEMPLATES = templates
            config.ACTIVE_TEMPLATES = active
            config.user_config["TEMPLATES"] = templates
            config.user_config["ACTIVE_TEMPLATES"] = active
            deletion = DeleteDialog(None, templates)
            deletion.checks[1].setChecked(True)
            with patch.object(
                config,
                "save_config",
                return_value=config.ConfigSaveResult(False, "delete disk full"),
            ), patch.object(
                QMessageBox,
                "warning",
                side_effect=lambda _parent, title, text: warnings.append((title, text)),
            ):
                deletion.delete()
            assert deletion.result() != QDialog.Accepted
            assert config.TEMPLATES is templates
            assert config.ACTIVE_TEMPLATES is active
            assert warnings[-1][0] == "Could Not Delete Templates"

            scores.deleteLater()
            deletion.deleteLater()
            tabs.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            print("BLOCK11_TEMPLATES_QT_LIFECYCLE_OK")
            """
        )
        environment = os.environ.copy()
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("BLOCK11_TEMPLATES_QT_LIFECYCLE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
