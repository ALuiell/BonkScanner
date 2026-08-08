from __future__ import annotations

import src

import unittest

from pathlib import Path

from ui import shared as gui_shared
from ui.shared import build_template_payload, format_template_conditions
from infra import paths


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

    def test_build_template_payload_includes_magnet_requirement(self) -> None:
        payload = build_template_payload("MAGNET", "0", "0", "0", "0", "0", "", "2")

        self.assertIsNotNone(payload)
        self.assertEqual(payload["magnet"], 2)

    def test_format_template_conditions_shows_bald_heads(self) -> None:
        text = format_template_conditions({"name": "BALD", "bald_heads": 3})

        self.assertEqual(text, "BH≥3")

    def test_format_template_conditions_shows_magnet_requirement(self) -> None:
        text = format_template_conditions({"name": "MAGNET", "magnet": 2})

        self.assertEqual(text, "Mag≥2")

    def test_build_template_payload_distinguishes_blank_and_zero_maximum(self) -> None:
        payload = build_template_payload(
            "NO CHALLENGES",
            "0",
            "0",
            "0",
            "0",
            "0",
            "",
            "0",
            challenges="0",
            magnet_max="",
            challenges_max="0",
        )

        self.assertIsNotNone(payload)
        self.assertNotIn("magnet_max", payload)
        self.assertEqual(payload["challenges"], 0)
        self.assertEqual(payload["challenges_max"], 0)

    def test_build_template_payload_rejects_minimum_above_maximum(self) -> None:
        payload = build_template_payload(
            "INVALID",
            "0",
            "0",
            "0",
            "0",
            "0",
            "",
            "2",
            magnet_max="1",
        )

        self.assertIsNone(payload)

    def test_format_template_conditions_shows_minimums_and_zero_maximums(self) -> None:
        text = format_template_conditions(
            {
                "name": "STRICT",
                "sm_total": 8,
                "micro": 2,
                "magnet_max": 0,
                "challenges_max": 0,
            }
        )

        self.assertEqual(text, "S+M≥8, Mic≥2, Mag≤0, Ch≤0")

    def test_format_template_conditions_shows_both_bounds(self) -> None:
        text = format_template_conditions({"name": "RANGE", "moai": 2, "moai_max": 4})

        self.assertEqual(text, "M≥2, M≤4")


if __name__ == "__main__":
    unittest.main()

class ResourcePathAnchorTests(unittest.TestCase):
    """resource_path derives its anchor from ui/shared.py's own __file__.

    The move this test was written to catch has now happened: step 17a did
    `git mv src/gui_shared.py src/ui/shared.py`, and the derivation went from
    one dirname to two so that media/ still resolves under src/ and everything
    else under the repository root. Left alone it would have repointed the
    user's config.json at src/config.json -- the step-10b failure, which went
    unnoticed for two commits.

    This test did its job: it failed on the move and was made to pass by fixing
    the anchor, not by relaxing the assertion. Both resolved values below are
    unchanged from before the move, which is the whole claim.

    It cannot simply import infra/paths: ui/ must never reach infra/, and this
    file is ui/ code.
    """

    def test_media_resolves_under_src(self) -> None:
        resolved = Path(gui_shared.resource_path("media/overlay/index.html"))
        self.assertTrue(resolved.is_file(), f"not found: {resolved}")
        self.assertEqual(resolved.parent.parent.parent.name, "src")

    def test_non_media_resolves_at_the_repository_root(self) -> None:
        # The checkout name is derived from this file's own location rather than
        # spelled out. It used to read "MegabonkReroll", which made the test a
        # statement about one directory on one machine: this tree is a copy of
        # that repository under a different name, so the assertion failed here
        # for a reason that has nothing to do with the anchor being wrong.
        # `parents[2]` is the repository root -- src/tests/this_file.py.
        repository_root = Path(__file__).resolve().parents[2]
        resolved = Path(gui_shared.resource_path("config.json"))
        self.assertEqual(resolved.parent.name, repository_root.name)
        self.assertEqual(resolved.parent, Path(paths.application_path()))
