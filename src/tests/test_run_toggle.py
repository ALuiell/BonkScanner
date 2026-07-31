"""The three streaming tabs' Start/Stop segments, and the captions driving them.

None of the three owners says "running" out loud. `refresh_overlay_ui`,
`update_in_game_overlay_status_ui` and `show_bot_running` each write a caption,
and `RunToggle.setText` reads it back into a state. A caption that drifts on
either side leaves the control stuck on Start with nothing raising and every
test green -- the same hole `test_scanner_toggle` was written for.

The pairs live in `ui.run_toggle` and both sides import them, so there is one
literal per caption rather than two to keep in step. These cases drive each pair
through the widget and assert which segment came out live; if a pair is renamed,
this still passes -- what it stops is a *mismatch*, and the shared constant is
what stops the rename.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite


class RunToggleTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication, QPushButton
            from ui.run_toggle import (
                IN_GAME_OVERLAY_CAPTIONS,
                OVERLAY_SERVER_CAPTIONS,
                TWITCH_BOT_CAPTIONS,
                RunToggle,
            )
            from ui.styles import build_qt_app_stylesheet

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            def segments_of(toggle):
                found = {
                    button.property("segment"): button
                    for button in toggle.findChildren(QPushButton)
                }
                return found["start"], found["stop"]
            """
        ) + textwrap.dedent(body)
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_tabs_caption_pair_moves_the_live_segment(self) -> None:
        self._run(
            """
            pairs = {
                "overlay server": OVERLAY_SERVER_CAPTIONS,
                "twitch bot": TWITCH_BOT_CAPTIONS,
                "in-game overlay": IN_GAME_OVERLAY_CAPTIONS,
            }
            for name, (start_text, stop_text) in pairs.items():
                toggle = RunToggle(start_text, stop_text)
                start, stop = segments_of(toggle)

                # Built idle: Start is the action, Stop is the dim half.
                assert start.isEnabled() and not stop.isEnabled(), name
                assert start.property("active") == "true", name
                assert not toggle.is_running(), name

                toggle.setText(stop_text)
                assert stop.isEnabled() and not start.isEnabled(), name
                assert stop.property("active") == "true", name
                assert toggle.is_running(), name
                assert toggle.text() == stop_text, name

                toggle.setText(start_text)
                assert start.isEnabled() and not stop.isEnabled(), name
                assert not toggle.is_running(), name
            """
        )

    def test_the_three_pairs_are_distinct(self) -> None:
        """One shared `RunToggle` must not answer to another tab's caption.

        All three stop captions begin with "Stop", and an implementation that
        matched on that prefix rather than the whole caption would pass every
        case above while letting the Twitch bot's caption start the OBS server's
        toggle.
        """
        self._run(
            """
            toggle = RunToggle(*OVERLAY_SERVER_CAPTIONS)
            toggle.setText(TWITCH_BOT_CAPTIONS[1])
            assert not toggle.is_running()
            toggle.setText(IN_GAME_OVERLAY_CAPTIONS[1])
            assert not toggle.is_running()
            toggle.setText(OVERLAY_SERVER_CAPTIONS[1])
            assert toggle.is_running()
            """
        )

    def test_an_unknown_caption_reads_as_idle(self) -> None:
        """Not "keep whatever it was": an unrecognised caption means stopped.

        `refresh_overlay_ui` writes the start caption on a port error, and the
        Twitch panel routes arbitrary worker status strings through the same
        port. Holding the previous state on an unknown string would leave Stop
        lit after a failure.
        """
        self._run(
            """
            toggle = RunToggle(*OVERLAY_SERVER_CAPTIONS)
            toggle.setText(OVERLAY_SERVER_CAPTIONS[1])
            assert toggle.is_running()
            toggle.setText("Server is doing something else")
            assert not toggle.is_running()
            """
        )

    def test_only_the_live_segment_can_fire_the_toggle(self) -> None:
        self._run(
            """
            toggle = RunToggle(*TWITCH_BOT_CAPTIONS)
            start, stop = segments_of(toggle)
            fired = []
            toggle.toggle_requested.connect(lambda: fired.append(1))

            # Idle: the dim segment is disabled, so the click never lands.
            stop.click()
            assert fired == []

            start.click()
            assert fired == [1]

            toggle.setText(TWITCH_BOT_CAPTIONS[1])
            start.click()
            assert fired == [1]
            stop.click()
            assert fired == [1, 1]
            """
        )


if __name__ == "__main__":
    unittest.main()
