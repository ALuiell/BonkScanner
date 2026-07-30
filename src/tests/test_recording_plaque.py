"""The record plaque: the heading, and the rename it opens on demand.

The header used to be a status line above an always-editable name field with
`Rename` and `Delete` beside it -- three permanent controls for the two things
you do least often, with the destructive one adjacent to the field you type in.
The name is a heading now and the field only exists mid-rename, which turns
"is the field showing?" into state worth pinning: a rename left open across a
recording change would commit the old name onto the new run.

Widgets here are bare `QLabel`/`QLineEdit`/`QPushButton` assigned onto a real
`RecordingsTab`, deliberately not `build()`. Building the whole tab inside the
suite's process is what `test_recordings_layout.py` runs in a **subprocess**
for; the plaque's *layout* is asserted over there.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from ui.tabs.player_stats import recordings as recordings_module
from ui.tabs.player_stats.recordings import _NameEdit
from tests.support.player_stats import build_recordings_tab


def _vod(name: str = "950k"):
    return SimpleNamespace(
        metadata=SimpleNamespace(path=Path("950k.jsonl"), name=name),
        snapshots=(),
    )


class PlaqueRenameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tab = build_recordings_tab()
        # Parented to a host that is never shown, and asserted with
        # `isVisibleTo`: `isVisible` is False for every widget here regardless
        # of the hidden flag, which is the flag these cases are about.
        self.host = QWidget()
        self.tab._title_label = QLabel("No recording selected", self.host)
        self.tab._status_label = QLabel("Select a recording", self.host)
        self.tab._name_entry = _NameEdit(self.host)
        self.tab._name_entry.setVisible(False)
        self.tab._rename_btn = QPushButton("edit", self.host)
        self.tab._delete_btn = QPushButton("delete", self.host)
        self.tab._loaded_vod = _vod()

    def _editing(self) -> bool:
        return self.tab._name_entry.isVisibleTo(self.host)

    def _showing_heading(self) -> bool:
        return self.tab._title_label.isVisibleTo(self.host)

    def test_the_field_is_hidden_until_a_rename_starts(self) -> None:
        self.assertFalse(self._editing())
        self.assertTrue(self._showing_heading())

    def test_beginning_a_rename_swaps_the_heading_for_the_field(self) -> None:
        self.tab.begin_rename()

        self.assertTrue(self._editing())
        self.assertFalse(self._showing_heading())
        self.assertFalse(self.tab._rename_btn.isVisibleTo(self.host))
        self.assertFalse(self.tab._delete_btn.isVisibleTo(self.host))

    def test_the_field_is_prefilled_with_the_current_name(self) -> None:
        self.tab.begin_rename()

        self.assertEqual(self.tab._name_entry.text(), "950k")

    def test_cancelling_restores_the_heading_and_keeps_the_name(self) -> None:
        self.tab.begin_rename()
        self.tab._name_entry.setText("typed something else")

        self.tab.cancel_rename()

        self.assertFalse(self._editing())
        self.assertTrue(self._showing_heading())
        self.assertEqual(self.tab._title_label.text(), "No recording selected")

    def test_a_rename_with_no_recording_loaded_does_nothing(self) -> None:
        self.tab._loaded_vod = None

        self.tab.begin_rename()

        self.assertFalse(self._editing())

    def test_committing_closes_the_field(self) -> None:
        self.tab.begin_rename()
        self.tab._name_entry.setText("970k")
        renamed = SimpleNamespace(path=Path("970k.jsonl"), name="970k")
        self.tab.refresh_loaded_vod_ui = lambda **_kwargs: None
        self.tab.refresh_vods_list = lambda: None

        with patch.object(recordings_module, "rename_vod", return_value=renamed):
            with patch.object(recordings_module, "load_vod", return_value=_vod("970k")):
                self.tab.rename_selected_vod()

        self.assertFalse(self._editing())

    def test_a_failed_rename_leaves_the_field_open_with_what_was_typed(self) -> None:
        """Closing it would discard the user's text to show them the old name."""
        self.tab.begin_rename()
        self.tab._name_entry.setText("970k")

        with patch.object(
            recordings_module, "rename_vod", side_effect=OSError("in use")
        ):
            self.tab.rename_selected_vod()

        self.assertTrue(self._editing())
        self.assertEqual(self.tab._name_entry.text(), "970k")
        self.assertIn("Could not rename", self.tab._status_label.text())

    def test_losing_the_recording_abandons_an_open_rename(self) -> None:
        """Otherwise the next commit writes this name onto a different run."""
        self.tab.begin_rename()

        self.tab._loaded_vod = None
        self.tab._set_vod_loading_state(True)

        self.assertFalse(self._editing())
        self.assertTrue(self._showing_heading())


# `_NameEdit`'s Escape handling is asserted in `test_recordings_layout.py`'s
# subprocess, not here. Delivering the key needs a real `QKeyEvent`, and
# building one at this point in a full run takes the interpreter down with a
# libshiboken fatal error: the binding raises on the argument and then dies
# formatting the complaint, because `unittest.mock` is patched over something
# shiboken reads to do it. A clean interpreter has no such problem.


if __name__ == "__main__":
    unittest.main()
