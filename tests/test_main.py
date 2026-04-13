from __future__ import annotations

import sys
import types
import unittest

sys.modules.setdefault(
    "keyboard",
    types.SimpleNamespace(
        add_hotkey=lambda *args, **kwargs: None,
        press=lambda *args, **kwargs: None,
        release=lambda *args, **kwargs: None,
        press_and_release=lambda *args, **kwargs: None,
    ),
)

from main import confirm_template_match


class MainFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.templates = [
            {"id": 1, "name": "GOOD", "color": "GREEN", "sm_total": 8, "micro": 2, "boss": 1},
            {"id": 2, "name": "PERFECT+", "color": "LIGHTRED_EX", "sm_total": 9, "micro": 2, "boss": 3},
        ]
        self.active_templates = ["GOOD", "PERFECT+"]

    def test_confirm_template_match_returns_none_when_initial_stats_do_not_match(self) -> None:
        initial_stats = {
            "Boss Curses": 0,
            "Challenges": 0,
            "Charge Shrines": 0,
            "Chests": 0,
            "Greed Shrines": 0,
            "Magnet Shrines": 0,
            "Microwaves": 1,
            "Moais": 3,
            "Pots": 0,
            "Shady Guy": 4,
        }
        confirmed_stats = {
            **initial_stats,
            "Microwaves": 2,
            "Boss Curses": 3,
        }

        self.assertIsNone(
            confirm_template_match(
                initial_stats,
                confirmed_stats,
                self.active_templates,
                self.templates,
            )
        )

    def test_confirm_template_match_returns_none_when_confirmation_fails(self) -> None:
        initial_stats = {
            "Boss Curses": 3,
            "Challenges": 0,
            "Charge Shrines": 0,
            "Chests": 0,
            "Greed Shrines": 0,
            "Magnet Shrines": 0,
            "Microwaves": 2,
            "Moais": 4,
            "Pots": 0,
            "Shady Guy": 5,
        }
        confirmed_stats = {
            **initial_stats,
            "Boss Curses": 0,
        }

        self.assertIsNone(
            confirm_template_match(
                initial_stats,
                confirmed_stats,
                self.active_templates,
                self.templates,
            )
        )

    def test_confirm_template_match_returns_confirmed_template(self) -> None:
        initial_stats = {
            "Boss Curses": 3,
            "Challenges": 0,
            "Charge Shrines": 0,
            "Chests": 0,
            "Greed Shrines": 0,
            "Magnet Shrines": 0,
            "Microwaves": 2,
            "Moais": 4,
            "Pots": 0,
            "Shady Guy": 5,
        }
        confirmed_stats = dict(initial_stats)

        template = confirm_template_match(
            initial_stats,
            confirmed_stats,
            self.active_templates,
            self.templates,
        )

        self.assertIsNotNone(template)
        self.assertEqual(template["name"], "PERFECT+")


if __name__ == "__main__":
    unittest.main()
