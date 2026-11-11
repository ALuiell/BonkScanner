from __future__ import annotations

import unittest
from unittest.mock import patch

import src
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from app import config
from gui_app import MegabonkApp, _choose_window_screen
from ui.shared import _AppWindow


class _Owner:
    """Just the window-state slice of `MegabonkApp`, on a real `_AppWindow`.

    Borrowing the four methods rather than restating them is the point: a stub
    that reimplemented the state naming would stay green while the app stopped
    remembering anything.
    """

    _WINDOW_STATE_KEY = MegabonkApp._WINDOW_STATE_KEY
    _WINDOW_PLACEMENT_KEY = MegabonkApp._WINDOW_PLACEMENT_KEY
    _current_window_state_name = MegabonkApp._current_window_state_name
    _handle_window_state_changed = MegabonkApp._handle_window_state_changed
    _save_window_placement = MegabonkApp._save_window_placement
    _restore_window_placement = MegabonkApp._restore_window_placement
    _restore_window_state = MegabonkApp._restore_window_state

    def __init__(self) -> None:
        self._is_shutting_down = False
        self._window_shown = False
        self.window = _AppWindow(self)

    def _handle_window_shown(self) -> None:
        self._window_shown = True

    def _handle_window_close(self, event) -> None:
        event.accept()


class WindowStateMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._stored = dict(config.user_config)
        config.user_config.pop(MegabonkApp._WINDOW_STATE_KEY, None)
        config.user_config.pop(MegabonkApp._WINDOW_PLACEMENT_KEY, None)
        saver = patch.object(config, "save_config", lambda cfg: None)
        saver.start()
        self.addCleanup(saver.stop)
        self.addCleanup(self._restore_config)

    def _restore_config(self) -> None:
        config.user_config.clear()
        config.user_config.update(self._stored)

    def _owner(self) -> _Owner:
        owner = _Owner()
        self.addCleanup(owner.window.close)
        return owner

    def _saved(self):
        return config.user_config.get(MegabonkApp._WINDOW_STATE_KEY)

    def test_maximizing_records_the_choice_and_windowing_clears_it(self) -> None:
        owner = self._owner()
        owner._restore_window_state()
        self._app.processEvents()

        owner.window.showMaximized()
        self._app.processEvents()
        self.assertEqual(self._saved(), "maximized")

        owner.window.showNormal()
        self._app.processEvents()
        self.assertEqual(self._saved(), "normal")

    def test_minimizing_does_not_overwrite_the_remembered_choice(self) -> None:
        owner = self._owner()
        owner.window.showMaximized()
        self._app.processEvents()

        owner.window.showMinimized()
        self._app.processEvents()

        self.assertEqual(self._saved(), "maximized")

    def test_shutdown_window_transitions_do_not_overwrite_the_remembered_choice(self) -> None:
        owner = self._owner()
        config.user_config[MegabonkApp._WINDOW_STATE_KEY] = "maximized"
        owner._is_shutting_down = True

        owner._handle_window_state_changed()

        self.assertEqual(self._saved(), "maximized")

    def test_a_remembered_state_decides_how_the_next_window_opens(self) -> None:
        first = self._owner()
        first.window.showMaximized()
        self._app.processEvents()

        second = self._owner()
        second._restore_window_state()
        self._app.processEvents()

        self.assertEqual(second._current_window_state_name(), "maximized")

    def test_no_remembered_state_opens_an_ordinary_window(self) -> None:
        owner = self._owner()
        owner._restore_window_state()
        self._app.processEvents()

        self.assertEqual(owner._current_window_state_name(), "normal")

    def test_window_placement_round_trip(self) -> None:
        available = self._app.primaryScreen().availableGeometry()
        first = self._owner()
        first.window.resize(min(600, available.width() - 100),
                            min(500, available.height() - 100))
        first.window.move(available.left() + 25, available.top() + 25)
        first.window.show()
        self._app.processEvents()
        expected = first.window.normalGeometry()
        with patch.object(config, "update_config", lambda mutate: mutate(config.user_config)):
            first._save_window_placement()

        second = self._owner()
        second._restore_window_state()
        self._app.processEvents()
        self.assertEqual(second.window.normalGeometry(), expected)
        self.assertEqual(config.user_config[second._WINDOW_PLACEMENT_KEY]["screen"],
                         first.window.screen().name())

    def test_maximized_window_restores_its_screen_and_normal_size(self) -> None:
        available = self._app.primaryScreen().availableGeometry()
        first = self._owner()
        first.window.resize(min(600, available.width() - 100),
                            min(500, available.height() - 100))
        first.window.move(available.left() + 25, available.top() + 25)
        first.window.show()
        self._app.processEvents()
        expected = first.window.normalGeometry()
        first.window.showMaximized()
        self._app.processEvents()
        with patch.object(config, "update_config", lambda mutate: mutate(config.user_config)):
            first._save_window_placement()

        second = self._owner()
        second._restore_window_state()
        self._app.processEvents()
        self.assertEqual(second._current_window_state_name(), "maximized")
        self.assertEqual(second.window.normalGeometry(), expected)

    def test_unavailable_screen_and_invalid_geometry_fall_back_to_primary(self) -> None:
        available = self._app.primaryScreen().availableGeometry()
        for placement in (
            {"screen": "missing-screen", "rect": [100000, 100000, 800, 600]},
            {"screen": "missing-screen", "rect": [True, 0, 800, 600]},
        ):
            with self.subTest(placement=placement):
                config.user_config[MegabonkApp._WINDOW_PLACEMENT_KEY] = placement
                owner = self._owner()
                owner._restore_window_state()
                self._app.processEvents()
                self.assertTrue(available.contains(owner.window.normalGeometry()))

    def test_saved_screen_wins_over_stale_screen_order(self) -> None:
        class Screen:
            def __init__(self, name, x):
                self._name = name
                self._geometry = QRect(x, 0, 1000, 800)

            def name(self):
                return self._name

            def availableGeometry(self):
                return self._geometry

        first, second, third = (Screen("first", 0), Screen("second", 1000),
                                Screen("third", 2000))
        screens = [third, second, first]
        stale_rect = QRect(2100, 100, 600, 500)
        self.assertIs(_choose_window_screen(screens, third, "first", stale_rect), first)
        self.assertIs(_choose_window_screen(screens, third, "missing", QRect(1100, 100, 600, 500)), second)
        self.assertIs(_choose_window_screen(screens, third, "missing", QRect(5000, 100, 600, 500)), third)


if __name__ == "__main__":
    unittest.main()
