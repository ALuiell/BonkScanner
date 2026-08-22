"""The tracked-item rule builder, and the two refusals it used to swallow.

`Add Rule` was always enabled. Pressing it with nothing selected ran
`if not item_names: return`, and pressing it with an existing rule ran
`if rule["id"] not in existing_ids` -- both did nothing and said nothing, which
reads as a broken button. `add_button_state` is what turns them into answers,
so it is tested on its own before any widget exists.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections.tracked_items import (
    available_tracked_item_names,
    group_tracked_items_by_rarity,
)
from ui.dialogs.tracked_items import (
    MODE_ALL_RUN,
    MODE_MAP_ONE,
    add_button_state,
    rule_signature,
)


class AddButtonStateTests(unittest.TestCase):
    def test_nothing_selected_is_a_disabled_button_with_a_reason(self) -> None:
        enabled, message = add_button_state(
            selected=(), mode=MODE_MAP_ONE, existing_signatures=()
        )
        self.assertFalse(enabled)
        self.assertTrue(message)

    def test_a_duplicate_is_named_rather_than_swallowed(self) -> None:
        existing = [(("Anvil",), MODE_MAP_ONE)]
        enabled, message = add_button_state(
            selected=("Anvil",), mode=MODE_MAP_ONE, existing_signatures=existing
        )
        self.assertFalse(enabled)
        self.assertIn("already", message.casefold())

        # The same items under the other condition are a different rule.
        enabled, message = add_button_state(
            selected=("Anvil",), mode=MODE_ALL_RUN, existing_signatures=existing
        )
        self.assertTrue(enabled, message)
        self.assertEqual(message, "")

    def test_a_live_button_carries_no_message(self) -> None:
        enabled, message = add_button_state(
            selected=("Kevin", "Electric Plug"),
            mode=MODE_ALL_RUN,
            existing_signatures=(),
        )
        self.assertTrue(enabled)
        self.assertEqual(message, "")

    def test_blank_names_do_not_make_a_rule(self) -> None:
        enabled, _message = add_button_state(
            selected=("", "   "), mode=MODE_ALL_RUN, existing_signatures=()
        )
        self.assertFalse(enabled)

    def test_a_rules_identity_is_its_items_and_its_condition(self) -> None:
        self.assertEqual(
            rule_signature({"item_names": ["Kevin", "Electric Plug"], "mode": MODE_MAP_ONE}),
            (("Kevin", "Electric Plug"), MODE_MAP_ONE),
        )
        # A rule persisted without a mode counts for the whole run.
        self.assertEqual(rule_signature({"item_names": ["Anvil"]}), (("Anvil",), MODE_ALL_RUN))


class RarityGroupingTests(unittest.TestCase):
    def test_every_item_lands_in_exactly_one_group(self) -> None:
        names = available_tracked_item_names()
        groups = group_tracked_items_by_rarity(names)
        grouped = [name for _caption, group in groups for name in group]
        # A dropped item is an item the user cannot track.
        self.assertEqual(sorted(grouped), sorted(names))
        self.assertEqual(len(grouped), len(set(grouped)))

    def test_groups_keep_the_order_they_were_given(self) -> None:
        groups = group_tracked_items_by_rarity(available_tracked_item_names())
        captions = [caption for caption, _names in groups]
        self.assertEqual(
            captions, ["Legendary", "Epic", "Rare", "Common", "Other"]
        )
        self.assertNotIn("Uncommon", captions)
        for _caption, names in groups:
            self.assertEqual(list(names), sorted(names, key=names.index))

    def test_an_empty_list_has_no_groups(self) -> None:
        self.assertEqual(group_tracked_items_by_rarity([]), [])

    def test_a_rarity_the_captions_do_not_name_still_reaches_the_picker(self) -> None:
        """The defensive branch, reached the only way it can be.

        `RARITY_GROUP_LABELS` names every rarity that exists today, so nothing
        in production falls through -- which is exactly why this needs a test:
        add a sixth rarity to the game and the untested branch is the one
        deciding whether those items are pickable at all.
        """
        from unittest.mock import patch

        import projections.tracked_items as tracked_items

        with patch.dict(
            tracked_items.ITEM_RARITY_BY_NAME, {"Anvil": "MYTHIC"}, clear=False
        ):
            groups = group_tracked_items_by_rarity(["Anvil", "Clover"])

        grouped = [name for _caption, names in groups for name in names]
        self.assertIn("Anvil", grouped)
        self.assertIn("Clover", grouped)
        self.assertIn("Other", [caption for caption, _names in groups])


class TrackedItemPickerWidgetTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication, QLabel, QPushButton
            from ui.dialogs.tracked_items import TrackedItemPicker
            from ui.styles import build_qt_app_stylesheet

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            # `_clear_layout` removes with `deleteLater`; without the loop's
            # DeferredDelete pass the previous rows are still in the tree.
            def settle():
                app.processEvents()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                app.processEvents()

            store = {"rules": []}

            def make_rule(item_names, mode):
                return {
                    "id": "_".join(item_names).lower() + "_" + mode,
                    "label": " + ".join(item_names),
                    "item_names": list(item_names),
                    "mode": mode,
                }

            picker = TrackedItemPicker(
                rules=lambda: [dict(rule) for rule in store["rules"]],
                make_rule=make_rule,
            )
            picker.rules_changed.connect(lambda rules: store.__setitem__("rules", rules))
            picker.resize(900, 560)
            picker.show()
            settle()

            def widget(cls, name):
                return [w for w in picker.findChildren(cls) if w.objectName() == name]

            def add_button():
                return [b for b in picker.findChildren(QPushButton) if b.text() == "Add"][0]

            def note():
                return widget(QLabel, "addNote")[0].text()
            """
        ) + textwrap.dedent(body)
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_button_refuses_out_loud_in_both_cases(self) -> None:
        self._run(
            """
            assert not add_button().isEnabled()
            assert "Pick one" in note(), note()

            picker.pick("Anvil")
            settle()
            assert add_button().isEnabled()
            assert note() == "", note()

            add_button().click()
            settle()
            assert len(store["rules"]) == 1, store["rules"]
            assert store["rules"][0]["item_names"] == ["Anvil"]
            assert store["rules"][0]["mode"] == "map_1_only"

            # ...and the same rule again is named, not swallowed.
            picker.pick("Anvil")
            settle()
            assert not add_button().isEnabled()
            assert "already" in note().casefold(), note()
            """
        )

    def test_adding_clears_the_selection_so_the_next_rule_starts_empty(self) -> None:
        # The old dialog called `clearSelection()` for the same reason; losing
        # it would silently fold the next rule into the previous one's items.
        self._run(
            """
            picker.pick("Kevin")
            picker.pick("Electric Plug")
            settle()
            assert picker.selected_items == ("Kevin", "Electric Plug")

            add_button().click()
            settle()
            assert picker.selected_items == (), picker.selected_items
            assert store["rules"][0]["item_names"] == ["Kevin", "Electric Plug"]
            """
        )

    def test_the_condition_is_a_choice_and_it_reaches_the_rule(self) -> None:
        """Driven by clicking the segment, which is the part that was broken.

        The first version of this case called `picker._on_mode("all_run")`
        directly and passed while the window could not do it at all: segments
        default to disabling whatever is not lit -- right when they are an
        action and its undo, wrong when they are two choices -- so "Whole run"
        was unclickable and an `all_run` rule could not be made.
        """
        self._run(
            """
            assert picker.mode == "map_1_only"
            segments = picker._mode_toggle
            assert segments.segment("all_run").isEnabled(), "the other choice is dead"
            assert segments.segment("map_1_only").isEnabled()

            segments.segment("all_run").click()
            settle()
            assert picker.mode == "all_run"

            picker.pick("Clover")
            settle()
            add_button().click()
            settle()
            assert store["rules"][0]["mode"] == "all_run", store["rules"]

            # ...and back, so neither choice is a one-way door.
            segments.segment("map_1_only").click()
            settle()
            assert picker.mode == "map_1_only"
            """
        )

    def test_the_remove_button_actually_draws_its_glyph(self) -> None:
        """It rendered as an empty rounded box, which reads as a checkbox.

        `#chipRemove` set no padding, so it inherited the base `QPushButton`
        rule's `9px 14px`; in a 20x20 button that leaves negative room for the
        text and Qt clipped the glyph away entirely. Nothing raised -- the
        button worked, it just had nothing on it.
        """
        self._run(
            """
            from PySide6.QtGui import QPixmap

            picker.pick("Clover")
            settle()
            add_button().click()
            settle()

            buttons = [
                b for b in picker.findChildren(QPushButton)
                if b.objectName() == "chipRemove"
            ]
            assert len(buttons) == 1, buttons
            button = buttons[0]
            pixmap = QPixmap(button.size())
            pixmap.fill()
            button.render(pixmap)
            image = pixmap.toImage()

            # Ink anywhere inside the border, where the glyph belongs.
            inset = 4
            ink = sum(
                1
                for x in range(inset, button.width() - inset)
                for y in range(inset, button.height() - inset)
                if image.pixelColor(x, y).value() < 200
            )
            assert ink > 8, f"the glyph is missing: {ink} ink pixels"
            """
        )

    def test_the_groups_are_captioned_and_the_search_narrows_them(self) -> None:
        self._run(
            """
            captions = [w.text() for w in widget(QLabel, "pickerGroup")]
            assert captions[0].startswith("Legendary"), captions
            assert any(c.startswith("Common") for c in captions), captions

            picker._on_search("bonk")
            settle()
            captions = [w.text() for w in widget(QLabel, "pickerGroup")]
            assert captions == ["Legendary \\u00b7 1"], captions

            picker._on_search("zzzz")
            settle()
            shown = [w.text() for w in widget(QLabel, "tableEmpty") if w.isVisible()]
            assert any("Nothing matches" in text for text in shown), shown
            """
        )

    def test_each_item_keeps_its_own_rarity_colour(self) -> None:
        """Sampled from the rendered widget, because nothing else catches it.

        The chips are styled per item with a hex the projection supplies, and
        the first version tinted it by appending alpha -- `#FACC15` + `44`. Qt
        reads eight-digit hex as `#AARRGGBB`, so that came out as
        `rgb(204, 21, 68)` and every rarity in the picker rendered as a shade
        of crimson: legendary yellow, uncommon blue and common green all
        shifted by one byte. Nothing raised and no assertion here failed; it
        was visible only on screen.
        """
        self._run(
            """
            from PySide6.QtGui import QPixmap
            from projections.tracked_items import tracked_item_color

            def rendered_colour(item_name):
                button = picker._picks[item_name]
                pixmap = QPixmap(button.size())
                pixmap.fill()
                button.render(pixmap)
                image = pixmap.toImage()
                best, best_saturation = None, -1
                for x in range(button.width()):
                    for y in range(button.height()):
                        colour = image.pixelColor(x, y)
                        if colour.value() > 60 and colour.saturation() > best_saturation:
                            best, best_saturation = colour, colour.saturation()
                return best.name().lower()

            for item in ("Anvil", "Kevin", "Electric Plug", "Clover"):
                expected = tracked_item_color(item).lower()
                actual = rendered_colour(item)
                assert actual == expected, (item, expected, actual)
            """
        )

    def test_removing_a_rule_takes_only_that_one(self) -> None:
        self._run(
            """
            picker.pick("Anvil")
            add_button().click()
            settle()
            picker.pick("Clover")
            add_button().click()
            settle()
            assert len(store["rules"]) == 2

            picker.remove_rule(store["rules"][0]["id"])
            settle()
            assert len(store["rules"]) == 1, store["rules"]
            assert store["rules"][0]["item_names"] == ["Clover"]

            picker.clear_rules()
            settle()
            assert store["rules"] == []
            """
        )


if __name__ == "__main__":
    unittest.main()
