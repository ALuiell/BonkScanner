"""The header's pulsing status dot and its REC flag.

Both failure modes here are silent. A dot that stops pulsing still shows the
right colour, so nothing looks broken -- the app just stops saying it is doing
something. And a dot that pulses while hidden costs a repaint loop for the
whole session with nothing on screen to give it away; `RecordingFlag` builds
its dot in the `rec` state and then hides itself, which is exactly that case.
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


class StatusIndicatorTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QPixmap

            from ui.status_indicators import PremiumAccessBadge, PulsingDot, RecordingFlag
            from ui.styles import build_qt_app_stylesheet, _set_widget_style_role

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            def header_dot():
                dot = PulsingDot()
                dot.setObjectName("statusDot")
                dot.setProperty("state", "idle")
                dot.show()
                app.processEvents()
                return dot

            def pixel(widget, offset):
                "Colour `offset` px right of the dot's centre, on white."
                pixmap = QPixmap(widget.size())
                pixmap.fill()
                widget.render(pixmap)
                centre = widget.rect().center()
                return pixmap.toImage().pixelColor(
                    centre.x() + 1 + offset, centre.y() + 1
                ).name()
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

    def test_the_scanners_state_starts_and_stops_the_pulse(self) -> None:
        # `_set_widget_style_role` is the only channel the scanner has, so the
        # animation has to follow the property rather than a call of its own.
        self._run(
            """
            dot = header_dot()
            assert not dot.is_pulsing()

            _set_widget_style_role(dot, "statusDot", state="running")
            app.processEvents()
            assert dot.is_pulsing()

            _set_widget_style_role(dot, "statusDot", state="idle")
            app.processEvents()
            assert not dot.is_pulsing()
            assert dot.pulse == 0.0, dot.pulse
            """
        )

    def test_a_dot_that_is_not_on_screen_does_not_pulse(self) -> None:
        # The header sets `state` while it is still being built, before
        # anything is shown. A state-only condition would start a repaint loop
        # there and never stop it: `hideEvent` cannot fire for a widget that
        # was never shown.
        self._run(
            """
            dot = PulsingDot()
            dot.setObjectName("statusDot")
            dot.setProperty("state", "running")
            app.processEvents()
            assert not dot.is_pulsing(), "pulsing before ever being shown"

            dot.show()
            app.processEvents()
            assert dot.is_pulsing()

            dot.hide()
            app.processEvents()
            assert not dot.is_pulsing()
            """
        )

    def test_the_rec_flag_stays_on_the_line_and_lights_up(self) -> None:
        # It reports whether a recording is running, so it is always there --
        # an indicator that vanishes when the answer is no cannot be told apart
        # from one that is broken or missing.
        #
        # Green while recording, after `gui_overlay`'s `Live`, and the inverse
        # of a camera's REC lamp; grey when not, because red read as a fault
        # rather than as "no recording". The literal colours are asserted
        # because getting them backwards is the whole risk here, and every
        # reading of them looks deliberate on screen.
        self._run(
            """
            # Shown through a parent, never with `flag.show()` -- calling that
            # would un-hide a flag that hid itself and prove nothing about
            # whether it stays on the line. This is what the header does.
            from PySide6.QtWidgets import QHBoxLayout, QWidget
            host = QWidget()
            QHBoxLayout(host).addWidget(RecordingFlag())
            host.show()
            app.processEvents()

            flag = host.findChild(RecordingFlag)
            assert flag.isVisible(), "the flag hid itself when idle"
            assert not flag.is_recording()
            dot = flag.findChild(PulsingDot)
            assert not dot.is_pulsing(), "an idle flag must sit still"
            assert pixel(dot, 0) == "#5c6675", ("off should be grey", pixel(dot, 0))

            flag.set_recording(True)
            app.processEvents()
            assert flag.isVisible() and flag.is_recording()
            assert pixel(dot, 0) == "#22c55e", ("on should be green", pixel(dot, 0))
            assert dot.is_pulsing(), "a running recording should pulse"

            flag.set_recording(False)
            app.processEvents()
            assert flag.isVisible() and not flag.is_recording()
            assert pixel(dot, 0) == "#5c6675", pixel(dot, 0)
            assert not dot.is_pulsing()
            """
        )

    def test_premium_badge_follows_effective_supporter_access(self) -> None:
        self._run(
            """
            from types import SimpleNamespace
            from PySide6.QtWidgets import QHBoxLayout, QWidget

            host = QWidget()
            badge = PremiumAccessBadge(host)
            QHBoxLayout(host).addWidget(badge)
            host.show()
            app.processEvents()
            assert badge.isHidden()

            badge.set_access_state(SimpleNamespace(active=True, online=True))
            app.processEvents()
            assert badge.isVisible()
            assert badge.text() == "PREMIUM"
            assert badge.property("connection") == "online"
            assert "active" in badge.toolTip().lower()

            badge.set_access_state(SimpleNamespace(active=True, online=False))
            app.processEvents()
            assert badge.isVisible()
            assert badge.property("connection") == "cached"
            assert "recent check" in badge.toolTip().lower()

            badge.set_access_state(SimpleNamespace(active=False, online=True))
            app.processEvents()
            assert badge.isHidden()
            """
        )

    def test_header_brand_and_scanner_status_share_one_centre_line(self) -> None:
        self._run(
            """
            from types import SimpleNamespace
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
            import ui.layout as layout_module

            class AccessController:
                def __init__(self):
                    self.state = SimpleNamespace(active=False, online=False)
                    self.listener = None

                def add_listener(self, listener):
                    self.listener = listener

            opened = []
            shell = SimpleNamespace(
                supporter_access=AccessController(),
                open_settings_dialog=lambda **kwargs: opened.append(kwargs.get("page")),
            )
            host = QWidget()
            host.resize(820, 80)
            outer = QVBoxLayout(host)
            original_controls = layout_module._build_header_controls
            layout_module._build_header_controls = lambda _app, _layout: None
            try:
                layout_module._build_header(shell, outer)
            finally:
                layout_module._build_header_controls = original_controls

            host.show()
            app.processEvents()
            title = host.findChild(QLabel, "appTitle")
            status_pair = host.findChild(QWidget, "statusPair")
            assert title is not None and status_pair is not None
            assert status_pair.height() == 30
            assert status_pair.layout().spacing() == 3
            assert status_pair.layout().getContentsMargins() == (0, 4, 0, 0)
            assert shell.status_label.alignment() & Qt.AlignVCenter

            def centre_y(widget):
                top = widget.mapTo(host, QPoint(0, 0)).y()
                return top + widget.height() / 2

            brand_centres = [centre_y(shell.logo_label), centre_y(title)]
            status_centres = [centre_y(shell.status_dot), centre_y(shell.status_label)]
            assert max(brand_centres) - min(brand_centres) <= 1.0, brand_centres
            assert max(status_centres) - min(status_centres) <= 1.0, status_centres
            optical_offset = status_centres[0] - brand_centres[1]
            assert 1.5 <= optical_offset <= 2.5, optical_offset
            assert "QLabel#statusText" in app.styleSheet()
            assert "padding: 0px;" in app.styleSheet()

            shell.supporter_access.listener(
                SimpleNamespace(active=True, online=True)
            )
            app.processEvents()
            assert shell.premium_access_badge.isVisible()
            shell.premium_access_badge.click()
            assert opened == ["support"], opened
            """
        )

    def test_the_stylesheet_still_owns_the_colours(self) -> None:
        # The dot is painted rather than filled by QSS now, so the colours
        # could quietly stop coming from the stylesheet without anything else
        # changing. `qproperty-dotColor` is what keeps them there.
        self._run(
            """
            dot = header_dot()
            assert pixel(dot, 0) == "#5c6675", pixel(dot, 0)

            _set_widget_style_role(dot, "statusDot", state="running")
            app.processEvents()
            assert pixel(dot, 0) == "#22c55e", pixel(dot, 0)

            _set_widget_style_role(dot, "statusDot", state="idle")
            app.processEvents()
            assert pixel(dot, 0) == "#5c6675", pixel(dot, 0)
            """
        )

    def test_the_ring_is_drawn_outside_the_dot_while_pulsing(self) -> None:
        # Offscreen has no clock to wait on, so the animation is driven by
        # hand. What is asserted is that the ring reaches past the dot's own
        # 4px radius at all -- a pulse that paints nothing outside it is the
        # flat label this widget replaced.
        self._run(
            """
            dot = header_dot()
            _set_widget_style_role(dot, "statusDot", state="running")
            app.processEvents()

            painted = []
            for phase in (0.25, 0.5, 0.75):
                dot.pulse = phase
                app.processEvents()
                painted += [
                    offset for offset in (5, 6, 7)
                    if pixel(dot, offset) != "#ffffff"
                ]
            assert painted, "the ring never painted outside the dot"

            # ...and that it is gone once the state is not live any more.
            _set_widget_style_role(dot, "statusDot", state="idle")
            app.processEvents()
            assert all(pixel(dot, offset) == "#ffffff" for offset in (5, 6, 7))
            """
        )


if __name__ == "__main__":
    unittest.main()
