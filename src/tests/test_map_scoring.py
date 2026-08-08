"""`app.map_scoring` -- the four functions step 22a took out of `TemplatesMixin`.

The call graph is what moved them: seven production calls, all from
`gui_scanner`, and none from any template-UI method in the file they shared.
See the module header for the count.

Every test here calls a module function directly. None of them builds an
app double, which is the point: `test_format_stats_includes_bald_heads_...`
needed `object.__new__(MegabonkApp)` only to reach a method whose sole use of
`self` was `self.active_templates`.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app import config
from app.map_scoring import (
    active_templates_require_bald_heads,
    calculate_map_score,
    evaluate_candidate,
    format_stats,
)


BALD_STATS = {
    "Shady Guy": 1,
    "Moais": 2,
    "Microwaves": 7,
    "Chests": 69,
    "Boss Curses": 3,
    "Magnet Shrines": 1,
    "Bald Heads": 4,
}


class FormatStatsTests(unittest.TestCase):
    def test_bald_heads_appear_when_an_active_template_requires_them(self) -> None:
        """Moved verbatim from `test_gui_run_control.py` by step 22a."""
        with patch.object(config, "EVALUATION_MODE", "templates"):
            with patch.object(config, "TEMPLATES", [{"name": "BALD", "bald_heads": 2}]):
                text = format_stats(BALD_STATS, ["BALD"])

        self.assertIn("Bald Heads: 4", text)
        self.assertIn("Microwaves: 7", text)

    def test_bald_heads_are_omitted_when_no_active_template_requires_them(self) -> None:
        with patch.object(config, "EVALUATION_MODE", "templates"):
            with patch.object(config, "TEMPLATES", [{"name": "PLAIN", "bald_heads": 0}]):
                text = format_stats(BALD_STATS, ["PLAIN"])

        self.assertNotIn("Bald Heads", text)

    def test_scores_mode_never_shows_bald_heads(self) -> None:
        """The mode check is first, so the template list is not even consulted."""
        with patch.object(config, "EVALUATION_MODE", "scores"):
            with patch.object(config, "TEMPLATES", [{"name": "BALD", "bald_heads": 2}]):
                text = format_stats(BALD_STATS, ["BALD"])

        self.assertNotIn("Bald Heads", text)


class RequireBaldHeadsTests(unittest.TestCase):
    def test_empty_active_list_is_false(self) -> None:
        with patch.object(config, "EVALUATION_MODE", "templates"):
            with patch.object(config, "TEMPLATES", [{"name": "BALD", "bald_heads": 2}]):
                self.assertFalse(active_templates_require_bald_heads([]))
                self.assertFalse(active_templates_require_bald_heads(None))

    def test_only_the_active_templates_are_consulted(self) -> None:
        templates = [
            {"name": "BALD", "bald_heads": 2},
            {"name": "PLAIN", "bald_heads": 0},
        ]
        with patch.object(config, "EVALUATION_MODE", "templates"):
            with patch.object(config, "TEMPLATES", templates):
                self.assertTrue(active_templates_require_bald_heads(["BALD"]))
                self.assertFalse(active_templates_require_bald_heads(["PLAIN"]))

    def test_zero_bald_heads_maximum_is_a_real_constraint(self) -> None:
        templates = [{"name": "NO BALD", "bald_heads_max": 0}]
        with patch.object(config, "EVALUATION_MODE", "templates"):
            with patch.object(config, "TEMPLATES", templates):
                self.assertTrue(active_templates_require_bald_heads(["NO BALD"]))


class EvaluateCandidateTests(unittest.TestCase):
    def test_templates_mode_matches_against_the_active_list(self) -> None:
        templates = [
            {
                "name": "Easy",
                "color": "GREEN",
                "shady_guys": 0,
                "moais": 0,
                "microwaves": 0,
                "boss_curses": 0,
                "magnet_shrines": 0,
                "bald_heads": 0,
            }
        ]
        stats = {"Shady Guy": 5, "Moais": 5, "Microwaves": 5, "Boss Curses": 5, "Magnet Shrines": 5}
        with patch.object(config, "EVALUATION_MODE", "templates"):
            with patch.object(config, "TEMPLATES", templates):
                matched = evaluate_candidate(stats, ["Easy"])
                unmatched = evaluate_candidate(stats, [])

        self.assertIsNotNone(matched)
        self.assertIsNone(unmatched)

    def test_scores_mode_ignores_the_active_template_list(self) -> None:
        """The parameter is unread in this branch; passing junk must not matter."""
        stats = {"Shady Guy": 1, "Moais": 1, "Boss Curses": 0, "Magnet Shrines": 0}
        with patch.object(config, "EVALUATION_MODE", "scores"):
            self.assertEqual(
                evaluate_candidate(stats, ["nonsense"]),
                evaluate_candidate(stats, []),
            )


class CalculateMapScoreTests(unittest.TestCase):
    def test_score_follows_the_configured_weights(self) -> None:
        stats = {"Shady Guy": 2, "Moais": 3, "Boss Curses": 0, "Magnet Shrines": 0}
        scores = {
            "active_tiers": [],
            "weights": {"moais": 1.0, "shady": 10.0, "boss": 0.0, "magnet": 0.0},
            "thresholds": {},
            "multipliers": {"microwave": {}},
        }
        doubled = {
            **scores,
            "weights": {"moais": 2.0, "shady": 20.0, "boss": 0.0, "magnet": 0.0},
        }
        with patch.object(config, "SCORES_SYSTEM", scores):
            base = calculate_map_score(stats)
        with patch.object(config, "SCORES_SYSTEM", doubled):
            scaled = calculate_map_score(stats)

        self.assertGreater(base, 0.0)
        self.assertAlmostEqual(scaled, base * 2.0)


if __name__ == "__main__":
    unittest.main()
