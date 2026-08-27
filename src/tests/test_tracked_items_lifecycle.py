from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src  # noqa: F401 -- repository path bootstrap

from PySide6.QtWidgets import QApplication, QMessageBox

from app.tracked_item_settings import TrackedItemPublishError
from ui.dialogs import tracked_items as dialogs


class TrackedItemsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _settings(*, set_rules=None, set_source=None):
        state = {"rules": [], "source": "custom"}
        return SimpleNamespace(
            rules=lambda _target: list(state["rules"]),
            source=lambda _target: state["source"],
            make_rule=lambda _target, names, mode: {
                "id": "_".join(names).lower() + "_" + mode,
                "label": " + ".join(names),
                "item_names": list(names),
                "mode": mode,
            },
            set_rules=set_rules or (lambda _target, rules: state.update(rules=rules)),
            set_source=set_source
            or (lambda _target, source: state.update(source=source)),
        )

    def test_save_failure_is_contained_and_shown_inline(self) -> None:
        settings = self._settings(
            set_rules=MagicMock(side_effect=OSError("disk unavailable"))
        )
        dialog = dialogs.TrackedItemsDialog(settings)
        self.addCleanup(dialog.deleteLater)

        dialog._on_rules_changed(
            [
                {
                    "id": "anvil",
                    "label": "Anvil",
                    "item_names": ["Anvil"],
                    "mode": "all_run",
                }
            ]
        )

        self.assertTrue(dialog._status_card.isVisibleTo(dialog))
        self.assertIn("Changes were not saved", dialog._status_label.text())
        self.assertIn("disk unavailable", dialog._status_label.text())

    def test_publish_failure_is_a_saved_with_warnings_inline_state(self) -> None:
        settings = self._settings(
            set_source=MagicMock(
                side_effect=TrackedItemPublishError("snapshot was already deleted")
            )
        )
        dialog = dialogs.TrackedItemsDialog(settings, target_key="overlay")
        self.addCleanup(dialog.deleteLater)

        dialog._on_source("session")

        self.assertIn("Saved with warnings", dialog._status_label.text())
        self.assertIn("snapshot was already deleted", dialog._status_label.text())

    def test_successful_change_clears_an_earlier_inline_error(self) -> None:
        write = MagicMock(side_effect=[OSError("first write failed"), None])
        settings = self._settings(set_rules=write)
        dialog = dialogs.TrackedItemsDialog(settings)
        self.addCleanup(dialog.deleteLater)

        dialog._on_rules_changed([])
        self.assertFalse(dialog._status_card.isHidden())
        dialog._on_rules_changed([])

        self.assertTrue(dialog._status_card.isHidden())
        self.assertEqual("", dialog._status_label.text())

    def test_one_shot_helper_releases_dialog_on_success_and_error(self) -> None:
        opened = MagicMock()
        with patch.object(dialogs, "TrackedItemsDialog", return_value=opened):
            self.assertTrue(dialogs.show_tracked_items_dialog(MagicMock()))
        opened.exec.assert_called_once_with()
        opened.deleteLater.assert_called_once_with()

        failed = MagicMock()
        failed.exec.side_effect = RuntimeError("parent was deleted")
        with patch.object(
            dialogs, "TrackedItemsDialog", return_value=failed
        ), patch.object(QMessageBox, "warning") as warning:
            self.assertFalse(dialogs.show_tracked_items_dialog(MagicMock()))
        failed.deleteLater.assert_called_once_with()
        warning.assert_called_once()

        already_deleted = MagicMock()
        already_deleted.deleteLater.side_effect = RuntimeError("already deleted")
        dialogs._release_dialog(already_deleted)

    def test_real_picker_rollback_retry_switch_and_deletion_offscreen(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import sys
            sys.path.insert(0, os.path.join(os.getcwd(), "src"))

            from unittest.mock import MagicMock

            from PySide6.QtCore import QCoreApplication, QEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QPushButton

            from app import config
            from app.tracked_item_settings import TrackedItemSettings
            from ui.dialogs.tracked_items import TrackedItemsDialog

            app = QApplication([])
            config.SESSION_TRACKED_ITEMS = {"tracked_items": []}
            config.OVERLAY = {
                "tracked_items": [],
                "tracked_items_source": "custom",
            }
            config.TWITCH_BOT = {
                "tracked_items": [],
                "tracked_items_source": "custom",
            }
            for key in ("SESSION_TRACKED_ITEMS", "OVERLAY", "TWITCH_BOT"):
                config.user_config[key] = getattr(config, key)

            save_results = iter(
                [
                    config.ConfigSaveResult(False, "simulated disk failure"),
                    config.ConfigSaveResult(True),
                ]
            )
            settings = TrackedItemSettings(
                tracker=lambda: MagicMock(),
                combined_rules=lambda: (),
                refresh_session_rows=MagicMock(),
                refresh_snapshot=MagicMock(),
                save=lambda: next(save_results),
            )
            dialog = TrackedItemsDialog(settings)
            dialog.resize(980, 720)
            dialog.show()
            QCoreApplication.processEvents()

            dialog.picker.pick("Anvil")
            add = next(
                button
                for button in dialog.picker.findChildren(QPushButton)
                if button.text() == "Add"
            )
            add.click()
            QCoreApplication.processEvents()
            assert config.SESSION_TRACKED_ITEMS["tracked_items"] == []
            assert "simulated disk failure" in dialog._status_label.text()

            settings._save = lambda: config.ConfigSaveResult(True)
            dialog.picker.pick("Anvil")
            add.click()
            QCoreApplication.processEvents()
            assert len(config.SESSION_TRACKED_ITEMS["tracked_items"]) == 1
            assert dialog._status_card.isHidden()

            dialog._on_target("overlay")
            dialog._on_source("session")
            QCoreApplication.processEvents()
            assert dialog.is_mirroring()
            assert dialog.width() >= dialog.minimumWidth()
            assert dialog.height() >= dialog.minimumHeight()

            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QTest.qWait(20)
            QCoreApplication.processEvents()
            print("BLOCK14_TRACKED_ITEMS_QT_LIFECYCLE_OK")
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
        self.assertIn("BLOCK14_TRACKED_ITEMS_QT_LIFECYCLE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
