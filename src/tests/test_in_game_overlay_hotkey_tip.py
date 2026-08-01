"""The layout tip names the hotkey, so it has to be re-rendered with it.

Layout mode is reachable by hotkey and by nothing else -- the `Edit Layout`
button that used to sit on this tab is gone. That makes this sentence the only
place the app says how to get in, and it prints the key inside the sentence. A
tip left saying `Press F9` after the key moved to F10 does not look broken; it
looks like an instruction, and following it does nothing.

Both editors of the key route through `refresh_in_game_overlay_hotkey_ui` -- the
field on this tab and the Settings dialog -- so testing the one function covers
both. No Qt: the function touches two widgets through `getattr`, and stand-ins
are enough to say what it wrote.
"""

from __future__ import annotations

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

import unittest
from unittest.mock import patch

from app import config
from gui_in_game_overlay_settings import refresh_in_game_overlay_hotkey_ui


class _Label:
    def __init__(self) -> None:
        self.text_value = ""

    def setText(self, text: str) -> None:
        self.text_value = str(text)


class _Entry(_Label):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.text_value = text
        self.blocked = False

    def text(self) -> str:
        return self.text_value

    def blockSignals(self, blocked: bool) -> None:
        self.blocked = bool(blocked)


class _Mixin:
    def __init__(self, hotkey_text: str = "") -> None:
        self.igo_hotkey_entry = _Entry(hotkey_text)
        self.igo_tip_label = _Label()


class InGameOverlayHotkeyTipTests(unittest.TestCase):
    def test_the_tip_names_the_configured_hotkey(self) -> None:
        mixin = _Mixin()

        with patch.object(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f10"):
            refresh_in_game_overlay_hotkey_ui(mixin)

        self.assertIn("F10", mixin.igo_tip_label.text_value)
        self.assertNotIn("F9", mixin.igo_tip_label.text_value)
        self.assertEqual(mixin.igo_hotkey_entry.text(), "F10")

    def test_a_changed_hotkey_re_renders_the_tip(self) -> None:
        """The failure mode is a stale tip, not a missing one -- so drive it
        twice and check the old key is gone, which one call cannot show."""
        mixin = _Mixin()

        with patch.object(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9"):
            refresh_in_game_overlay_hotkey_ui(mixin)
        self.assertIn("F9", mixin.igo_tip_label.text_value)

        with patch.object(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f8"):
            refresh_in_game_overlay_hotkey_ui(mixin)

        self.assertIn("F8", mixin.igo_tip_label.text_value)
        self.assertNotIn("F9", mixin.igo_tip_label.text_value)

    def test_it_survives_a_tab_that_has_no_tip(self) -> None:
        """`InGameOverlay.build` is not the only caller: the Settings dialog
        calls this too, and it can run before the tab exists."""
        mixin = _Mixin()
        del mixin.igo_tip_label

        with patch.object(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9"):
            refresh_in_game_overlay_hotkey_ui(mixin)

        self.assertEqual(mixin.igo_hotkey_entry.text(), "F9")


if __name__ == "__main__":
    unittest.main()
