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
            import atexit
            import src
            from PySide6.QtWidgets import QApplication
            from app import config
            from gui_app import MegabonkApp

            config.save_config = lambda *_args, **_kwargs: None
            config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED = True
            app = MegabonkApp()
            # Keep an assertion failure from reaching interpreter teardown with
            # live QThreads.  The explicit close below remains the path tested;
            # this is only the subprocess's emergency cleanup.
            atexit.register(app.on_closing)
            qt = QApplication.instance()

            assert app.window.width() == 1320
            assert app.window.height() == 830
            assert app.window.minimumWidth() == 480
            assert app.window.minimumHeight() == 360

            def class_names():
                return {
                    widget.metaObject().className()
                    for widget in qt.topLevelWidgets()
                }

            # Building the hidden UI must not put anything on screen. It *does*
            # create top-level widgets -- every QComboBox gets a
            # QComboBoxPrivateContainer for its popup -- and this assertion used
            # to forbid that, which is what the 200-line StartupSafeComboBox
            # proxy existed to satisfy. Measurement on the real desktop found no
            # visible window from those containers at any point in startup, so
            # the proxy and this clause were paying for a flash that was never
            # there. What matters is visibility, and that is what is asserted:
            # here, and per-widget in the sibling test below.
            assert all(not widget.isVisible() for widget in qt.topLevelWidgets()), class_names()
            assert not app.window.isVisible()
            assert app._in_game_overlay.in_game_overlay_window is None

            app.window.show()
            assert app.window.isVisible()
            assert all(
                widget is app.window or not widget.isVisible()
                for widget in qt.topLevelWidgets()
            ), class_names()

            # Deferred helpers may now be created, but only behind a mapped main
            # window. In particular, the in-game overlay no longer exists during
            # MegabonkApp.__init__.
            # The show event posts ``start_runtime``; that callback deliberately
            # posts the native helper construction once more.  One pass was only
            # enough while UiInvoker's AutoConnection ran after_idle inline.
            qt.processEvents()
            qt.processEvents()
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

    def test_building_the_ui_shows_no_window_of_its_own(self) -> None:
        """No widget may be shown while it is still parentless.

        `test_the_main_window_precedes_every_native_helper_window` above cannot
        see this: it enumerates top-level widgets *after* `__init__` returns,
        and the window this catches is created and destroyed **inside** it. A
        parentless `QWidget` that is made visible gets a real native window --
        titled with the application name, because the widget has none of its own
        -- and loses it again when a layout reparents it a few milliseconds
        later. Two of those flashed before the real window at every start, from
        the stat-grid toggles in `live_stats` and `recordings`.

        The filter has to be installed before `MegabonkApp()` runs, which is why
        the `QApplication` is built first.
        """
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtCore import QEvent, QObject
            from PySide6.QtWidgets import QWidget
            from app import config
            from gui_app import MegabonkApp

            config.save_config = lambda *_args, **_kwargs: None
            config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED = True
            qt = MegabonkApp._ensure_qt_application()

            shown = []

            class ShowSpy(QObject):
                def eventFilter(self, obj, event):
                    if (
                        event.type() == QEvent.Show
                        and isinstance(obj, QWidget)
                        and obj.isWindow()
                    ):
                        shown.append(
                            (
                                obj.metaObject().className(),
                                obj.objectName(),
                                obj.windowTitle(),
                            )
                        )
                    return False

            spy = ShowSpy()
            qt.installEventFilter(spy)
            app = MegabonkApp()
            assert shown == [], shown
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
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
