from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui.tabs.player_stats.recordings import RecordingsTab


class _CompareDetailHarness:
    _render_compare_detail_rows = RecordingsTab._render_compare_detail_rows

    def __init__(self) -> None:
        self._compare_details_items = QWidget()
        QVBoxLayout(self._compare_details_items)
        self._compare_detail_rows = []
        self._compare_detail_empty_label = None


class RecordingCompareDetailReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _tab(self):
        return _CompareDetailHarness()

    def test_rows_are_updated_and_hidden_without_recreation(self) -> None:
        tab = self._tab()
        tab._render_compare_detail_rows(
            (("Common", "Beer +1"), ("Rare", "Key +1"))
        )
        original = tuple(tab._compare_detail_rows)

        tab._render_compare_detail_rows(
            (("Legendary", "Anvil +1"), ("Broken", "Key -1"))
        )
        self.assertEqual(original, tuple(tab._compare_detail_rows))

        tab._render_compare_detail_rows((("Common", "Beer +2"),))
        self.assertIs(tab._compare_detail_rows[0], original[0])
        self.assertTrue(original[1].isHidden())

        tab._render_compare_detail_rows(())
        self.assertTrue(all(row.isHidden() for row in original))
        self.assertFalse(tab._compare_detail_empty_label.isHidden())


if __name__ == "__main__":
    unittest.main()
