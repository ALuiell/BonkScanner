"""A control that goes away under the press must not arm the field beside it.

Three of them did, and they are three shapes of one Qt behaviour: the focus is
not left on a widget that has just been disabled or hidden, it is handed to the
next one in the tab order. These tabs are columns of cards where a button is
followed by a field, so the next one is a `QLineEdit` -- which selects its
contents on focus-in. Pressing a button therefore opened an unrelated field for
editing.

* **Copy**, on the OBS tab, disabled itself while it said "Copied!" and put a
  caret in the Port field. Nothing needed it off, so it is not turned off.
* **Start Overlay**, on the In-Game Overlay tab, is a `SegmentedToggle` segment,
  and the segment that stops being live *is* disabled -- so pressing Start armed
  the layout-hotkey field. That fix is the class-level one: it lands in
  `set_active`, so every toggle built on it gets it.
* **Connect** and **Disconnect**, on the Twitch tab -- one disabled, one hidden,
  both landing in the username field. `release_focus` is what they use.

None of it is visible to a test that drives a panel through fakes: the tab order
only exists once the widgets are laid out in a real window. So each case builds
the actual application in a subprocess, as `test_startup_window_order` does, and
drives the real control.

The assertion is always about the *field*, not about which widget won the focus.
Where the focus ends up is a judgement call that differs per case -- the toggle
carries it to the incoming segment, Connect drops it entirely -- but no case may
end with a text field focused or its contents selected.
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


PREAMBLE = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import src
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QLineEdit, QPushButton, QTabWidget,
)
from app import config
from gui_app import MegabonkApp

config.save_config = lambda *_args, **_kwargs: None
app = MegabonkApp()
qt = QApplication.instance()
app.window.show()
# There is no focus at all inside a window that is not active, and nothing
# activates this one for us: under `offscreen` never, and on the real platform
# only sometimes, which is what made three of these four flaky -- every claim
# below read `focusWidget() is None`. Asserted rather than assumed, because
# `None` is not a `QLineEdit` either: a window that silently stopped activating
# would leave `assert_no_field_armed` passing without checking anything.
app.window.activateWindow()
qt.processEvents()
assert qt.activeWindow() is app.window, qt.activeWindow()

tabs = [
    widget
    for widget in app.window.findChildren(QTabWidget)
    if widget.objectName() == "mainTabs"
][0]


def open_tab(caption):
    # The focus chain is per-page: a control on a page the tab widget is not
    # showing has the navigation rail after it rather than its own neighbour,
    # which is not the order the user is in.
    for index in range(tabs.count()):
        if tabs.tabText(index) == caption:
            tabs.setCurrentIndex(index)
            qt.processEvents()
            return tabs.widget(index)
    raise AssertionError("no tab called " + caption)


def settle(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def assert_no_field_armed(where):
    focused = qt.focusWidget()
    assert not isinstance(focused, (QLineEdit, QAbstractSpinBox)), (
        where, focused, getattr(focused, "objectName", lambda: "")()
    )
    for field in app.window.findChildren(QLineEdit):
        assert not field.hasSelectedText(), (where, field.selectedText())
"""

EPILOGUE = """
app.on_closing()
qt.processEvents()
"""


class FocusAfterPressTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = (
            textwrap.dedent(PREAMBLE)
            + textwrap.dedent(body)
            + textwrap.dedent(EPILOGUE)
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    # -- OBS: Copy ------------------------------------------------------------

    def test_copying_the_obs_url_leaves_the_port_field_alone(self) -> None:
        """The focus is asserted to stay on Copy, which is the stronger claim.

        "Not the port" alone would pass if it went to the widget after the port,
        which would be just as wrong. Copy is where the press was.
        """
        self._run(
            """
            open_tab("OBS Overlay")
            overlay = app._overlay
            copy_button = [
                button
                for button in overlay.tab_overlay.findChildren(QPushButton)
                if button.text() == "Copy"
            ][0]

            copy_button.setFocus()
            qt.processEvents()
            copy_button.click()
            qt.processEvents()

            assert QGuiApplication.clipboard().text() == overlay.overlay_url_entry.text()
            assert_no_field_armed("obs copy")
            assert qt.focusWidget() is copy_button, qt.focusWidget()
            assert copy_button.isEnabled()
            """
        )

    def test_the_copy_caption_and_role_come_back_after_the_feedback(self) -> None:
        """Including after a second press inside the feedback window.

        The button stays enabled now, so a second press is possible where it was
        not before. It must not stack: a second restore would capture "Copied!"
        as the caption to put back, and the button would say it forever.

        The role is asserted empty rather than "not SuccessButton" because an
        empty object name is what leaves the button to the stylesheet. The old
        restore wrote an inline padding rule instead, and the button stayed out
        of the stylesheet for the rest of the session.
        """
        self._run(
            """
            open_tab("OBS Overlay")
            overlay = app._overlay
            copy_button = [
                button
                for button in overlay.tab_overlay.findChildren(QPushButton)
                if button.text() == "Copy"
            ][0]
            assert copy_button.objectName() == ""

            copy_button.click()
            qt.processEvents()
            assert copy_button.text() == "Copied!"
            assert copy_button.objectName() == "SuccessButton"

            settle(300)
            copy_button.click()
            qt.processEvents()
            assert copy_button.text() == "Copied!"

            settle(2000)
            assert copy_button.text() == "Copy", copy_button.text()
            assert copy_button.objectName() == "", copy_button.objectName()
            assert copy_button.styleSheet() == "", copy_button.styleSheet()
            """
        )

    # -- In-Game Overlay: the run toggle --------------------------------------

    def test_the_overlay_toggle_does_not_arm_the_hotkey_field(self) -> None:
        """Driven through `setText`, which is the toggle's whole state channel.

        Clicking the segment would start the real overlay; the state change the
        owner makes in response is `setText("Stop Overlay")`, and that is what
        disables the segment under the press. Both directions are exercised --
        Start going dark and Stop going dark -- because the hotkey field is
        after the toggle either way.
        """
        self._run(
            """
            open_tab("In-Game Overlay")
            toggle = app._in_game_overlay.igo_toggle_btn
            hotkey = app._in_game_overlay.igo_hotkey_entry
            assert hotkey is not None

            for pressed, caption in (
                ("start", "Stop Overlay"),
                ("stop", "Start Overlay"),
            ):
                toggle.set_active(pressed)
                qt.processEvents()
                segment = toggle.segment(pressed)
                segment.setFocus()
                qt.processEvents()
                assert qt.focusWidget() is segment, (pressed, qt.focusWidget())

                toggle.setText(caption)
                qt.processEvents()

                assert_no_field_armed("igo toggle " + pressed)
                assert not hotkey.hasFocus()
                # The focus went to the segment taking over, not nowhere: this
                # toggle has somewhere better to put it than the window root.
                assert qt.focusWidget() is toggle.segment(toggle.active_key()), (
                    pressed, qt.focusWidget()
                )
            """
        )

    # -- Twitch: connect and disconnect ---------------------------------------

    def test_connecting_and_disconnecting_leave_the_username_alone(self) -> None:
        """One disables its button, the other hides it; both used to land here.

        Asserted through the panel's own state methods rather than a click,
        because a click would start a real authorization against Twitch. Those
        methods are what the click reaches, and they are where the disable and
        the hide live.
        """
        self._run(
            """
            open_tab("Twitch Bot")
            panel = app._twitch_tab
            assert panel is not None

            panel.show_disconnected()
            qt.processEvents()
            panel._connect_btn.setFocus()
            qt.processEvents()
            assert qt.focusWidget() is panel._connect_btn
            panel.show_authorizing()
            qt.processEvents()
            assert not panel._connect_btn.isEnabled()
            assert_no_field_armed("twitch connect")

            panel._connect_btn.setEnabled(True)
            panel._connect_btn.setVisible(False)
            panel._disconnect_btn.setVisible(True)
            qt.processEvents()
            panel._disconnect_btn.setFocus()
            qt.processEvents()
            assert qt.focusWidget() is panel._disconnect_btn
            panel.show_disconnected()
            qt.processEvents()
            assert not panel._disconnect_btn.isVisible()
            assert_no_field_armed("twitch disconnect")
            """
        )


if __name__ == "__main__":
    unittest.main()
