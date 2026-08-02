from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.shared import _clear_layout


class ClearLayoutWindowSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_clearing_visible_widgets_does_not_promote_them_to_windows(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        chip = QLabel("Item chip")
        layout.addWidget(chip)
        host.show()
        self.qt_app.processEvents()

        top_levels_before = set(self.qt_app.topLevelWidgets())
        self.assertTrue(chip.isVisible())
        self.assertFalse(chip.isWindow())

        _clear_layout(layout)

        self.assertEqual(layout.count(), 0)
        self.assertFalse(chip.isVisible())
        self.assertFalse(chip.isWindow())
        self.assertIs(chip.parentWidget(), host)
        self.assertEqual(set(self.qt_app.topLevelWidgets()), top_levels_before)

        host.close()
        self.qt_app.processEvents()


if __name__ == "__main__":
    unittest.main()
