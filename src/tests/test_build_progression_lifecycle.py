from __future__ import annotations

from copy import deepcopy
import os
import subprocess
import sys
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src  # noqa: F401 -- repository path bootstrap

from PySide6.QtWidgets import QApplication, QDialog

from app import config
from app.settings import ConfigBuildProgressionSettings
from ui.dialogs import build_progression as dialogs


def _library() -> dict:
    return config.normalize_build_progression_config(
        {
            "schema_version": 3,
            "builds": [
                {
                    "id": "one",
                    "name": "First",
                    "requirements": [],
                },
                {
                    "id": "two",
                    "name": "Second",
                    "requirements": [],
                },
            ],
            "active_build_id": "one",
        }
    )


class BuildProgressionLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_config_write_rolls_back_runtime_memory_and_disk_on_failed_result(self) -> None:
        previous = _library()
        candidate = deepcopy(previous)
        candidate["active_build_id"] = "two"
        user_config = {
            "BUILD_PROGRESSION": deepcopy(previous),
            "unrelated": True,
        }
        writes = []

        def save(payload):
            writes.append(deepcopy(payload))
            if len(writes) == 1:
                return config.ConfigSaveResult(False, "disk full")
            return config.ConfigSaveResult(True)

        with patch.object(config, "BUILD_PROGRESSION", previous), patch.object(
            config, "user_config", user_config
        ), patch.object(config, "save_config", side_effect=save):
            with self.assertRaisesRegex(OSError, "disk full"):
                ConfigBuildProgressionSettings().write(candidate)

            self.assertIs(config.BUILD_PROGRESSION, previous)
            self.assertEqual(previous, config.user_config["BUILD_PROGRESSION"])

        self.assertEqual("two", writes[0]["BUILD_PROGRESSION"]["active_build_id"])
        self.assertEqual("one", writes[1]["BUILD_PROGRESSION"]["active_build_id"])

    def test_config_write_commits_verified_result(self) -> None:
        previous = _library()
        candidate = deepcopy(previous)
        candidate["active_build_id"] = "two"
        user_config = {"BUILD_PROGRESSION": deepcopy(previous)}

        with patch.object(config, "BUILD_PROGRESSION", previous), patch.object(
            config, "user_config", user_config
        ), patch.object(
            config,
            "save_config",
            return_value=config.ConfigSaveResult(True),
        ):
            saved = ConfigBuildProgressionSettings().write(candidate)

            self.assertEqual("two", saved["active_build_id"])
            self.assertEqual("two", config.BUILD_PROGRESSION["active_build_id"])
            self.assertEqual(
                "two", config.user_config["BUILD_PROGRESSION"]["active_build_id"]
            )

    def test_config_write_treats_an_empty_exception_as_failure(self) -> None:
        previous = _library()
        candidate = deepcopy(previous)
        candidate["active_build_id"] = "two"

        with patch.object(config, "BUILD_PROGRESSION", previous), patch.object(
            config,
            "user_config",
            {"BUILD_PROGRESSION": deepcopy(previous)},
        ), patch.object(
            config,
            "save_config",
            side_effect=[OSError(), config.ConfigSaveResult(True)],
        ):
            with self.assertRaisesRegex(OSError, "OSError"):
                ConfigBuildProgressionSettings().write(candidate)
            self.assertIs(config.BUILD_PROGRESSION, previous)

    def test_manager_restores_last_saved_library_when_write_fails(self) -> None:
        state = _library()
        settings = SimpleNamespace(
            read=lambda: deepcopy(state),
            write=MagicMock(side_effect=OSError("settings unavailable")),
        )
        service = MagicMock()
        manager = dialogs.BuildProgressionManagerDialog(settings, service)
        self.addCleanup(manager.deleteLater)
        manager._library["active_build_id"] = "two"

        with patch.object(dialogs, "_show_notice") as notice:
            saved = manager._persist(refresh_service=True)

        self.assertFalse(saved)
        self.assertEqual("one", manager.library["active_build_id"])
        self.assertFalse(manager.changed)
        service.replace_definition.assert_not_called()
        self.assertEqual("Build Progression Not Saved", notice.call_args.args[1])
        self.assertTrue(notice.call_args.kwargs["danger"])

    def test_manager_contains_live_refresh_failure_after_successful_save(self) -> None:
        state = _library()
        settings = SimpleNamespace(
            read=lambda: deepcopy(state),
            write=lambda payload: deepcopy(payload),
        )
        service = MagicMock()
        service.replace_definition.side_effect = RuntimeError("live view unavailable")
        manager = dialogs.BuildProgressionManagerDialog(settings, service)
        self.addCleanup(manager.deleteLater)
        manager._library["active_build_id"] = "two"

        with patch.object(dialogs, "_show_notice") as notice:
            saved = manager._persist(refresh_service=True)

        self.assertTrue(saved)
        self.assertTrue(manager.changed)
        self.assertEqual("two", manager.library["active_build_id"])
        self.assertEqual("Build Saved with Warnings", notice.call_args.args[1])
        self.assertIn("live view unavailable", notice.call_args.args[2])

    def test_service_warning_is_opened_only_after_ui_refresh_finishes(self) -> None:
        state = _library()
        settings = SimpleNamespace(
            read=lambda: deepcopy(state),
            write=lambda payload: deepcopy(payload),
        )
        events = []
        service = MagicMock()
        manager = dialogs.BuildProgressionManagerDialog(settings, service)
        self.addCleanup(manager.deleteLater)
        manager._library["active_build_id"] = "two"
        manager._refresh_cards = MagicMock(
            side_effect=lambda: events.append("refresh")
        )

        def fail_refresh(_definition) -> None:
            events.append("service")
            raise RuntimeError("shutdown interrupted refresh")

        service.replace_definition.side_effect = fail_refresh
        with patch.object(
            dialogs,
            "_show_notice",
            side_effect=lambda *_args, **_kwargs: events.append("notice"),
        ):
            self.assertTrue(manager._persist(refresh_service=True))

        self.assertEqual(["refresh", "service", "notice"], events)

    def test_one_shot_dialog_helpers_always_schedule_deletion(self) -> None:
        notice = MagicMock()
        confirm = MagicMock(confirmed=True)
        help_dialog = MagicMock()
        manager = MagicMock(changed=True)

        with patch.object(dialogs, "BuildProgressionNoticeDialog", return_value=notice):
            dialogs._show_notice(None, "Title", "Message")
        with patch.object(dialogs, "BuildProgressionConfirmDialog", return_value=confirm):
            self.assertTrue(
                dialogs._ask_confirmation(
                    None, "Title", "Message", confirm_text="Confirm"
                )
            )
        with patch.object(dialogs, "BuildProgressionHelpDialog", return_value=help_dialog):
            dialogs.show_build_progression_help()
        with patch.object(
            dialogs, "BuildProgressionManagerDialog", return_value=manager
        ):
            self.assertTrue(
                dialogs.show_build_progression_manager(MagicMock(), MagicMock())
            )

        notice.deleteLater.assert_called_once_with()
        confirm.deleteLater.assert_called_once_with()
        help_dialog.deleteLater.assert_called_once_with()
        manager.deleteLater.assert_called_once_with()

        dead_dialog = MagicMock()
        dead_dialog.deleteLater.side_effect = RuntimeError("already deleted")
        dialogs._release_dialog(dead_dialog)

    def test_editor_is_released_after_accepted_result(self) -> None:
        state = {"schema_version": 3, "builds": [], "active_build_id": None}
        settings = SimpleNamespace(
            read=lambda: deepcopy(state),
            write=lambda payload: config.normalize_build_progression_config(payload),
        )
        manager = dialogs.BuildProgressionManagerDialog(settings, MagicMock())
        self.addCleanup(manager.deleteLater)
        draft = config.normalize_build_definition_config(
            {"id": "created", "name": "Created", "requirements": []}
        )
        editor = MagicMock(result_payload=draft)
        editor.exec.return_value = QDialog.Accepted

        with patch.object(dialogs, "BuildProgressionDialog", return_value=editor):
            manager._open_editor(draft, create=True)

        editor.deleteLater.assert_called_once_with()

    def test_real_dialog_tree_survives_refresh_failure_and_deferred_deletion(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import sys
            sys.path.insert(0, os.path.join(os.getcwd(), "src"))

            from copy import deepcopy
            from types import SimpleNamespace
            from unittest.mock import MagicMock, patch

            from PySide6.QtCore import QCoreApplication, QEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from app import config
            from ui.dialogs import build_progression as dialogs

            library = config.normalize_build_progression_config(
                {
                    "schema_version": 3,
                    "builds": [
                        {"id": "one", "name": "First", "requirements": []},
                        {"id": "two", "name": "Second", "requirements": []},
                    ],
                    "active_build_id": "one",
                }
            )
            settings = SimpleNamespace(
                read=lambda: deepcopy(library),
                write=MagicMock(side_effect=OSError("disk unavailable")),
            )
            app = QApplication([])
            manager = dialogs.BuildProgressionManagerDialog(settings, MagicMock())
            editor = dialogs.BuildProgressionDialog(deepcopy(library["builds"][0]))
            help_dialog = dialogs.BuildProgressionHelpDialog(manager)
            manager.show()
            editor.show()
            help_dialog.show()
            QCoreApplication.processEvents()

            manager._library["active_build_id"] = "two"
            with patch.object(dialogs, "_show_notice"):
                assert not manager._persist(refresh_service=True)
            assert manager.library["active_build_id"] == "one"
            assert not manager.card_widgets["one"]["active"].isEnabled()
            assert manager.width() >= manager.minimumWidth()
            assert editor.width() >= editor.minimumWidth()

            manager.deleteLater()
            editor.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QTest.qWait(20)
            QCoreApplication.processEvents()
            print("BLOCK13_BUILD_PROGRESSION_QT_LIFECYCLE_OK")
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
        self.assertIn("BLOCK13_BUILD_PROGRESSION_QT_LIFECYCLE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
