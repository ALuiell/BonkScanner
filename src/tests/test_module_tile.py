"""The module grids' tile, and the two things that make it not a checkbox.

`ModuleTile` replaces sixteen Twitch command checkboxes, six OBS widget
checkboxes and seven in-game ones. Two properties carry that, and both fail
quietly if they break:

* the whole tile is the click target, with the switch inside transparent to the
  mouse. Get that wrong and one press toggles twice, landing back where it
  started -- which looks like a dead control, not like a double toggle;
* `on` is a stylesheet property, and Qt does not re-evaluate property selectors
  on assignment. Without the repolish the tile keeps its built colours, so
  every tile in the grid looks off no matter what the config says.

Neither shows up in a state assertion, so both are asserted directly.
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


class ModuleTileTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtWidgets import QApplication
            from ui.module_tile import ModuleTile
            from ui.styles import build_qt_app_stylesheet

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            def press(widget, position=None):
                point = QPointF(position or QPoint(4, 4))
                event = QMouseEvent(
                    QEvent.MouseButtonPress,
                    point,
                    Qt.LeftButton,
                    Qt.LeftButton,
                    Qt.NoModifier,
                )
                QApplication.sendEvent(widget, event)
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

    def test_a_press_toggles_exactly_once(self) -> None:
        """The double-toggle guard: one press, one change, state actually flips."""
        self._run(
            """
            tile = ModuleTile("!weapons")
            tile.resize(220, 34)
            changes = []
            tile.toggled.connect(changes.append)

            assert not tile.isChecked()
            press(tile)
            assert tile.isChecked(), "one press did not enable the tile"
            assert changes == [True], changes

            press(tile)
            assert not tile.isChecked()
            assert changes == [True, False], changes
            """
        )

    def test_the_switch_does_not_take_the_mouse(self) -> None:
        """Without this the inner switch fires too and the tile lands back.

        Asserted on the attribute rather than by clicking through it: an event
        sent straight to a transparent-for-mouse child is still delivered by
        `sendEvent`, so a click-based check would pass with the attribute gone.
        """
        self._run(
            """
            tile = ModuleTile("Stage summary")
            assert tile.switch().testAttribute(Qt.WA_TransparentForMouseEvents)
            """
        )

    def test_the_on_property_follows_the_state(self) -> None:
        """What the stylesheet reads. A stale value is an untinted tile."""
        self._run(
            """
            tile = ModuleTile("KPS")
            assert tile.property("on") == "false"

            tile.setChecked(True)
            assert tile.property("on") == "true"

            tile.setChecked(False)
            assert tile.property("on") == "false"
            """
        )

    def test_the_tile_actually_repaints_when_enabled(self) -> None:
        """The property assertion above passes with the repolish deleted.

        And the tint *is* the feature: it is the whole reason sixteen tiles
        read better than sixteen ticks. A tile that holds `on="true"` while
        still painting the off background is the failure this catches, and no
        state assertion can see it.
        """
        self._run(
            """
            tile = ModuleTile("!stats")
            tile.resize(220, 34)

            # A whole-image comparison is *not* enough and was tried first: the
            # switch inside repaints its own track on every toggle, so the two
            # grabs differ even with the tile's repolish deleted. Sample a point
            # in the frame's own background instead -- x=5 is inside the border
            # and left of the 10px content margin, so nothing but the tile
            # paints there.
            probe_x, probe_y = 5, 17

            off = tile.grab().toImage().pixelColor(probe_x, probe_y)
            tile.setChecked(True)
            on = tile.grab().toImage().pixelColor(probe_x, probe_y)

            assert off != on, (
                "the tile background painted identically enabled and disabled: "
                f"{off.name()} both times"
            )
            """
        )

    def test_it_answers_the_checkbox_vocabulary(self) -> None:
        """The three grids' handlers speak `stateChanged` / `isChecked`.

        `read_settings` asks every Twitch command `cb.isChecked()`, and both
        overlays connect `stateChanged` to a save. If the forwarding breaks, the
        tabs stop saving with nothing raising.
        """
        self._run(
            """
            tile = ModuleTile("Tracked items")
            seen = []
            tile.stateChanged.connect(seen.append)

            tile.setChecked(True)
            assert tile.isChecked()
            assert seen and seen[-1] == Qt.Checked.value, seen

            tile.setChecked(False)
            assert not tile.isChecked()
            assert seen[-1] == Qt.Unchecked.value, seen

            assert tile.text() == "Tracked items"
            """
        )


if __name__ == "__main__":
    unittest.main()
