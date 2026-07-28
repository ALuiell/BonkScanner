"""The header's Start/Stop segments, and the caption channel that drives them.

`gui_scanner.update_status_ui` never says "running" out loud -- it writes a
caption onto whatever the `toggle_btn` port hands it. `ScannerToggle.setText`
reads that caption back into a state, which means a typo on either side would
leave the control stuck on Start with nothing raising and every test green.
The first case below is what stops that: it drives the widget through the two
literal strings `update_status_ui` writes, taken from `ScannerToggle` itself,
and asserts which segment came out live.
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


class ScannerToggleTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication, QPushButton
            from ui.scanner_toggle import ScannerToggle

            app = QApplication([])
            toggle = ScannerToggle()
            segments = {
                button.property("segment"): button
                for button in toggle.findChildren(QPushButton)
            }
            start, stop = segments["start"], segments["stop"]
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
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_scanners_captions_move_the_live_segment(self) -> None:
        self._run(
            """
            # Built idle: Start is the action, Stop is the dim half.
            assert start.isEnabled() and not stop.isEnabled()
            assert start.property("active") == "true"
            assert stop.property("active") == "false"
            assert not toggle.is_running()

            # The exact string `update_status_ui` writes while scanning.
            toggle.setText(ScannerToggle.STOP_TEXT)
            assert stop.isEnabled() and not start.isEnabled()
            assert stop.property("active") == "true"
            assert start.property("active") == "false"
            assert toggle.is_running()
            assert toggle.text() == "Stop Scanner"

            # ...and the one it writes when it stops.
            toggle.setText(ScannerToggle.START_TEXT)
            assert start.isEnabled() and not stop.isEnabled()
            assert not toggle.is_running()

            # Anything else is not the running caption, so it reads as idle
            # rather than silently keeping the previous state.
            toggle.setText(ScannerToggle.STOP_TEXT)
            toggle.setText("Scanner is doing something else")
            assert not toggle.is_running()
            """
        )

    def test_only_the_live_segment_can_fire_the_toggle(self) -> None:
        self._run(
            """
            fired = []
            toggle.toggle_requested.connect(lambda: fired.append(1))

            # Idle: pressing Stop must not ask the scanner to do anything --
            # the dim segment is disabled, so the click never lands.
            stop.click()
            assert fired == []
            start.click()
            assert len(fired) == 1

            toggle.setText(ScannerToggle.STOP_TEXT)
            start.click()
            assert len(fired) == 1
            stop.click()
            assert len(fired) == 2
            """
        )

    def test_the_control_is_one_width_in_both_states(self) -> None:
        # The whole reason the segments replaced a caption-swapping button:
        # `_build_header_controls` had to pin minimum sizes over a control that
        # measured 199x34 in one state and 194x37 in the other.
        self._run(
            """
            toggle.show()
            app.processEvents()
            idle_size = toggle.sizeHint()

            toggle.setText(ScannerToggle.STOP_TEXT)
            app.processEvents()
            running_size = toggle.sizeHint()

            assert idle_size == running_size, (idle_size, running_size)
            """
        )


if __name__ == "__main__":
    unittest.main()
