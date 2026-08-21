"""The Damage Sources panel reuses its cards instead of rebuilding them.

It was the most expensive of the four card panels -- 48 ms of a 103 ms
Recordings scrub frame -- and almost all of that was construction: every render
tore the grid down and built a fresh `QFrame`, four `QLabel`s and a
`QProgressBar` per source.

Reuse buys speed and costs correctness risk in one specific way: a card that
survives a render can keep showing the *previous* source. Every case here is
about what the cards say afterwards, because that is the failure reuse
introduces and no timing measurement can see it.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.tabs.player_stats.stat_cards import StatCardsView


def _source(key: str, damage: float | None):
    return SimpleNamespace(source_key=key, source_name=key.title(), damage=damage)


class DamageSourceCardReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.host = QWidget()
        self.layout = QVBoxLayout(self.host)
        self.status = QLabel()
        self.view = StatCardsView(
            weapons_layout=None,
            weapons_status_label=None,
            tomes_layout=None,
            tomes_status_label=None,
            chaos_layout=None,
            chaos_status_label=None,
            damage_sources_layout=self.layout,
            damage_sources_status_label=self.status,
        )

    @property
    def cards(self):
        return self.view._damage_source_cards

    @staticmethod
    def _texts(card):
        return [label.text() for label in card.findChildren(QLabel)]

    def test_a_card_is_created_per_source(self) -> None:
        self.view.display_damage_sources((_source("katana", 30.0), _source("orb", 10.0)))

        self.assertEqual(len(self.cards), 2)
        self.assertIn("Katana", self._texts(self.cards[0]))
        self.assertIn("Orb", self._texts(self.cards[1]))

    def test_the_same_widgets_survive_a_rerender(self) -> None:
        """The point of the change: no teardown between frames."""
        self.view.display_damage_sources((_source("katana", 30.0), _source("orb", 10.0)))
        first, second = self.cards

        self.view.display_damage_sources((_source("katana", 90.0), _source("orb", 20.0)))

        self.assertIs(self.cards[0], first)
        self.assertIs(self.cards[1], second)

    def test_a_reused_card_shows_the_new_source(self) -> None:
        """The failure reuse introduces: a card left showing the old source."""
        self.view.display_damage_sources((_source("katana", 30.0),))
        self.view.display_damage_sources((_source("bow", 55.0),))

        self.assertEqual(len(self.cards), 1)
        self.assertIn("Bow", self._texts(self.cards[0]))
        self.assertNotIn("Katana", self._texts(self.cards[0]))

    def test_the_pool_grows_when_a_source_appears(self) -> None:
        self.view.display_damage_sources((_source("katana", 30.0),))
        self.view.display_damage_sources((_source("katana", 30.0), _source("orb", 10.0)))

        self.assertEqual(len(self.cards), 2)
        self.assertIn("Orb", self._texts(self.cards[1]))

    def test_the_pool_shrinks_when_a_source_disappears(self) -> None:
        """A stale trailing card would keep a source on screen after it is gone."""
        self.view.display_damage_sources(
            (_source("katana", 30.0), _source("orb", 10.0), _source("bow", 5.0))
        )
        self.view.display_damage_sources((_source("katana", 30.0),))

        self.assertEqual(len(self.cards), 1)
        rendered = [text for card in self.cards for text in self._texts(card)]
        self.assertNotIn("Orb", rendered)
        self.assertNotIn("Bow", rendered)

    def test_ranks_follow_the_new_order(self) -> None:
        """Sources are sorted by damage, so reuse must rewrite the rank too."""
        self.view.display_damage_sources((_source("katana", 30.0), _source("orb", 10.0)))
        self.view.display_damage_sources((_source("katana", 5.0), _source("orb", 90.0)))

        self.assertIn("Orb", self._texts(self.cards[0]))
        self.assertIn("#1", self._texts(self.cards[0]))
        self.assertIn("Katana", self._texts(self.cards[1]))
        self.assertIn("#2", self._texts(self.cards[1]))

    def test_an_empty_reading_tears_the_panel_down(self) -> None:
        self.view.display_damage_sources((_source("katana", 30.0),))

        self.view.display_damage_sources((), status_text="Damage sources unavailable")

        self.assertEqual(self.cards, [])
        self.assertIsNone(self.view._damage_sources_grid)
        self.assertEqual(self.status.text(), "Damage sources unavailable")

    def test_rebuilding_after_an_empty_reading_works(self) -> None:
        """The torn-down panel must come back, not stay blank."""
        self.view.display_damage_sources((_source("katana", 30.0),))
        self.view.display_damage_sources(())

        self.view.display_damage_sources((_source("bow", 12.0),))

        self.assertEqual(len(self.cards), 1)
        self.assertIn("Bow", self._texts(self.cards[0]))

    def test_the_total_line_follows_the_sources(self) -> None:
        self.view.display_damage_sources((_source("katana", 30.0), _source("orb", 10.0)))
        summary = self.view._damage_sources_summary
        self.assertIn("2 sources", [label.text() for label in summary.findChildren(QLabel)])

        self.view.display_damage_sources((_source("katana", 30.0),))

        self.assertIn("1 source", [label.text() for label in summary.findChildren(QLabel)])

    def test_an_unknown_damage_is_not_displayed_or_totalled_as_zero(self) -> None:
        self.view.display_damage_sources(
            (_source("katana", 30.0), _source("overflow", None))
        )

        summary_text = self._texts(self.view._damage_sources_summary)
        overflow_text = self._texts(self.cards[1])
        self.assertIn("--", summary_text)
        self.assertIn("Overflow", overflow_text)
        self.assertGreaterEqual(overflow_text.count("--"), 2)


if __name__ == "__main__":
    unittest.main()
