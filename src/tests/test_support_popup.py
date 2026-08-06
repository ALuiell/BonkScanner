"""The supporters list in the footer popup, and the reader that fills it.

The first test is the one that matters most. The shipping state is the empty
one -- nobody has subscribed, or the request failed -- and it has to stay
indistinguishable from the card that was there before the list existed.

The `SupportersLoadTests` half covers the other end: `supporters.json` is a file
maintained by hand in a browser, so a half-saved edit or a dead network is a
normal Tuesday, not an exceptional case, and none of them may reach the screen.
"""
import src  # noqa: F401  -- puts src/ on the path, as the other tests do

import unittest

from PySide6.QtWidgets import QApplication, QLabel

from app import supporters as supporters_flow
from infra import updater
from ui.dialogs import update_prompt
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


class SupportersLoadTests(unittest.TestCase):
    def setUp(self):
        self.reported: list = []
        self._real_fetch = updater.fetch_supporters
        self.addCleanup(setattr, updater, "fetch_supporters", self._real_fetch)

    def _fetch_returns(self, value):
        updater.fetch_supporters = lambda: value

    def _fetch_raises(self, error):
        def fetch():
            raise error

        updater.fetch_supporters = fetch

    def test_names_are_reported(self):
        self._fetch_returns(["Grimwald", "Nyxaria"])

        supporters_flow.load_supporters(self.reported.append)

        self.assertEqual(self.reported, [["Grimwald", "Nyxaria"]])

    def test_a_failed_request_reports_nothing(self):
        self._fetch_raises(RuntimeError("no network"))

        supporters_flow.load_supporters(self.reported.append)

        self.assertEqual(self.reported, [])

    def test_an_empty_list_reports_nothing(self):
        # Not the same as "report an empty list": the strip already ships empty,
        # and a call here would only risk `♥ 0 supporters` if that rule moved.
        self._fetch_returns([])

        supporters_flow.load_supporters(self.reported.append)

        self.assertEqual(self.reported, [])

    def test_load_does_nothing_without_a_footer_or_a_scheduler(self):
        # `build_layout` has not run yet, or an app stand-in has neither. The
        # thread must not start at all rather than fail inside it.
        self._fetch_raises(AssertionError("must not be called"))

        update_prompt.start_supporters_load(None)
        update_prompt.start_supporters_load(object())

    def test_clean_supporters_drops_what_the_popup_cannot_draw(self):
        self.assertEqual(
            updater.clean_supporters(["Grimwald", 5, None, {"name": "Nyxaria"}]),
            ["Grimwald", {"name": "Nyxaria"}],
        )

    def test_clean_supporters_rejects_a_payload_that_is_not_a_list(self):
        # What a mis-edited file looks like: an object, a bare string, `null`.
        self.assertEqual(updater.clean_supporters({"names": ["a"]}), [])
        self.assertEqual(updater.clean_supporters("Grimwald"), [])
        self.assertEqual(updater.clean_supporters(None), [])


if __name__ == "__main__":
    unittest.main()
