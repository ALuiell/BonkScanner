"""The header's scanner button: the width pin and the scoped QSS role.

Two things hold this button together, and both fail quietly.

`_pin_width_across_captions` measures the two captions `update_status_ui`
writes and holds the button at the wider one. If the measurement ever runs
before the stylesheet is applied -- or if a third caption appears -- the pin
comes out too small and the button starts shoving the status dot sideways on
every start, with nothing raising.

The QSS metrics are scoped by the `headerAction` property rather than the
objectName, because `update_status_ui` owns that name and swaps it between
`primary` and `stopScanner`. If the property selector stops matching, the
button silently falls back to the shared roles, which disagree by 4px in
height -- the disagreement the pin does not cover.
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


class HeaderScannerActionTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication, QPushButton
            from ui.layout import SCANNER_TOGGLE_CAPTIONS, _pin_width_across_captions
            from ui.styles import build_qt_app_stylesheet, _set_widget_style_role

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            def header_button():
                button = QPushButton("Start Scanner")
                button.setObjectName("primary")
                button.setProperty("headerAction", "true")
                _pin_width_across_captions(button, SCANNER_TOGGLE_CAPTIONS)
                return button

            def width(button):
                return max(button.sizeHint().width(), button.minimumWidth())
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

    def test_the_button_holds_one_size_across_the_role_swap(self) -> None:
        self._run(
            """
            button = header_button()
            idle = (width(button), button.sizeHint().height())

            # Exactly what `update_status_ui` does, in that order.
            _set_widget_style_role(button, "stopScanner")
            button.setText("Stop Scanner")
            button.ensurePolished()
            running = (width(button), button.sizeHint().height())

            assert idle == running, (idle, running)

            # And back, because the scanner stops as often as it starts.
            _set_widget_style_role(button, "primary")
            button.setText("Start Scanner")
            button.ensurePolished()
            assert (width(button), button.sizeHint().height()) == idle
            """
        )

    def test_the_pin_covers_the_wider_caption_not_the_built_one(self) -> None:
        # `Start Scanner` is the wider of the two today. The pin must not be
        # reading whichever caption the button happened to be built with.
        self._run(
            """
            button = header_button()
            pinned = button.minimumWidth()

            for caption in SCANNER_TOGGLE_CAPTIONS:
                probe = QPushButton(caption)
                probe.setObjectName("primary")
                probe.setProperty("headerAction", "true")
                probe.ensurePolished()
                assert probe.sizeHint().width() <= pinned, (caption, pinned)

            assert any(
                QPushButton(caption) is not None for caption in SCANNER_TOGGLE_CAPTIONS
            )
            assert pinned > 0
            """
        )

    def test_the_header_metrics_do_not_leak_into_the_shared_roles(self) -> None:
        # `primary` and `stopScanner` are worn by the overlay server, the
        # Twitch bot and the in-game overlay buttons too. The header's flatter
        # padding must stay behind the `headerAction` property.
        self._run(
            """
            plain = QPushButton("Start Server")
            plain.setObjectName("primary")
            plain.ensurePolished()

            scoped = header_button()

            assert plain.sizeHint().height() != scoped.sizeHint().height(), (
                plain.sizeHint(), scoped.sizeHint()
            )
            """
        )


if __name__ == "__main__":
    unittest.main()
