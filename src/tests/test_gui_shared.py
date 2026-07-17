from __future__ import annotations

import src

import unittest

from pathlib import Path

import gui_shared
from gui_shared import build_template_payload, format_template_conditions
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

    def test_format_template_conditions_shows_bald_heads(self) -> None:
        text = format_template_conditions({"name": "BALD", "bald_heads": 3})

        self.assertEqual(text, "BH:3")


if __name__ == "__main__":
    unittest.main()

class ResourcePathAnchorTests(unittest.TestCase):
    """resource_path derives its anchor from gui_shared's own __file__.

    That is correct while this module sits in src/, and breaks the moment it
    moves -- which step 14 (gui_shared.py -> ui/shared.py) will do. The same
    derivation in config.py and overlay_server.py was broken by step 10b and
    nothing noticed for two commits, so pin the resolved values here: this test
    fails the moment the anchor shifts, whoever shifts it.

    It cannot simply import infra/paths: ui/ must never reach infra/, and this
    file is ui/-destined. Deciding that anchor is step 14's problem; noticing is
    this test's.
    """

    def test_media_resolves_under_src(self) -> None:
        resolved = Path(gui_shared.resource_path("media/overlay/index.html"))
        self.assertTrue(resolved.is_file(), f"not found: {resolved}")
        self.assertEqual(resolved.parent.parent.parent.name, "src")

    def test_non_media_resolves_at_the_repository_root(self) -> None:
        resolved = Path(gui_shared.resource_path("config.json"))
        self.assertEqual(resolved.parent.name, "MegabonkReroll")
        self.assertEqual(resolved.parent, Path(paths.application_path()))
