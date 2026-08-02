"""The chat preview's height, which no layout is in a position to enforce.

The preview card is told to match the account card, and the two are in
different columns -- the rail is a sibling of the main column, not a row shared
with it. So the match runs through an event filter on a widget the preview has
no relationship to, which is exactly the kind of wiring that can stop working
with nothing raising. `test_twitch_component` cannot see it: it drives the panel
through fakes and never lays a widget out.

What is asserted is the *minimum* the mirror sets, never a rendered pixel
height. Rendered heights here are a report on the offscreen platform's font
substitutes, not on the layout: the same tab whose cards measure 244 and 244
with the shipped font measures 230 and 275 offscreen. An earlier version of the
caption-width check in this file was exactly that mistake, and it failed by
90px on a design that fits with room to spare.

Run in a subprocess, as `test_run_toggle` does: building the panel needs a real
`QApplication`, and one per process keeps these from depending on whatever ran
before.
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


class TwitchTabLayoutTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication, QFrame
            from ui.shared import resource_path
            from ui.styles import build_qt_app_stylesheet

            app = QApplication([])
            app.setStyleSheet(
                build_qt_app_stylesheet(
                    resource_path("media/checkmark.svg").replace("\\\\", "/")
                )
            )

            from ui.tabs.twitch import TwitchTab

            panel = TwitchTab()
            tab = panel.build()
            tab.setStyleSheet(app.styleSheet())

            def card_of(widget):
                node = widget
                while node is not None and not (
                    isinstance(node, QFrame) and node.property("settingsCard")
                ):
                    node = node.parentWidget()
                return node

            def lay_out(width, height):
                tab.resize(width, height)
                # `grab()`, and it is load-bearing: a widget that was never
                # shown does not run a real layout pass on resize alone, and
                # every card comes back the same stretched height. The first
                # version of these tests passed against that -- two cards
                # reading 480 are equal for a reason that has nothing to do
                # with the mirror.
                tab.grab()
                app.processEvents()
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
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_chat_preview_is_as_tall_as_the_account_card(self) -> None:
        """At both window sizes, not just the one it was tuned at.

        The mirror copies a height on every resize of the source, so asserting
        one size would pass against a hardcoded constant too.

        The *minimum* is what is asserted, not the rendered height. Those are
        the same number whenever the transcript is the shorter of the two, which
        is the normal case and the one on screen -- but font metrics decide
        which is shorter, and the offscreen platform's fonts are not the
        shipped ones. Asserting rendered equality would make this test a report
        on the test platform's font rather than on the mirror.
        """
        self._run(
            """
            preview = card_of(panel._chat_preview)
            for width, height in ((1320, 830), (1920, 1080)):
                lay_out(width, height)
                account = panel._account_card.height()
                assert account > 100, (width, account)
                assert preview.minimumHeight() == account, (
                    width, preview.minimumHeight(), account
                )
                assert preview.height() >= account, (width, preview.height(), account)
            """
        )

    def test_the_preview_never_shrinks_below_its_own_content(self) -> None:
        """A minimum, not a fixed height -- the difference matters when a
        template wraps onto more lines than the account form has rows.

        Forced here by making the transcript far taller than the account card
        could ever be; the card must follow the text rather than clip it.
        """
        self._run(
            """
            lay_out(1320, 830)
            preview = card_of(panel._chat_preview)
            account = panel._account_card.height()

            panel._chat_preview.setText("<br>".join(f"line {n}" for n in range(60)))
            app.processEvents()
            lay_out(1320, 830)

            assert preview.height() > account, (preview.height(), account)
            """
        )


if __name__ == "__main__":
    unittest.main()
