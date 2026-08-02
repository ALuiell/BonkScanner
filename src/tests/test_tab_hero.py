"""The shared tab header, and the two states its stylesheet cannot see.

`TabHero` carries the streaming tabs' status. Two things about it fail without
raising:

* `state` is a stylesheet property, and Qt does not re-evaluate property
  selectors on assignment. Miss the repolish and a stopped server keeps the
  green it was built with -- the badge says `STOPPED` in ok colours;
* error text does not fit the badge, so it goes to the subtitle instead. If a
  cleared error does not put the subtitle back, the hero keeps explaining a
  problem that is over.

The icon case is here for a different reason: the three SVGs come from a mock
that wrote `stroke="currentColor"`, which Qt does not resolve. A file that kept
it renders as nothing, and an empty 48px square is not obviously a bug.
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

from ui.shared import resource_path

HERO_ICONS = ("media/obs_icon.svg", "media/twitch_icon.svg", "media/in_game_icon.svg")


class HeroIconAssetTests(unittest.TestCase):
    """Qt-free: these are facts about the files, not about widgets."""

    def test_the_icons_exist(self) -> None:
        for relative in HERO_ICONS:
            with self.subTest(icon=relative):
                self.assertTrue(Path(resource_path(relative)).is_file())

    def test_no_icon_relies_on_current_colour(self) -> None:
        """`currentColor` is a CSS idea. Qt's SVG renderer draws nothing for it.

        The mock's paths used it throughout; each file must name the stroke.
        """
        for relative in HERO_ICONS:
            with self.subTest(icon=relative):
                markup = Path(resource_path(relative)).read_text(encoding="utf-8")
                self.assertNotIn("currentColor", markup)
                self.assertIn("#38BDF8", markup)


class TabHeroTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication
            from ui.run_toggle import OVERLAY_SERVER_CAPTIONS
            from ui.styles import build_qt_app_stylesheet
            from ui.tab_hero import (
                STATE_DANGER,
                STATE_OFF,
                STATE_OK,
                STATE_WARN,
                TabHero,
            )

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            def build():
                return TabHero(
                    title="OBS Overlay",
                    subtitle="Send live run data to OBS through a local browser source.",
                    icon_path="media/obs_icon.svg",
                    auto_text="Auto-start server",
                    run_captions=OVERLAY_SERVER_CAPTIONS,
                )
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

    def test_the_badge_state_property_follows_the_status(self) -> None:
        self._run(
            """
            hero = build()
            assert hero.status_state() == STATE_OFF

            hero.set_status("LIVE", STATE_OK)
            assert hero.status_text() == "LIVE"
            assert hero.status_state() == STATE_OK

            hero.set_status("CONNECTING", STATE_WARN)
            assert hero.status_state() == STATE_WARN

            hero.set_status("STOPPED", STATE_OFF)
            assert hero.status_state() == STATE_OFF
            """
        )

    def test_the_badge_actually_repaints_between_states(self) -> None:
        """The property assertion above passes with the repolish deleted.

        Qt does not re-evaluate property selectors when the property is set, so
        a badge can hold `state="off"` and keep painting the green it was built
        with -- `STOPPED` in ok colours, which nothing in a state assertion can
        see. Comparing what the widget actually renders is the only check that
        fails when the repolish goes.
        """
        self._run(
            """
            hero = build()
            badge = hero.findChild(type(hero._title), "heroBadge")

            hero.set_status("LIVE", STATE_OK)
            live = badge.grab().toImage()
            hero.set_status("LIVE", STATE_DANGER)
            failed = badge.grab().toImage()

            # Same caption, same geometry, different colours -- so any
            # difference at all is the stylesheet having been re-matched.
            assert live != failed, "the badge painted identically in ok and danger"
            """
        )

    def test_error_detail_takes_over_the_subtitle_and_gives_it_back(self) -> None:
        self._run(
            """
            hero = build()
            resting = "Send live run data to OBS through a local browser source."
            subtitle = hero.findChild(type(hero._subtitle), "heroSubtitle")
            assert subtitle.text() == resting

            hero.set_status(
                "PORT ERROR",
                STATE_DANGER,
                detail="[WinError 10048] Address already in use",
            )
            assert subtitle.text() == "[WinError 10048] Address already in use"
            # The badge itself stays a short label -- that is the whole point of
            # moving the sentence out of it.
            assert hero.status_text() == "PORT ERROR"

            hero.set_status("LIVE", STATE_OK)
            assert subtitle.text() == resting
            """
        )

    def test_the_icon_actually_rendered(self) -> None:
        """An unresolved stroke colour would leave the holder empty, not crash."""
        self._run(
            """
            hero = build()
            holder = hero.findChild(type(hero._title), "heroIcon")
            pixmap = holder.pixmap()
            assert pixmap is not None and not pixmap.isNull(), "hero icon did not render"
            assert holder.text() == "", "hero fell back to the missing-asset marker"
            """
        )

    def test_the_run_toggle_and_auto_switch_are_reachable(self) -> None:
        """The tab wires both; a renamed accessor would break it at build time."""
        self._run(
            """
            hero = build()
            assert not hero.run_toggle.is_running()
            hero.run_toggle.setText(OVERLAY_SERVER_CAPTIONS[1])
            assert hero.run_toggle.is_running()

            assert not hero.auto_switch.isChecked()
            hero.auto_switch.setChecked(True)
            assert hero.auto_switch.isChecked()
            """
        )


if __name__ == "__main__":
    unittest.main()
