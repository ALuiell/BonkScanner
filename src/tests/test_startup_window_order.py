from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap


class StartupWindowOrderTests(unittest.TestCase):
    def test_the_main_window_precedes_every_native_helper_window(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication
            from app import config
            from gui_app import MegabonkApp

            config.save_config = lambda *_args, **_kwargs: None
            app = MegabonkApp()
            qt = QApplication.instance()

            def class_names():
                return {
                    widget.metaObject().className()
                    for widget in qt.topLevelWidgets()
                }

            # Building the hidden UI must not create native popup/tool windows.
            assert class_names() == {"_AppWindow"}, class_names()
            assert not app.window.isVisible()
            assert app._in_game_overlay.in_game_overlay_window is None

            app._show_main_window_ready()
            assert app.window.isVisible()
            assert app.window.windowOpacity() == 1.0
            assert app.window.updatesEnabled()
            assert all(
                widget is app.window or not widget.isVisible()
                for widget in qt.topLevelWidgets()
            ), class_names()

            # Deferred helpers may now be created, but only behind a mapped main
            # window. In particular, the in-game overlay no longer exists during
            # MegabonkApp.__init__.
            qt.processEvents()
            assert app.window.isVisible()
            overlay_window = app._in_game_overlay.in_game_overlay_window
            assert overlay_window is not None

            app.on_closing()
            qt.processEvents()
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_combo_popup_is_created_only_after_its_host_is_visible(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
            from ui.shared import StartupSafeComboBox
            from ui.styles import build_qt_app_stylesheet

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))
            host = QWidget()
            layout = QVBoxLayout(host)
            combo = StartupSafeComboBox()
            combo.addItem("Default", "default")
            combo.addItem("Rarity", "rarity")
            combo.setCurrentIndex(1)
            layout.addWidget(combo)

            def popup_count():
                return sum(
                    widget.metaObject().className()
                    == "QComboBoxPrivateContainer"
                    for widget in app.topLevelWidgets()
                )

            assert popup_count() == 0
            assert combo.currentText() == "Rarity"
            assert combo.currentData() == "rarity"

            host.show()
            assert popup_count() == 0
            app.processEvents()
            assert popup_count() == 1
            assert combo.currentText() == "Rarity"
            assert combo.currentData() == "rarity"
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
