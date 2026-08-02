"""Losing the selection puts the library back in front of the user.

Switching to the tab with nothing loaded already opens the chooser -- the
router calls `ensure_recordings_chooser_for_empty_selection` on activation.
The same *state* is reachable without an activation, though: deleting the
selected recording, cleaning up short ones, or a load that fails all end with
no recording and a collapsed chooser, leaving a screen of "--" whose only
remedy is a button in the corner.

"--" itself is not what these cases are about. It is the right answer for one
missing value inside a populated view; it is the wrong answer for the whole
tab, where it says one thing forty times.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from tests.support.player_stats import build_recordings_tab, items_section_over


class _Scrubber:
    """The one widget on the clear path that is called, not just written."""

    def setEnabled(self, _enabled: bool) -> None:
        pass

    def set_pin(self, _pin) -> None:
        pass

    def set_model(self, _model) -> None:
        pass


class _StatCards:
    """Every `display_*` the clear path calls, and the cache it invalidates."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class ChooserReopensTests(unittest.TestCase):
    def _tab(self, *, active: bool = True):
        tab = build_recordings_tab(is_active=lambda: active)
        # `_clear_loaded_vod_selection` writes ~40 widgets; none exist on this
        # harness, and `_set_text` and friends tolerate `None` by design.
        tab.refresh_vods_list = lambda: None
        tab._scrubber = _Scrubber()
        tab._items_section = items_section_over(None)
        tab._stat_cards = _StatCards()
        tab._refresh_stage_cards = lambda: None
        tab._refresh_vod_compare_controls = lambda: None
        tab._refresh_vod_compare_details = lambda *a, **k: None
        tab._loaded_vod = SimpleNamespace(
            metadata=SimpleNamespace(path=Path("950k.jsonl"), name="950k"),
            snapshots=(),
        )
        tab._chooser_expanded = False
        return tab

    def test_clearing_the_selection_opens_the_library(self) -> None:
        tab = self._tab()

        tab._clear_loaded_vod_selection()

        self.assertTrue(tab._chooser_expanded)

    def test_it_does_not_open_the_library_on_an_inactive_tab(self) -> None:
        """A background tab must not rearrange itself behind the user."""
        tab = self._tab(active=False)

        tab._clear_loaded_vod_selection()

        self.assertFalse(tab._chooser_expanded)

    def test_deleting_the_selected_recording_opens_the_library(self) -> None:
        tab = self._tab()
        tab._window = lambda: None

        with patch(
            "ui.tabs.player_stats.recordings.ConfirmDeleteRecordingDialog"
        ) as dialog:
            dialog.return_value = SimpleNamespace(exec=lambda: None, result=True)
            with patch("ui.tabs.player_stats.recordings.delete_vod"):
                tab.delete_selected_vod()

        self.assertIsNone(tab._loaded_vod)
        self.assertTrue(tab._chooser_expanded)

    def test_an_already_open_library_is_left_alone(self) -> None:
        """Reopening would clear the guided flag and stop the auto-collapse."""
        tab = self._tab()
        # `remember=False` so the suite does not write the drawer's open state
        # into the real config.json on its way past.
        tab.set_recordings_chooser_expanded(True, guided=False, remember=False)

        tab._clear_loaded_vod_selection()

        self.assertTrue(tab._chooser_expanded)
        self.assertFalse(tab._guided_selection_active)


if __name__ == "__main__":
    unittest.main()
