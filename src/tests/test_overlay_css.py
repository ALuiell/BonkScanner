"""Structural checks for data-stable OBS overlay sizing."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


CSS_PATH = Path(__file__).resolve().parents[1] / "media" / "overlay" / "overlay.css"


class StageSummarySizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def _rule(self, selector: str) -> str:
        match = re.search(re.escape(selector) + r"\s*\{(?P<body>.*?)\}", self.css, re.S)
        self.assertIsNotNone(match, f"missing CSS rule: {selector}")
        return match.group("body")

    def test_stage_summary_reserves_the_same_width_in_both_layout_modes(self) -> None:
        panel = self._rule(".stage-summary-widget")
        absolute_wrapper = self._rule(
            '.widget-wrapper[data-id="stage_summary"]:not(.custom-size-active)'
        )

        panel_width = re.search(r"width:\s*calc\((\d+)px", panel)
        wrapper_width = re.search(r"min-width:\s*calc\((\d+)px", absolute_wrapper)
        self.assertIsNotNone(panel_width)
        self.assertIsNotNone(wrapper_width)
        self.assertEqual(panel_width.group(1), wrapper_width.group(1))

    def test_each_item_slot_reserves_two_digit_width(self) -> None:
        counts = self._rule(".stage-item-counts")
        count = self._rule(".stage-item-count")

        self.assertIn(
            "repeat(4, minmax(calc(38px * var(--scale)), max-content))",
            counts,
        )
        self.assertIn("min-width: calc(38px * var(--scale))", count)
        self.assertIn("font-variant-numeric: tabular-nums", count)


if __name__ == "__main__":
    unittest.main()
