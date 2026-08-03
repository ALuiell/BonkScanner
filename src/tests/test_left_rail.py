from __future__ import annotations

import unittest
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app import config
from ui.layout import _template_rail_entries


class LeftRailTests(unittest.TestCase):
    def test_template_tiles_keep_panel_order_and_include_inactive_entries(self) -> None:
        templates = [
            {"name": "LIGHT", "color": "WHITE"},
            {"name": "MERCHANT", "color": "CYAN"},
            {"name": "GOOD", "color": "GREEN"},
            {"name": "PERFECT", "color": "YELLOW"},
        ]

        with patch.object(config, "TEMPLATES", templates), patch.object(
            config, "ACTIVE_TEMPLATES", ["PERFECT", "LIGHT"]
        ):
            entries = _template_rail_entries()

        self.assertEqual(
            [(name, active) for name, _colour, active in entries],
            [
                ("LIGHT", True),
                ("MERCHANT", False),
                ("GOOD", False),
                ("PERFECT", True),
            ],
        )
