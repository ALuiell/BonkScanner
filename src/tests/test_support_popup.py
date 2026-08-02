"""The supporters list in the footer popup.

The list has no data source yet -- `FooterView.set_supporters` is a seam nobody
calls in production. These tests are what stops that from meaning *untested*:
they drive the seam directly, so the widget cannot rot between now and the day
someone adds a reader for it.

The first test is the one that matters most. The shipping state is the empty
one, and it has to stay indistinguishable from the card that was there before
the list existed.
"""
import src  # noqa: F401  -- puts src/ on the path, as the other tests do

import unittest

from PySide6.QtWidgets import QApplication, QLabel

from ui.footer import SupportPopup

_app = QApplication.instance() or QApplication([])


def _names(popup):
    """The name rows the popup would actually show.

    `isHidden` is not decoration here. `_clear_layout` hides each widget and
    then `deleteLater`s it, so a row taken off the screen is still a child of
    the host until the event loop next runs -- `findChildren` alone would count
    a list that has already been replaced, and the "back to empty" case would
    pass or fail depending on whether anything happened to spin the loop.
    """
    return [
        label.text()
        for label in popup.findChildren(QLabel)
        if label.objectName() in ("supporterName", "supporterNameTier")
        and not label.isHidden()
    ]


class SupportPopupTests(unittest.TestCase):
    def setUp(self):
        self.popup = SupportPopup()
        self.addCleanup(self.popup.deleteLater)

    def test_no_supporters_is_the_plain_card(self):
        self.popup.set_supporters(())
        self.assertEqual(_names(self.popup), [])
        self.assertEqual(self.popup._card.width(), SupportPopup.NARROW_WIDTH)
        self.assertFalse(self.popup._names_host.isVisibleTo(self.popup))
        self.assertFalse(self.popup._rule.isVisibleTo(self.popup))
        self.assertEqual(self.popup._title.text(), "Support BonkScanner")

    def test_blank_and_malformed_entries_do_not_become_rows(self):
        self.popup.set_supporters(["", "  ", {"name": ""}, {"tier": "gold"}, None])
        self.assertEqual(_names(self.popup), [])
        self.assertEqual(self.popup._card.width(), SupportPopup.NARROW_WIDTH)

    def test_plain_names_and_mappings_are_both_accepted(self):
        self.popup.set_supporters(["Grimwald", {"name": "Nyxaria", "tier": "gold"}])
        self.assertIn("Grimwald", _names(self.popup))
        self.assertTrue(any("Nyxaria" in name for name in _names(self.popup)))
        self.assertEqual(self.popup._card.width(), SupportPopup.WIDE_WIDTH)

    def test_tiers_sort_first_and_are_marked(self):
        self.popup.set_supporters(
            ["a", "b", {"name": "paid", "tier": "gold"}, "c"]
        )
        marked = [
            label
            for label in self.popup.findChildren(QLabel)
            if label.objectName() == "supporterNameTier"
        ]
        self.assertEqual(len(marked), 1)
        self.assertIn("paid", marked[0].text())
        self.assertEqual(_names(self.popup)[0], marked[0].text())

    def test_count_is_everyone_even_when_the_list_is_capped(self):
        people = [f"person {index}" for index in range(SupportPopup.MAX_LISTED + 6)]
        self.popup.set_supporters(people)
        self.assertEqual(len(_names(self.popup)), SupportPopup.MAX_LISTED)
        self.assertIn(str(len(people)), self.popup._title.text())
        self.assertIn("6 more", self.popup._note.text())

    def test_going_back_to_empty_restores_the_plain_card(self):
        self.popup.set_supporters(["Someone"])
        self.popup.set_supporters(())
        self.assertEqual(_names(self.popup), [])
        self.assertEqual(self.popup._card.width(), SupportPopup.NARROW_WIDTH)
        self.assertEqual(self.popup._title.text(), "Support BonkScanner")


if __name__ == "__main__":
    unittest.main()
