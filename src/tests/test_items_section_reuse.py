from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtWidgets import QApplication, QWidget

from ui.shared import FlowLayout
from ui.tabs.player_stats.items_section import ItemsSectionView


class ItemsSectionReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        container = QWidget()
        FlowLayout(container, margin=0, spacing=5)
        view = ItemsSectionView(
            group=None,
            label=None,
            rarity_label=None,
            toggle_btn=None,
            sort_combo=None,
            chips_container=container,
            always_expanded=True,
        )
        return view, container

    def test_count_changes_reuse_existing_chip_widgets(self) -> None:
        view, _container = self._view()
        view.update(("Beer x1", "Key x1"))
        self.app.processEvents()
        original = tuple(view._chip_widgets)

        view.update(("Beer x1", "Key x2"))
        self.app.processEvents()

        self.assertEqual(original, tuple(view._chip_widgets))
        self.assertEqual(["Beer x1", "Key x2"], [chip.text() for chip in original])

    def test_pool_grows_only_for_new_slots_and_hides_unused_ones(self) -> None:
        view, _container = self._view()
        view.update(("Beer x1", "Key x1"))
        first_two = tuple(view._chip_widgets)

        view.update(("Beer x1", "Key x1", "Big Bonk x1"))
        self.assertEqual(3, len(view._chip_widgets))
        self.assertEqual(first_two, tuple(view._chip_widgets[:2]))

        view.update(("Beer x2",))
        self.assertEqual(3, len(view._chip_widgets))
        self.assertFalse(view._chip_widgets[0].isHidden())
        self.assertTrue(all(chip.isHidden() for chip in view._chip_widgets[1:]))

    def test_placeholder_reuses_the_same_pool(self) -> None:
        view, _container = self._view()
        view.update(("Big Bonk x1", "Key x1"))
        original = tuple(view._chip_widgets)

        view.update((), items_text="No item data")

        self.assertEqual(original, tuple(view._chip_widgets))
        self.assertEqual("No item data", original[0].text())
        self.assertEqual("itemChipNote", original[0].objectName())
        self.assertTrue(original[1].isHidden())


if __name__ == "__main__":
    unittest.main()
