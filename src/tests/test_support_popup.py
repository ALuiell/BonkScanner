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
from unittest.mock import patch

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from app import supporters as supporters_flow
from app import config
from infra import updater
from ui.dialogs import update_prompt
from ui.footer import SUPPORT_BADGE_ICON_SIZE, SupportPopup
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
    known = {
        "supporterName",
        *(style[0] for style in SupportPopup.SOURCE_STYLES.values()),
    }
    return [
        (label.text(), label.objectName())
        for label in popup.findChildren(QLabel)
        if label.objectName() in known
        and not label.isHidden()
        and not label.parentWidget().isHidden()
    ]


def _badges(popup):
    """Badge keys drawn beside each visible name, in their visual order."""
    result = {}
    for row in popup.findChildren(QWidget, "supporterNameRow"):
        if row.isHidden():
            continue
        name_labels = [
            label
            for label in row.findChildren(QLabel)
            if label.objectName().startswith("supporterName")
            and label.objectName() != "supporterNameBadgeIcon"
        ]
        icons = row.findChildren(QLabel, "supporterNameBadgeIcon")
        if name_labels:
            result[name_labels[0].text()] = tuple(
                icon.property("badge") for icon in icons
            )
    return result


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

    def test_support_routes_include_crypto_without_a_placeholder_link(self):
        buttons = {
            button.objectName(): button
            for button in self.popup.findChildren(QPushButton)
        }

        self.assertEqual(buttons["PatreonButton"].text(), "Patreon")
        self.assertEqual(buttons["CryptoButton"].text(), "Crypto")
        self.assertFalse(buttons["PatreonButton"].icon().isNull())
        self.assertFalse(buttons["CryptoButton"].icon().isNull())
        self.assertEqual(
            buttons["CryptoButton"].isEnabled(),
            bool(config.CRYPTO_SUPPORT_URL),
        )

    def test_blank_and_malformed_entries_do_not_become_rows(self):
        self.popup.set_supporters(
            ["", "  ", {"name": ""}, {"source": "patreon"}, None]
        )
        self.assertEqual(_names(self.popup), [])
        self.assertEqual(self.popup._card.width(), SupportPopup.NARROW_WIDTH)

    def test_plain_names_and_mappings_are_both_accepted(self):
        self.popup.set_supporters(
            [
                "Grimwald",
                {
                    "name": "Nyxaria",
                    "source": "patreon",
                    "badges": ["active_sub"],
                },
            ]
        )
        self.assertIn("Grimwald", _names(self.popup))
        self.assertTrue(any("Nyxaria" in name for name in _names(self.popup)))
        self.assertEqual(self.popup._card.width(), SupportPopup.WIDE_WIDTH)

    def test_supporter_title_uses_singular_and_plural_grammar(self):
        self.popup.set_supporters(["PrestoOmento"])
        self.assertEqual(self.popup._title.text(), "1 person supports BonkScanner")

        self.popup.set_supporters(["PrestoOmento", "Nyxaria"])
        self.assertEqual(self.popup._title.text(), "2 people support BonkScanner")

    def test_legend_and_names_have_breathing_room(self):
        self.assertEqual(self.popup._legend.layout().spacing(), 5)

        margins = self.popup._names_grid.contentsMargins()

        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            (0, 7, 0, 4),
        )

    def test_legend_explains_platform_colours_and_status_badges(self):
        self.popup.set_supporters(["PrestoOmento"])
        caption_names = {
            "supporterLegendPatreon",
            "supporterLegendDirect",
            "supporterLegendSourceHeading",
            "supporterLegendBadgesHeading",
            "supporterLegendFounder",
            "supporterLegendExtraSupport",
            "supporterLegendSub",
        }
        labels = {
            label.objectName(): label.text()
            for label in self.popup._legend.findChildren(QLabel)
            if label.objectName() in caption_names
        }

        self.assertTrue(self.popup._legend.isVisibleTo(self.popup))
        self.assertEqual(
            labels,
            {
                "supporterLegendPatreon": "●  Patreon",
                "supporterLegendDirect": "●  Direct",
                "supporterLegendSourceHeading": "Source:",
                "supporterLegendBadgesHeading": "Badges:",
                "supporterLegendFounder": "Founder",
                "supporterLegendExtraSupport": "Extra support",
                "supporterLegendSub": "Active sub",
            },
        )
        legend_icons = [
            label
            for label in self.popup._legend.findChildren(QLabel)
            if label.objectName().endswith("Icon")
        ]
        self.assertEqual(
            [icon.property("badge") for icon in legend_icons],
            ["founder", "extrasupport", "activesub"],
        )
        self.assertEqual(SUPPORT_BADGE_ICON_SIZE, 15)
        self.assertTrue(
            all(icon.size() == QSize(15, 15) for icon in legend_icons)
        )
        self.popup.show()
        _app.processEvents()
        self.popup.grab()
        self.assertTrue(
            all(not icon._tinted_pixmap.isNull() for icon in legend_icons)
        )
        self.assertTrue(
            all(
                abs(
                    icon._tinted_pixmap.devicePixelRatioF()
                    - icon.devicePixelRatioF()
                )
                < 0.001
                for icon in legend_icons
            )
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
                {
                    "name": "patreon name",
                    "source": "patreon",
                    "badges": ["active_sub"],
                },
                {
                    "name": "direct name",
                    "source": "direct",
                    "badges": ["extra_support"],
                },
            ]
        )
        popup.ensurePolished()

        for legend_name, supporter_name, expected_colour in (
            ("supporterLegendPatreon", "supporterNamePatreon", "#FF6F61"),
            ("supporterLegendDirect", "supporterNameDirect", "#29ABE0"),
        ):
            legend = popup.findChild(QLabel, legend_name)
            supporter = popup.findChild(QLabel, supporter_name)
            legend.ensurePolished()
            supporter.ensurePolished()
            self.assertEqual(
                legend.palette().color(QPalette.WindowText),
                supporter.palette().color(QPalette.WindowText),
            )
            self.assertEqual(
                supporter.palette().color(QPalette.WindowText).name().upper(),
                expected_colour,
            )

        popup.show()
        _app.processEvents()
        popup.grab()
        for supporter_name in ("supporterNamePatreon", "supporterNameDirect"):
            supporter = popup.findChild(QLabel, supporter_name)
            expected_colour = supporter.palette().color(QPalette.WindowText)
            icons = supporter.parentWidget().findChildren(
                QLabel, "supporterNameBadgeIcon"
            )
            self.assertTrue(icons)
            self.assertTrue(
                all(icon._rendered_color == expected_colour for icon in icons)
            )

    def test_two_row_legend_does_not_clip_any_caption(self):
        previous_stylesheet = _app.styleSheet()
        self.addCleanup(_app.setStyleSheet, previous_stylesheet)
        checkmark_path = resource_path("media/checkmark.svg").replace("\\", "/")
        _app.setStyleSheet(build_qt_app_stylesheet(checkmark_path))

        self.popup.set_supporters(["PrestoOmento"])
        self.popup.show()
        _app.processEvents()

        for label in self.popup._legend.findChildren(QLabel):
            with self.subTest(label=label.objectName()):
                self.assertGreaterEqual(label.width(), label.sizeHint().width())

    def test_source_controls_colour_and_badges_control_icons(self):
        self.popup.set_supporters(
            [
                {
                    "name": "sub",
                    "source": "patreon",
                    "badges": ["active_sub"],
                },
                {
                    "name": "buyer",
                    "source": "patreon",
                    "badges": ["extra_support"],
                },
                {
                    "name": "direct",
                    "source": "direct",
                    "badges": ["extra_support"],
                },
                "nobody",
            ]
        )

        styles = {text: name for text, name in _rows(self.popup)}
        self.assertEqual(styles["sub"], "supporterNamePatreon")
        self.assertEqual(styles["buyer"], "supporterNamePatreon")
        self.assertEqual(styles["direct"], "supporterNameDirect")
        self.assertEqual(styles["nobody"], "supporterName")

        self.assertEqual(
            _badges(self.popup),
            {
                "sub": ("activesub",),
                "buyer": ("extrasupport",),
                "direct": ("extrasupport",),
                "nobody": (),
            },
        )

    def test_legacy_tiers_keep_their_colour_and_badges_during_migration(self):
        self.popup.set_supporters(
            [
                {
                    "name": "legacy subscriber",
                    "tier": "patreon",
                    "badges": ["founder", "pack"],
                },
                {"name": "legacy pack", "tier": "pack"},
            ]
        )

        self.assertEqual(
            _rows(self.popup),
            [
                ("legacy subscriber", "supporterNamePatreon"),
                ("legacy pack", "supporterNamePatreon"),
            ],
        )
        self.assertEqual(
            _badges(self.popup),
            {
                "legacy subscriber": ("founder", "extrasupport", "activesub"),
                "legacy pack": ("extrasupport",),
            },
        )

    def test_new_source_takes_priority_over_a_legacy_tier(self):
        self.popup.set_supporters(
            [
                {
                    "name": "new schema",
                    "source": "direct",
                    "tier": "patreon",
                    "badges": ["extra_support"],
                }
            ]
        )

        self.assertEqual(
            _rows(self.popup),
            [("new schema", "supporterNameDirect")],
        )
        self.assertEqual(_badges(self.popup), {"new schema": ("extrasupport",)})

    def test_founder_extra_support_and_active_sub_stack_in_stable_order(self):
        self.popup.set_supporters(
            [
                {
                    "name": "PrestoOmento",
                    "source": "patreon",
                    "badges": [
                        "active_sub",
                        "extra_support",
                        "founder",
                        "extra_support",
                    ],
                }
            ]
        )

        self.assertEqual(
            _rows(self.popup),
            [("PrestoOmento", "supporterNamePatreon")],
        )
        self.assertEqual(
            _badges(self.popup),
            {"PrestoOmento": ("founder", "extrasupport", "activesub")},
        )

    def test_sources_group_in_order_and_keep_the_files_order_inside_a_group(self):
        self.popup.set_supporters(
            [
                "plain one",
                {"name": "direct one", "source": "direct"},
                {"name": "patreon one", "source": "patreon"},
                {"name": "patreon two", "source": "patreon"},
            ]
        )

        self.assertEqual(
            [text for text, _name in _rows(self.popup)],
            ["patreon one", "patreon two", "direct one", "plain one"],
        )

    def test_a_source_is_matched_however_it_was_typed(self):
        self.popup.set_supporters(
            [
                {"name": "a", "source": "Direct"},
                {"name": "b", "source": " DIRECT "},
                {"name": "c", "source": "di_rect"},
            ]
        )

        self.assertEqual(
            {name for _text, name in _rows(self.popup)}, {"supporterNameDirect"}
        )

    def test_an_unknown_source_stays_neutral_but_keeps_the_support_badge(self):
        self.popup.set_supporters(
            [
                {
                    "name": "typo",
                    "source": "patrn",
                    "badges": ["extra_support"],
                }
            ]
        )

        self.assertEqual(_rows(self.popup), [("typo", "supporterName")])
        self.assertEqual(_badges(self.popup), {"typo": ("extrasupport",)})

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
        popup.set_supporters(
            ["Grimwald", {"name": "Nyxaria", "source": "patreon"}]
        )
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

        popup.set_supporters(
            ["Grimwald", {"name": "Nyxaria", "source": "patreon"}]
        )
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

    def test_load_refreshes_every_ten_minutes_without_duplicate_loops(self):
        class Footer:
            def __init__(self) -> None:
                self.received = []

            def set_supporters(self, supporters) -> None:
                self.received.append(list(supporters))

        class App:
            def __init__(self) -> None:
                self.footer = Footer()
                self.scheduled = []
                self._is_shutting_down = False

            def after(self, delay_ms, callback) -> None:
                if delay_ms == 0:
                    callback()
                else:
                    self.scheduled.append((delay_ms, callback))

        app = App()
        workers = []
        loads = []

        class Worker:
            @staticmethod
            def is_alive() -> bool:
                return False

        def load(report) -> None:
            loads.append(len(loads) + 1)
            report([f"supporter {loads[-1]}"])

        def start_inline(_app, *, target, args=(), kwargs=None, name):
            self.assertEqual(name, "BonkSupportersLoad")
            target(*args, **(kwargs or {}))
            worker = Worker()
            workers.append(worker)
            _app.__dict__.setdefault("_background_threads", set()).add(worker)
            return worker

        with (
            patch.object(update_prompt, "load_supporters", side_effect=load),
            patch.object(
                update_prompt,
                "_start_registered_thread",
                side_effect=start_inline,
            ),
        ):
            first_worker = update_prompt.start_supporters_load(app)
            self.assertIs(first_worker, workers[0])
            self.assertIsNone(update_prompt.start_supporters_load(app))
            self.assertEqual(loads, [1])
            self.assertEqual(app.footer.received, [["supporter 1"]])
            self.assertEqual(len(app.scheduled), 1)

            delay_ms, refresh = app.scheduled.pop()
            self.assertEqual(
                delay_ms,
                update_prompt.SUPPORTERS_REFRESH_INTERVAL_MS,
            )
            second_worker = refresh()
            self.assertIs(second_worker, workers[1])
            self.assertEqual(loads, [1, 2])
            self.assertEqual(app.footer.received[-1], ["supporter 2"])
            self.assertNotIn(first_worker, app._background_threads)
            self.assertIn(second_worker, app._background_threads)

            _delay_ms, refresh = app.scheduled.pop()
            app._is_shutting_down = True
            self.assertIsNone(refresh())
            self.assertEqual(loads, [1, 2])
            self.assertEqual(app.scheduled, [])

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
            "supporters": ["Grimwald", {"name": "Nyxaria", "source": "direct"}],
        }

        self.assertEqual(
            updater.clean_supporters(payload),
            ["Grimwald", {"name": "Nyxaria", "source": "direct"}],
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
