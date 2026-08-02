"""Hidden card panels record their last render instead of performing it.

Rebuilding a panel nobody is looking at was the whole cost of a Recordings
scrub frame: measured over a 713-snapshot recording, the four panels here were
95 ms of a 103 ms frame, and the tab opens on *Stats*, where none of them is on
screen.

The risk the deferral introduces is a panel that is stale *and stays that way*,
which no timing measurement can catch -- so these cases are about what the
panel shows after it is revealed, not about how long it took.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from support.player_stats import FakeCardsLayout, FakeTimelineWidget
from ui.tabs.player_stats.stat_cards import StatCardsView


def _weapon(weapon_id: int, level: int):
    return SimpleNamespace(
        weapon_id=weapon_id,
        name=f"Weapon {weapon_id}",
        level=level,
        upgrade_stat_ids=(),
        upgraded_stats={},
    )


class DeferredSectionTests(unittest.TestCase):
    def _view(self, visible_sections: set[str]):
        self.widgets = {
            "weapons_layout": FakeCardsLayout(),
            "weapons_status_label": FakeTimelineWidget("weapons_status_label"),
            "tomes_layout": FakeCardsLayout(),
            "tomes_status_label": FakeTimelineWidget("tomes_status_label"),
            "chaos_layout": FakeCardsLayout(),
            "chaos_status_label": FakeTimelineWidget("chaos_status_label"),
            "damage_sources_layout": FakeCardsLayout(),
            "damage_sources_status_label": FakeTimelineWidget("damage_sources_status_label"),
        }
        self.visible = visible_sections
        return StatCardsView(
            **self.widgets,
            section_visible=lambda section: section in self.visible,
        )

    def test_a_hidden_panel_is_not_rebuilt(self) -> None:
        view = self._view(set())

        view.display_weapons((_weapon(1, 3),))

        self.assertEqual(self.widgets["weapons_layout"].count(), 0)
        self.assertIsNone(self.widgets["weapons_status_label"].text)

    def test_a_visible_panel_still_renders(self) -> None:
        view = self._view({"weapons"})

        view.display_weapons((_weapon(1, 3),))

        self.assertGreater(self.widgets["weapons_layout"].count(), 0)

    def test_revealing_a_panel_draws_what_it_missed(self) -> None:
        """The deferral must not turn into a permanently stale panel."""
        view = self._view(set())
        view.display_weapons((_weapon(1, 3),))

        self.visible.add("weapons")
        view.flush_pending()

        self.assertGreater(self.widgets["weapons_layout"].count(), 0)

    def test_only_the_last_hidden_call_is_kept(self) -> None:
        """A scrub makes hundreds of calls; the panel owes exactly one render."""
        view = self._view(set())
        for level in range(1, 6):
            view.display_weapons((_weapon(1, level),))

        self.visible.add("weapons")
        view.flush_pending()

        # One render, and it is the newest state: a second flush has nothing
        # left to do.
        count_after_first = self.widgets["weapons_layout"].count()
        view.flush_pending()
        self.assertEqual(self.widgets["weapons_layout"].count(), count_after_first)

    def test_a_panel_still_hidden_keeps_its_debt(self) -> None:
        """Switching between two hidden panels must not drop the skipped one."""
        view = self._view(set())
        view.display_weapons((_weapon(1, 3),))
        view.display_tomes(())

        self.visible.add("tomes")
        view.flush_pending()
        self.assertEqual(self.widgets["weapons_layout"].count(), 0)

        self.visible.add("weapons")
        view.flush_pending()
        self.assertGreater(self.widgets["weapons_layout"].count(), 0)

    def test_a_deferred_call_is_not_suppressed_as_a_repeat(self) -> None:
        """The signature cache must not record a render that never happened.

        Deferring while updating the signature would leave the panel blank
        forever: the flush would compare equal and return without drawing.
        """
        view = self._view(set())
        weapons = (_weapon(1, 3),)
        view.display_weapons(weapons)
        self.visible.add("weapons")
        view.flush_pending()

        self.assertGreater(self.widgets["weapons_layout"].count(), 0)

    def test_without_a_visibility_port_everything_renders(self) -> None:
        """Live Stats and Compare Runs build this view and did not opt in."""
        widgets = {
            "weapons_layout": FakeCardsLayout(),
            "weapons_status_label": FakeTimelineWidget("weapons_status_label"),
            "tomes_layout": FakeCardsLayout(),
            "tomes_status_label": FakeTimelineWidget("tomes_status_label"),
            "chaos_layout": FakeCardsLayout(),
            "chaos_status_label": FakeTimelineWidget("chaos_status_label"),
            "damage_sources_layout": FakeCardsLayout(),
            "damage_sources_status_label": FakeTimelineWidget("damage_sources_status_label"),
        }
        view = StatCardsView(**widgets)

        view.display_weapons((_weapon(1, 3),))

        self.assertGreater(widgets["weapons_layout"].count(), 0)


if __name__ == "__main__":
    unittest.main()
