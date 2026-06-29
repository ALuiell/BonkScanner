from __future__ import annotations

import src

import unittest

from gui_shared import build_template_payload, format_template_conditions


class GuiSharedTests(unittest.TestCase):
    def test_build_template_payload_includes_bald_heads(self) -> None:
        payload = build_template_payload(
            "BALD",
            "0",
            "0",
            "0",
            "0",
            "0",
            "3",
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["bald_heads"], 3)

    def test_format_template_conditions_shows_bald_heads(self) -> None:
        text = format_template_conditions({"name": "BALD", "bald_heads": 3})

        self.assertEqual(text, "BH:3")


if __name__ == "__main__":
    unittest.main()