from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest

import src  # noqa: F401 -- repository path bootstrap


class SettingsUpdateQtLifecycleTests(unittest.TestCase):
    def test_transient_dialogs_and_update_timer_are_safe_offscreen(self) -> None:
        script = textwrap.dedent(
            """
            import os
            import sys
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            sys.path.insert(0, os.path.join(os.getcwd(), "src"))

            from PySide6.QtCore import QCoreApplication, QEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QPushButton, QWidget

            from core.update_types import PreparedUpdate, ReleaseInfo
            from ui.dialogs import HelpDialog, SettingsDialog
            from ui.dialogs.update_dialog import UpdateDialog
            from ui.footer import SupportPopup

            app = QApplication([])
            window = QWidget()
            window.resize(760, 620)
            window.show()

            class Master:
                @staticmethod
                def is_game_running():
                    return False

            help_dialog = HelpDialog(window)
            help_dialog.show()
            QCoreApplication.processEvents()
            help_dialog.close()
            help_dialog.deleteLater()

            settings = SettingsDialog(window, master=Master())
            settings.open()
            QCoreApplication.processEvents()
            settings.reject()
            settings.reload_from_config()
            settings.open()
            QCoreApplication.processEvents()
            settings.reject()
            settings.deleteLater()

            callbacks = {}
            installed = []

            def start_download(progress, ready, failed):
                callbacks.update(progress=progress, ready=ready, failed=failed)

            update = UpdateDialog(
                window,
                ReleaseInfo(
                    "9.9.9",
                    "## Lifecycle test",
                    "https://example.invalid/BonkScanner.exe",
                    3,
                    "a" * 64,
                ),
                start_download=start_download,
                install_update=installed.append,
            )
            update.show()
            update._begin_download()
            callbacks["ready"](
                PreparedUpdate(
                    version="9.9.9",
                    exe_path="BonkScanner.exe",
                    new_exe_path="BonkScanner.new.exe",
                    installer_path="update.bat",
                    downloaded_size=3,
                    sha256="a" * 64,
                )
            )
            update.deleteLater()

            anchor = QPushButton("Support", window)
            anchor.move(620, 560)
            anchor.show()
            popup = SupportPopup(window)
            popup.show_above(anchor)
            anchor.deleteLater()

            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            popup.set_supporters(["Late supporter"])
            QTest.qWait(750)
            QCoreApplication.processEvents()
            assert installed == [], installed

            popup.close()
            popup.deleteLater()
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            print("BLOCK12_SETTINGS_UPDATE_QT_LIFECYCLE_OK")
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
        self.assertIn("BLOCK12_SETTINGS_UPDATE_QT_LIFECYCLE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
