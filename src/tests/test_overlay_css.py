"""Structural checks for data-stable OBS overlay sizing."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


CSS_PATH = Path(__file__).resolve().parents[1] / "media" / "overlay" / "overlay.css"


class StageSummarySizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        cls.css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def _rule(self, selector: str) -> str:
        match = re.search(
            r"^[ \t]*" + re.escape(selector) + r"\s*\{(?P<body>.*?)\}",
            self.css,
            re.M | re.S,
        )
        self.assertIsNotNone(match, f"missing CSS rule: {selector}")
        return match.group("body")

    def test_grid_shell_has_no_fixed_pixel_cap(self) -> None:
        shell = self._rule(".overlay-shell")

        self.assertIn("max-width: 100vw", shell)
        self.assertNotRegex(shell, r"max-width:\s*min\(100vw,\s*\d+px\)")

    def test_panels_support_a_widget_natural_width_contract(self) -> None:
        panel = self._rule(".panel")
        custom_panel = self._rule(".widget-wrapper.custom-size-active .panel")

        self.assertIn("min-width: var(--widget-natural-width, 0)", panel)
        self.assertIn("min-width: 0 !important", custom_panel)

    def test_stage_summary_reserves_the_same_width_in_both_layout_modes(self) -> None:
        panel = self._rule(".stage-summary-widget")
        absolute_wrapper = self._rule(
            '.widget-wrapper[data-id="stage_summary"]:not(.custom-size-active)'
        )

        natural_width = re.search(
            r"--widget-natural-width:\s*calc\((\d+)px", panel
        )
        wrapper_width = re.search(r"min-width:\s*calc\((\d+)px", absolute_wrapper)
        self.assertIsNotNone(natural_width)
        self.assertIsNotNone(wrapper_width)
        self.assertIn("width: var(--widget-natural-width)", panel)
        self.assertEqual(natural_width.group(1), wrapper_width.group(1))

    def test_each_item_slot_reserves_two_digit_width(self) -> None:
        counts = self._rule(".stage-item-counts")
        count = self._rule(".stage-item-count")

        self.assertIn(
            "repeat(4, minmax(calc(38px * var(--scale)), max-content))",
            counts,
        )
        self.assertIn("min-width: calc(38px * var(--scale))", count)
        self.assertIn("font-variant-numeric: tabular-nums", count)


class BuildProgressionColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        cls.css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def _rule(self, selector: str) -> str:
        match = re.search(
            r"^[ \t]*" + re.escape(selector) + r"\s*\{(?P<body>.*?)\}",
            self.css,
            re.M | re.S,
        )
        self.assertIsNotNone(match, f"missing CSS rule: {selector}")
        return match.group("body")

    def test_min_met_uses_green_check_and_stats_cyan_hint(self) -> None:
        self.assertIn("#59D890", self._rule(".build-row.min-met .build-symbol"))
        self.assertIn("var(--hud-cyan)", self._rule(".build-row.min-met .build-time"))

    def test_late_rules_follow_min_met_rules_and_keep_priority(self) -> None:
        self.assertLess(
            self.css.index(".build-row.min-met .build-time"),
            self.css.index(".build-row.late .build-time"),
        )
        self.assertIn("#F97316", self._rule(".build-row.late .build-time"))


if __name__ == "__main__":
    unittest.main()
