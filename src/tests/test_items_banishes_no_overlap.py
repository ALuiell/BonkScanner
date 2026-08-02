"""The item chips must not draw over Banishes on a short window.

The list had a `setMinimumHeight(220)` floor, added so that Banishes -- whose
flow layout pushes a `minimumHeight` onto its container for every row it wraps
-- could not squeeze the list out. A floor cannot yield, and a `QVBoxLayout`
that cannot compress a child still *positions* the ones after it as if it had:
on a 1280x800 window the divider and the whole Banishes section landed inside
the scroll's rect, and the chips painted over them.

So this asserts geometry, at the size that produced it, rather than the
attributes that were supposed to imply it: the scroll ends above the divider,
which ends above Banishes, and Banishes ends inside the card.
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


class ItemsBanishesOverlapTests(unittest.TestCase):
    def test_the_item_list_never_overlaps_banishes_below_it(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import (
                QApplication,
                QFrame,
                QGroupBox,
                QScrollArea,
                QTabWidget,
                QWidget,
            )
            from app import config
            from ui.styles import build_qt_app_stylesheet
            from ui.tabs.player_stats.items_section import update_banishes_section
            from ui.tabs.player_stats.recordings import RecordingsTab

            config.save_config = lambda _payload: None

            class Library:
                index = ()
                def ensure_refresh(self):
                    pass

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))
            tabview = QTabWidget()
            view = RecordingsTab(
                tabview=tabview,
                vod_library=Library(),
                window=lambda: None,
                vod_recorder=lambda: None,
                is_active=lambda: True,
                log=lambda *_args, **_kwargs: None,
            )
            view.build()
            # The tab's contents wait for a show; this test drives the
            # widgets without one, so it asks for them. See `LazyPage`.
            view.build_now()

            # A long run and a long banish list: both flows wrap several rows,
            # which is what grew the minimums that collided.
            items = tuple(
                f"{name} x{count}"
                for name, count in (
                    ("Coward's cloak", 1), ("Skuleg", 2), ("Backpack", 2),
                    ("Anvil", 1), ("Time Bracelet", 7), ("Power Gloves", 8),
                    ("Beefy Ring", 16), ("Echo Shard", 5), ("Wrench", 2),
                    ("Za Warudo", 1), ("Key", 7), ("Credit Card (Green)", 1),
                    ("Scarf", 1), ("Spiky Shield", 1), ("Slurp Gloves", 1),
                    ("Kevin", 1), ("Mirror", 1), ("Clover", 2),
                    ("Golden Shield", 2), ("Campfire", 3), ("Beacon", 4),
                    ("Big Bonk", 11),
                )
            )
            view._items_section.update(items)
            update_banishes_section(
                view._banishes_view,
                view._banishes_label,
                ("Fire Tome", "Ice Tome", "Anvil", "Wrench", "Beer", "Key"),
            )

            page = view._tab
            tabview.addTab(page, "Recordings") if page.parent() is None else None
            for height in (620, 800, 1000):
                tabview.resize(1520, height)
                tabview.show()
                tabview.setCurrentWidget(page)
                for _ in range(4):
                    app.processEvents()

                card = page.findChild(QGroupBox, "LiveStatsItems")
                scroll = card.findChild(QScrollArea, "LiveStatsItemsScroll")
                divider = card.findChild(QFrame, "LiveStatsItemsDivider")
                banishes = card.findChild(QWidget, "LiveStatsBanishes")
                assert None not in (card, scroll, divider, banishes)

                where = f"at {height}px: card={card.height()}"
                assert scroll.geometry().bottom() < divider.geometry().top(), (
                    f"{where} scroll={scroll.geometry()} divider={divider.geometry()}"
                )
                assert divider.geometry().bottom() < banishes.geometry().top(), where
                assert banishes.geometry().bottom() <= card.height(), (
                    f"{where} banishes={banishes.geometry()}"
                )
                # And the list is still the bigger half of the split, which is
                # what the floor was there to guarantee.
                assert scroll.height() >= banishes.height(), (
                    f"{where} scroll={scroll.height()} banishes={banishes.height()}"
                )
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
