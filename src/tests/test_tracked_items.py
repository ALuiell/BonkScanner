"""`projections/tracked_items.py` -- the pure tracked-item naming helpers.

Moved here by step 24a, not duplicated. These three assertions lived in
`test_gui_run_control.py` as unbound `OverlayMixin.<helper>(...)` calls, which
is the very idiom the componentization inventory measures: the subject moved
out of the class, so the tests move with it. Same treatment steps 21d and 22c
gave their relocated tests.

The subject needs no app, no widgets and no `QApplication` -- which is the
point of the move.
"""

from __future__ import annotations

import unittest

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections.tracked_items import (
    available_tracked_item_names,
    tracked_item_display_name,
    tracked_rule_display_label,
)
from tracked_item_rules import tracked_item_rules_from_config


class TrackedItemNamingTests(unittest.TestCase):
    def test_tracked_item_display_name_prefers_live_inventory_aliases(self) -> None:
        self.assertEqual(tracked_item_display_name("Glove Power"), "Power Gloves")
        self.assertEqual(tracked_item_display_name("Glove Blood"), "Slurp Gloves")
        self.assertEqual(tracked_item_display_name("Glove Lightning"), "Thunder Mitts")
        self.assertEqual(tracked_item_display_name("Pot"), "Pot (stainless steel)")
        self.assertEqual(tracked_item_display_name("Wrench"), "Wrench")

    def test_available_tracked_item_names_use_game_ui_names(self) -> None:
        names = available_tracked_item_names()

        self.assertIn("Bob's Light", names)
        self.assertIn("Crypt key", names)
        self.assertIn("Golden key", names)
        self.assertIn("Slurp Gloves", names)
        self.assertIn("The One Ring", names)
        self.assertNotIn("Bobs Lantern", names)

    def test_tracked_rule_display_label_prefers_live_alias_for_default_labels(self) -> None:
        self.assertEqual(
            tracked_rule_display_label(
                {"label": "Glove Power Map 1"},
                ["Glove Power"],
                "map_1_only",
            ),
            "Power Gloves Map 1",
        )
        self.assertEqual(
            tracked_rule_display_label(
                {"label": "Glove Blood"},
                ["Glove Blood"],
                "all_run",
            ),
            "Slurp Gloves",
        )
        self.assertEqual(
            tracked_rule_display_label(
                {"label": "Custom Gloves Label"},
                ["Glove Power"],
                "all_run",
            ),
            "Custom Gloves Label",
        )

    def test_non_finite_rule_limits_are_unknown_not_infinite(self) -> None:
        rules = tracked_item_rules_from_config(
            {
                "tracked_items": [
                    {
                        "id": "anvil",
                        "label": "Anvil",
                        "item_names": ["Anvil"],
                        "mode": "all_run",
                        "before_seconds": float("inf"),
                        "max_copies": float("inf"),
                    }
                ]
            }
        )

        self.assertIsNone(rules[0].before_seconds)
        self.assertIsNone(rules[0].max_copies)


if __name__ == "__main__":
    unittest.main()
