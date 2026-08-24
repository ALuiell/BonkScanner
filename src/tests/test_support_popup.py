"""The supporters list in the footer popup, and the reader that fills it.

The first test is the one that matters most. The shipping state is the empty
one -- nobody has subscribed, or the request failed -- and it has to stay
indistinguishable from the card that was there before the list existed.

The `SupportersLoadTests` half covers the other end: `supporters.json` is a file
maintained by hand in a browser, so a half-saved edit or a dead network is a
normal Tuesday, not an exceptional case, and none of them may reach the screen.
"""
import src  # noqa: F401  -- puts src/ on the path, as the other tests do

import json
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from app import supporters as supporters_flow
from infra import updater
from ui.dialogs import update_prompt
from ui.footer import SupportPopup
from ui.shared import resource_path
from ui.styles import build_qt_app_stylesheet

_app = QApplication.instance() or QApplication([])


def _names(popup):
    """The name rows the popup would actually show.

    `isHidden` is not decoration here. `_clear_layout` hides each widget and
    then `deleteLater`s it, so a row taken off the screen is still a child of
    the host until the event loop next runs -- `findChildren` alone would count
    a list that has already been replaced, and the "back to empty" case would
    pass or fail depending on whether anything happened to spin the loop.
    """
    return [text for text, _object_name in _rows(popup)]


def _rows(popup):
    """The visible name rows as `(text, object name)` -- the styling included."""
    known = {"supporterName", *(style[0] for style in SupportPopup.TIER_STYLES.values())}
    return [
        (label.text(), label.objectName())
        for label in popup.findChildren(QLabel)
        if label.objectName() in known and not label.isHidden()
    ]


class SupportPopupTests(unittest.TestCase):
    def setUp(self):
        self.popup = SupportPopup()
        self.addCleanup(self.popup.deleteLater)

    def test_no_supporters_is_the_plain_card(self):
        self.popup.set_supporters(())
        self.assertEqual(_names(self.popup), [])
        self.assertEqual(self.popup._card.width(), SupportPopup.NARROW_WIDTH)
        self.assertFalse(self.popup._legend.isVisibleTo(self.popup))
        self.assertFalse(self.popup._names_host.isVisibleTo(self.popup))
        self.assertFalse(self.popup._rule.isVisibleTo(self.popup))
        self.assertEqual(self.popup._title.text(), "Support BonkScanner")
        self.assertEqual(self.popup._note.text(), SupportPopup.DEFAULT_NOTE)

    def test_blank_and_malformed_entries_do_not_become_rows(self):
        self.popup.set_supporters(["", "  ", {"name": ""}, {"tier": "patreon"}, None])
        self.assertEqual(_names(self.popup), [])
        self.assertEqual(self.popup._card.width(), SupportPopup.NARROW_WIDTH)

    def test_plain_names_and_mappings_are_both_accepted(self):
        self.popup.set_supporters(["Grimwald", {"name": "Nyxaria", "tier": "patreon"}])
        self.assertIn("Grimwald", _names(self.popup))
        self.assertTrue(any("Nyxaria" in name for name in _names(self.popup)))
        self.assertEqual(self.popup._card.width(), SupportPopup.WIDE_WIDTH)

    def test_supporter_title_uses_singular_and_plural_grammar(self):
        self.popup.set_supporters(["PrestoOmento"])
        self.assertEqual(self.popup._title.text(), "1 person supports BonkScanner")

        self.popup.set_supporters(["PrestoOmento", "Nyxaria"])
        self.assertEqual(self.popup._title.text(), "2 people support BonkScanner")

    def test_names_have_breathing_room_above_and_below(self):
        margins = self.popup._names_grid.contentsMargins()

        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            (0, 3, 0, 4),
        )

    def test_legend_explains_platform_colours_and_status_symbols(self):
        self.popup.set_supporters(["PrestoOmento"])
        labels = {
            label.objectName(): label.text()
            for label in self.popup._legend.findChildren(QLabel)
        }

        self.assertTrue(self.popup._legend.isVisibleTo(self.popup))
        self.assertEqual(
            labels,
            {
                "supporterLegendPatreon": "●  Patreon",
                "supporterLegendKofi": "●  Ko-fi",
                "supporterLegendFounder": "★  Founder",
                "supporterLegendPack": "■  Supporter Pack",
                "supporterLegendSub": "♦  Active sub",
            },
        )

    def test_legend_platform_colours_match_supporter_names(self):
        previous_stylesheet = _app.styleSheet()
        self.addCleanup(_app.setStyleSheet, previous_stylesheet)
        checkmark_path = resource_path("media/checkmark.svg").replace("\\", "/")
        _app.setStyleSheet(build_qt_app_stylesheet(checkmark_path))

        popup = SupportPopup()
        self.addCleanup(popup.deleteLater)
        popup.set_supporters(
            [
                {"name": "patreon name", "tier": "patreon"},
                {"name": "kofi name", "tier": "kofi"},
            ]
        )
        popup.ensurePolished()

        for legend_name, supporter_name in (
            ("supporterLegendPatreon", "supporterNamePatreon"),
            ("supporterLegendKofi", "supporterNameKofi"),
        ):
            legend = popup.findChild(QLabel, legend_name)
            supporter = popup.findChild(QLabel, supporter_name)
            legend.ensurePolished()
            supporter.ensurePolished()
            self.assertEqual(
                legend.palette().color(QPalette.WindowText),
                supporter.palette().color(QPalette.WindowText),
            )

    def test_each_tier_gets_its_own_style_and_marker(self):
        self.popup.set_supporters(
            [
                {"name": "sub", "tier": "patreon"},
                {"name": "buyer", "tier": "pack"},
                {"name": "tipper", "tier": "kofi"},
                "nobody",
            ]
        )

        styles = {text.lstrip("★■♦ "): name for text, name in _rows(self.popup)}
        self.assertEqual(styles["sub"], "supporterNamePatreon")
        self.assertEqual(styles["buyer"], "supporterNamePack")
        self.assertEqual(styles["tipper"], "supporterNameKofi")
        self.assertEqual(styles["nobody"], "supporterName")

        rows = {text.lstrip("★■♦ "): text for text, _name in _rows(self.popup)}
        self.assertEqual(rows["sub"], "♦  sub")
        self.assertEqual(rows["buyer"], "■  buyer")
        self.assertEqual(rows["tipper"], "tipper")
        self.assertEqual(rows["nobody"], "nobody")

    def test_founder_and_pack_badges_stack_with_an_active_subscription(self):
        self.popup.set_supporters(
            [
                {
                    "name": "PrestoOmento",
                    "tier": "patreon",
                    "badges": ["pack", "founder", "pack"],
                }
            ]
        )

        self.assertEqual(
            _rows(self.popup),
            [("★  ■  ♦  PrestoOmento", "supporterNamePatreon")],
        )

    def test_tiers_group_in_order_and_keep_the_files_order_inside_a_group(self):
        self.popup.set_supporters(
            [
                "plain one",
                {"name": "kofi one", "tier": "kofi"},
                {"name": "pack one", "tier": "pack"},
                {"name": "pack two", "tier": "pack"},
                {"name": "sub one", "tier": "patreon"},
            ]
        )

        self.assertEqual(
            [text.lstrip("★■♦ ") for text, _name in _rows(self.popup)],
            ["sub one", "pack one", "pack two", "kofi one", "plain one"],
        )

    def test_a_tier_is_matched_however_it_was_typed(self):
        self.popup.set_supporters(
            [
                {"name": "a", "tier": "Ko-Fi"},
                {"name": "b", "tier": " KOFI "},
                {"name": "c", "tier": "ko_fi"},
            ]
        )

        self.assertEqual(
            {name for _text, name in _rows(self.popup)}, {"supporterNameKofi"}
        )

    def test_an_unknown_tier_stays_marked_rather_than_dropping_to_plain(self):
        # A typo in the tier of someone who paid must not read as "not a
        # supporter". It costs the diamond, not the colour.
        self.popup.set_supporters([{"name": "typo", "tier": "patrn"}])

        self.assertEqual(_rows(self.popup), [("typo", "supporterNamePack")])

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
        self.assertFalse(self.popup._legend.isVisibleTo(self.popup))
        self.assertEqual(self.popup._title.text(), "Support BonkScanner")
        self.assertEqual(self.popup._note.text(), SupportPopup.DEFAULT_NOTE)


class SupportPopupPlacementTests(unittest.TestCase):
    """Where the card lands, including when it changes size while open.

    The bug these were written for: clicking Support in the second or so between
    the window appearing and the supporters arriving. The card opened at its
    narrow width, the names then widened it from 268 to 400, and since `move`
    pins the top-left corner it grew rightwards off the display. Opening it
    again looked fine, which is why it read as "only the first time".
    """

    def _anchor(self):
        window = QWidget()
        self.addCleanup(window.deleteLater)
        # Sized and placed to fit the display rather than assuming one: under
        # the full suite the platform is offscreen and the screen is 800x800, so
        # a fixed 900px window hangs off the edge, the clamp does its job, and a
        # test about *alignment* fails on a card that was correctly rescued.
        available = QApplication.primaryScreen().availableGeometry()
        width = min(900, available.width() - 40)
        height = min(600, available.height() - 40)
        window.setGeometry(available.left() + 20, available.top() + 20, width, height)
        button = QPushButton("♥ 2 supporters", window)
        button.setGeometry(width - 120, height - 30, 110, 20)
        # Shown, and not for realism: `mapToGlobal` on a window the platform has
        # not placed yet answers from a position it then changes, so the
        # expected value and the one `show_above` used are read from different
        # windows. Closed again by cleanup.
        window.show()
        self.addCleanup(window.close)
        _app.processEvents()
        return window, button

    def _open_fresh(self, anchor):
        popup = SupportPopup(anchor.window())
        self.addCleanup(popup.deleteLater)
        popup.set_supporters(["Grimwald", {"name": "Nyxaria", "tier": "patreon"}])
        popup.show_above(anchor)
        self.addCleanup(popup.close)
        return popup

    def test_first_open_is_sized_and_placed_like_the_second(self):
        _window, anchor = self._anchor()

        first = self._open_fresh(anchor)
        geometry = first.geometry()

        self.assertEqual(geometry.width(), first.sizeHint().width())
        # Aligned with the anchor's right edge -- the placement rule. Reading a
        # stale 100 would put the right edge 300px past it.
        anchor_right = anchor.mapToGlobal(QPoint(anchor.width(), 0)).x()
        self.assertEqual(geometry.right() + 1, anchor_right)

    def test_names_arriving_while_the_card_is_open_do_not_push_it_off_screen(self):
        window, anchor = self._anchor()
        screen = window.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()

        # Opened before the list has arrived -- the narrow, two-button card.
        popup = SupportPopup(window)
        self.addCleanup(popup.deleteLater)
        popup.show_above(anchor)
        self.addCleanup(popup.close)
        _app.processEvents()
        self.assertEqual(popup._card.width(), SupportPopup.NARROW_WIDTH)

        popup.set_supporters(["Grimwald", {"name": "Nyxaria", "tier": "patreon"}])
        _app.processEvents()

        self.assertEqual(popup._card.width(), SupportPopup.WIDE_WIDTH)
        self.assertTrue(
            available.contains(popup.geometry()),
            f"{popup.geometry()} is not inside {available}",
        )
        anchor_right = anchor.mapToGlobal(QPoint(anchor.width(), 0)).x()
        self.assertEqual(popup.geometry().right() + 1, anchor_right)

    def test_the_card_grows_upwards_and_never_down_over_its_button(self):
        window, anchor = self._anchor()
        popup = SupportPopup(window)
        self.addCleanup(popup.deleteLater)
        popup.show_above(anchor)
        self.addCleanup(popup.close)

        heights = []
        for count in (2, 8, SupportPopup.MAX_LISTED):
            popup.set_supporters([f"Supporter {index}" for index in range(count)])
            # Twice: the placement that matters happens on the pass after the
            # rows become measurable. See `SupportPopup._reanchor`.
            _app.processEvents()
            _app.processEvents()

            anchor_top = anchor.mapToGlobal(QPoint(0, 0)).y()
            self.assertLess(
                popup.geometry().bottom(),
                anchor_top,
                f"{count} names: the card covers the button it opens from",
            )
            heights.append(popup.geometry().height())

        self.assertEqual(heights, sorted(heights))
        self.assertLess(heights[0], heights[-1])

        # And it stops growing: `MAX_LISTED` caps the rows, so a list ten times
        # longer is exactly as tall. Nothing here can outgrow a screen.
        popup.set_supporters([f"Supporter {index}" for index in range(240)])
        _app.processEvents()
        _app.processEvents()
        self.assertEqual(popup.geometry().height(), heights[-1])

    def test_the_card_is_kept_on_the_screen(self):
        window, anchor = self._anchor()
        screen = window.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        # The anchor pushed hard against the left of the display, so that the
        # card -- wider than the space to the left of it -- would be placed at a
        # negative x and hang off the edge. Right-aligning to the anchor cannot
        # go wrong on the right; this is the side where it can.
        window.move(available.left(), available.top())
        anchor.setGeometry(10, 570, 110, 20)
        _app.processEvents()

        popup = self._open_fresh(anchor)

        self.assertTrue(
            available.contains(popup.geometry()),
            f"{popup.geometry()} is not inside {available}",
        )


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

    def test_clean_supporters_rejects_a_payload_that_is_neither_shape(self):
        # What a mis-edited file looks like: an object without the key, a bare
        # string, `null`.
        self.assertEqual(updater.clean_supporters({"names": ["a"]}), [])
        self.assertEqual(updater.clean_supporters("Grimwald"), [])
        self.assertEqual(updater.clean_supporters(None), [])

    def test_clean_supporters_reads_the_documented_object_form(self):
        # The shape that lets the instructions live in the file being edited:
        # notes under any other key, names under `supporters`.
        payload = {
            "_help": ["how to fill this in"],
            "anything else": {"nested": True},
            "supporters": ["Grimwald", {"name": "Nyxaria", "tier": "kofi"}],
        }

        self.assertEqual(
            updater.clean_supporters(payload),
            ["Grimwald", {"name": "Nyxaria", "tier": "kofi"}],
        )

    def test_the_shipped_file_is_valid_and_reads_back(self):
        # The file in the repository is the live input; a comma dropped while
        # editing the notes silently empties the card for everyone.
        path = Path(__file__).resolve().parents[2] / "supporters.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            updater.clean_supporters(payload), payload[updater.SUPPORTERS_KEY]
        )


if __name__ == "__main__":
    unittest.main()
