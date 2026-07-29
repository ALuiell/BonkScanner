"""What the circles on the timeline are, said in words on hover.

The marker strip bins events to a glyph's own width on purpose: ~190 markers
drawn one-per-event across an 800 px track merge into a solid bar that says
only "items happened". Binning keeps the distribution legible and moves the
identity of an event to the tooltip -- which is what these cases pin.

Run in a **subprocess**, like `test_scanner_toggle.py` and
`test_recordings_layout.py`. Constructing a custom-painted widget inside the
suite's own process takes the interpreter down with an access violation -- no
traceback, no failing test, just a dead run somewhere after this file. The
tooltip needs real widget geometry, so there is no in-process version of it.
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


class MarkerTooltipTests(unittest.TestCase):
    def test_the_marker_strip_names_the_events_under_the_pointer(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QApplication

            from projections.scrubber import Marker, ScrubberModel
            from ui.tabs.player_stats.recording_scrubber import (
                _MARKER_STRIP_HEIGHT,
                _MARKER_TOOLTIP_MAX_LINES,
                RecordingScrubber,
            )

            app = QApplication([])
            widget = RecordingScrubber()
            widget.resize(800, 150)

            def load(markers, count=100):
                widget.set_model(ScrubberModel(count=count, markers=tuple(markers)))

            def strip_y():
                return int(widget._track_rect().bottom() - _MARKER_STRIP_HEIGHT / 2)

            def tip(index, y=None):
                x = int(widget._x_of(index))
                return widget._marker_tooltip_at(QPoint(x, strip_y() if y is None else y))

            def marker(index, kind, text):
                colour = {"legendary": "#FACC15", "rare": "#60A5FA"}.get(kind, "#F0787E")
                return Marker(index=index, kind=kind, color=colour, text=text)

            # Nothing loaded: the strip has nothing to say.
            assert widget._marker_tooltip_at(QPoint(400, strip_y())) == ""

            # One marker names its event.
            load([marker(40, "legendary", "Rocket Launcher +1")])
            assert tip(40) == "Rocket Launcher +1", tip(40)

            # Above the strip is not a marker hover: the widget's own keyboard
            # help has to win everywhere the markers are not.
            assert tip(40, y=40) == "", tip(40, y=40)

            # The glyph shows the highest-ranked event in its bin; the tooltip
            # owes all of them, which is the whole reason it exists.
            load([
                marker(40, "rare", "Boots +1"),
                marker(40, "legendary", "Crown +1"),
                marker(40, "banish", "Banish: Rock"),
            ])
            assert tip(40).splitlines() == ["Boots +1", "Crown +1", "Banish: Rock"], tip(40)

            # A bin far from the pointer is a different bin.
            load([marker(10, "rare", "Near +1"), marker(90, "rare", "Far +1")])
            assert tip(10) == "Near +1", tip(10)
            assert tip(70) == "", tip(70)

            # A crowded bin stops listing and starts counting: a tooltip taller
            # than the widget it describes is worse than a summary.
            load([
                marker(40, "rare", f"Item {n} +1")
                for n in range(_MARKER_TOOLTIP_MAX_LINES + 4)
            ])
            lines = tip(40).splitlines()
            assert len(lines) == _MARKER_TOOLTIP_MAX_LINES + 1, lines
            assert lines[-1] == "+4 more", lines
            """
        )
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


if __name__ == "__main__":
    unittest.main()
