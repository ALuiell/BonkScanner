"""The two settings dialogs are constructed, opened and closed for real.

Written because deleting the tracked-item sections out of them left a call to a
handler that went with the sections, and nothing failed: the name is only
resolved when the dialog closes, pyflakes cannot see an attribute, and no test
opened either dialog. It surfaced by running the application.

So this is a smoke test and says so: it asserts that opening and dismissing each
dialog raises nothing. Anything about what is *in* them belongs elsewhere -- an
assertion on their contents here would make the file look like coverage it does
not provide.

`exec` is replaced rather than driven: these are modal, and a real `exec` in a
test blocks until something closes it. What is exercised is construction, the
teardown each dialog runs when it returns, and the handlers reachable from
both.
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


class SettingsDialogsOpenTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from unittest.mock import MagicMock, patch
            from PySide6.QtWidgets import QApplication, QDialog

            app = QApplication([])

            from app import config

            opened = []
            QDialog.exec = lambda self: (opened.append(self), 0)[1]
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
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_obs_widget_settings_dialog_opens_and_closes(self) -> None:
        self._run(
            """
            import gui_overlay
            from core.tracker.live_run import LiveRunTracker
            from infra.overlay_server import OverlayStateStore

            coordinator = MagicMock()
            coordinator.overlay_state_store = OverlayStateStore()
            coordinator.live_run_tracker = LiveRunTracker()
            coordinator.overlay_server = MagicMock()
            coordinator.overlay_server.is_running = False
            coordinator.overlay_server.last_error = ""
            coordinator.overlay_server.seconds_since_state_request = lambda: None

            overlay = gui_overlay.Overlay(
                coordinator,
                session_stats=MagicMock(),
                stats_tab=lambda: None,
                set_tracked_item_rows=lambda _rows: None,
                overlay_tab_active=lambda: True,
                server_rebuilt=lambda _server: None,
            )
            overlay.build()

            # The `finally` block is the half that broke: it ran a handler that
            # had been deleted with the section it belonged to.
            overlay.open_overlay_widget_settings_dialog()
            assert opened, "the dialog never reached exec"
            """
        )

    def test_the_twitch_command_settings_dialog_opens_and_closes(self) -> None:
        self._run(
            """
            from ui.dialogs import TwitchCommandSettingsDialog

            with patch.object(config, "save_config"):
                dialog = TwitchCommandSettingsDialog(None, MagicMock())
                dialog.exec()
            """
        )

    def test_the_tracked_items_window_opens_on_each_target(self) -> None:
        """One window, three lists -- so a switch is part of opening it."""
        self._run(
            """
            from app.tracked_item_settings import TrackedItemSettings, TARGETS
            from ui.dialogs.tracked_items import TrackedItemsDialog

            settings = TrackedItemSettings(
                tracker=lambda: None,
                combined_rules=lambda: (),
                refresh_session_rows=lambda: None,
                refresh_snapshot=lambda: None,
                save=lambda: None,
            )
            for target in TARGETS:
                dialog = TrackedItemsDialog(settings, target_key=target.key)
                assert dialog.target_key == target.key, target.key
                for other in TARGETS:
                    dialog._on_target(other.key)
                    assert dialog.target_key == other.key, (target.key, other.key)
            """
        )


if __name__ == "__main__":
    unittest.main()
