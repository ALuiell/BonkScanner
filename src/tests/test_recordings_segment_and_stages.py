"""Two decisions the Recordings tab makes about *when* to show things.

Both replaced behaviour that looked fine while you sat still and wrong while
you scrubbed, and both were written after a tamper run showed the existing
suite could not tell the difference:

* stage cards describe the whole recording, not the prefix up to the playhead;
* Compare Details appears only once a compare pin exists.

Driven through `build_recordings_tab` -- the component's real constructor --
with stand-in widgets for the labels asserted on, the same shape
`test_timeline_scrub_performance` uses.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from support.player_stats import (
    RecordingItemsSectionView,
    RecordingStatCardsView,
    build_recordings_tab,
)


class FakeLabel:
    def __init__(self, text: str = "") -> None:
        self.value = text

    def setText(self, text: str) -> None:
        self.value = text

    def text(self) -> str:
        return self.value


class FakeGroup:
    """Enough `QGroupBox` for a visibility assertion."""

    def __init__(self) -> None:
        self.visible: bool | None = None

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class FakeScrubber:
    """The scrubber as this tab drives it: index, pin, model, slots."""

    def __init__(self, count: int = 0) -> None:
        self.enabled = True
        self.index = 0
        self.pin = None
        self.model = SimpleNamespace(count=count, stages=(), series=lambda _key: None)
        self.series_keys = ()
        self.cap_keys = ()
        # The model must carry the capped stats too, or a ceiling drawn without
        # its curve has no scale to sit on. The tab reads this, not
        # `series_keys`, so the double has to have it.
        self.model_keys = ()
        self.slots = ()

    def setEnabled(self, enabled) -> None:
        self.enabled = bool(enabled)

    def set_index(self, index, *, emit: bool = False) -> None:
        self.index = int(index)

    def set_pin(self, index, *, emit: bool = False) -> None:
        self.pin = index

    def set_model(self, model) -> None:
        self.model = model

    def set_slots(self, slots) -> None:
        self.slots = tuple(slots)
        self.series_keys = tuple(key for slot in self.slots for key in slot)
        self.model_keys = tuple(dict.fromkeys(self.series_keys + self.cap_keys))

    def set_cap_keys(self, cap_keys) -> None:
        self.cap_keys = tuple(cap_keys)
        self.model_keys = tuple(dict.fromkeys(self.series_keys + self.cap_keys))


def _snapshot(elapsed: int, *, stage_index: int, kills: int, items=()):
    return SimpleNamespace(
        elapsed_seconds=elapsed,
        game_time_seconds=float(elapsed),
        stage_index=stage_index,
        stage_time_seconds=float(elapsed),
        stage_ptr=stage_index + 1,
        mob_kills=kills,
        items=tuple(items),
        banishes=(),
        weapons=(),
        tomes=(),
        chaos_tome=None,
        damage_sources=(),
        player_level=1,
        stats={},
        time_label=f"{elapsed:02d}s",
    )


#: A run that reaches stage 2. Stage 1's totals must be readable at snapshot 0.
SNAPSHOTS = (
    _snapshot(0, stage_index=0, kills=0),
    _snapshot(30, stage_index=0, kills=1_000, items=("Anvil x1",)),
    _snapshot(60, stage_index=0, kills=5_000, items=("Anvil x1", "Key x2")),
    _snapshot(90, stage_index=1, kills=9_000, items=("Anvil x1", "Key x2")),
    _snapshot(120, stage_index=1, kills=20_000, items=("Anvil x2", "Key x2")),
)


def _tab_with_stage_cards(snapshots=SNAPSHOTS):
    tab = build_recordings_tab()
    tab._loaded_vod = SimpleNamespace(
        metadata=SimpleNamespace(name="Run", created_label="today", duration_seconds=120),
        snapshots=snapshots,
    )
    tab._snapshot_index = 0
    tab._requested_snapshot_index = 0
    tab._status_label = FakeLabel()
    tab._position_label = FakeLabel()
    tab._legend_label = FakeLabel()
    tab._compare_hint_label = FakeLabel()
    tab._scrubber = FakeScrubber(count=len(snapshots))
    tab._stage_summary_labels = [
        {
            "stage": FakeLabel(),
            "time": FakeLabel(),
            "kills": FakeLabel(),
            "items": FakeLabel(),
        }
        for _ in range(4)
    ]
    # `_refresh_stage_cards` walks the real cards; there are none on this
    # harness, and its early return is the honest stand-in.
    tab._stage_cards = []
    tab._items_section = RecordingItemsSectionView()
    tab._stat_cards = RecordingStatCardsView()
    tab._rows = {}
    tab._compact_rows = {}
    tab._banishes_label = FakeLabel()
    tab._chests_per_minute_label = FakeLabel()
    tab._chests_card_values = {}
    tab._loot_rarity_card_values = {}
    return tab


class StageCardTests(unittest.TestCase):
    def test_stage_totals_are_complete_at_the_first_snapshot(self) -> None:
        """The whole run, not the prefix up to the playhead.

        The prefix version filled the cards in *as you scrubbed*, so a run's
        stage totals appeared to depend on where you were looking. Asserting at
        index 0 is what pins the difference: with a prefix, stage 2 would still
        be empty here.
        """
        tab = _tab_with_stage_cards()
        tab.refresh_loaded_vod_ui()

        stage_one, stage_two = tab._stage_summary_labels[0], tab._stage_summary_labels[1]
        self.assertNotEqual(stage_one["kills"].text(), "--")
        self.assertNotEqual(stage_two["kills"].text(), "--")
        self.assertNotEqual(stage_two["time"].text(), "--")

    def test_scrubbing_does_not_change_the_stage_totals(self) -> None:
        tab = _tab_with_stage_cards()
        tab.refresh_loaded_vod_ui()
        at_start = {
            key: labels[key].text()
            for labels in tab._stage_summary_labels
            for key in ("time", "kills")
        }

        tab.display_loaded_vod_snapshot(len(SNAPSHOTS) - 1)

        at_end = {
            key: labels[key].text()
            for labels in tab._stage_summary_labels
            for key in ("time", "kills")
        }
        self.assertEqual(at_start, at_end)

    def test_stages_the_run_never_reached_stay_empty(self) -> None:
        tab = _tab_with_stage_cards()
        tab.refresh_loaded_vod_ui()

        self.assertEqual(tab._stage_summary_labels[2]["kills"].text(), "--")
        self.assertEqual(tab._stage_summary_labels[3]["kills"].text(), "--")


class StageRangeSelectionTests(unittest.TestCase):
    def _tab(self):
        tab = _tab_with_stage_cards()
        tab._compare_details_group = FakeGroup()
        tab._compare_details_summary_label = FakeLabel()
        tab._compare_details_items_label = FakeLabel()
        tab.refresh_loaded_vod_ui()
        return tab

    def test_click_then_shift_click_compares_the_complete_first_stage(self) -> None:
        tab = self._tab()

        tab.on_stage_card_clicked(1)
        self.assertEqual(tab._snapshot_index, 0)
        self.assertEqual(tab._stage_range_anchor_number, 1)
        self.assertIsNone(tab._compare_start_index)

        tab.on_stage_card_clicked(2, shift_pressed=True)

        self.assertEqual(tab._snapshot_index, 0)
        self.assertEqual(tab._compare_start_index, 2)
        self.assertEqual(tab._scrubber.pin, 2)
        self.assertTrue(tab._compare_details_group.visible)

    def test_shift_clicking_the_anchor_again_compares_the_whole_stage(self) -> None:
        tab = self._tab()

        tab.on_stage_card_clicked(2)
        tab.on_stage_card_clicked(2, shift_pressed=True)

        self.assertEqual(tab._snapshot_index, 3)
        self.assertEqual(tab._compare_start_index, 4)
        self.assertEqual(tab._scrubber.pin, 4)

    def test_shift_clicking_an_earlier_stage_keeps_a_on_the_anchor(self) -> None:
        tab = self._tab()

        tab.on_stage_card_clicked(2)
        tab.on_stage_card_clicked(1, shift_pressed=True)

        self.assertEqual(tab._snapshot_index, 3)
        self.assertEqual(tab._compare_start_index, 0)
        self.assertEqual(tab._scrubber.pin, 0)

    def test_a_shift_click_without_an_anchor_behaves_like_a_normal_jump(self) -> None:
        tab = self._tab()

        tab.on_stage_card_clicked(2, shift_pressed=True)

        self.assertEqual(tab._snapshot_index, 3)
        self.assertEqual(tab._stage_range_anchor_number, 2)
        self.assertIsNone(tab._compare_start_index)

    def test_a_new_plain_stage_click_clears_an_older_manual_pin(self) -> None:
        tab = self._tab()
        tab.set_vod_compare_start(1)

        tab.on_stage_card_clicked(2)

        self.assertIsNone(tab._compare_start_index)
        self.assertIsNone(tab._scrubber.pin)
        self.assertFalse(tab._compare_details_group.visible)


class CompareDetailsVisibilityTests(unittest.TestCase):
    def _tab(self):
        tab = _tab_with_stage_cards()
        tab._compare_details_group = FakeGroup()
        tab._compare_details_summary_label = FakeLabel()
        tab._compare_details_items_label = FakeLabel()
        return tab

    def test_hidden_while_no_compare_pin_is_set(self) -> None:
        """Without a pin the base snapshot is simply the previous one.

        That is a ten-second delta -- the snapshot cadence -- and showing it
        was what made the old "Segment Compare" card read as broken rather than
        as empty.
        """
        tab = self._tab()
        tab._compare_start_index = None

        tab.display_loaded_vod_snapshot(3)

        self.assertFalse(tab._compare_details_group.visible)

    def test_shown_once_a_pin_exists(self) -> None:
        tab = self._tab()

        tab.set_vod_compare_start(1)

        self.assertTrue(tab._compare_details_group.visible)
        self.assertEqual(tab._scrubber.pin, 1)

    def test_clearing_the_pin_hides_it_again(self) -> None:
        tab = self._tab()
        tab.set_vod_compare_start(1)

        tab.clear_vod_compare_start()

        self.assertFalse(tab._compare_details_group.visible)
        self.assertIsNone(tab._scrubber.pin)

    def test_the_timeline_accents_both_segment_ends(self) -> None:
        """Same A-playhead/B-pin pairing as the card's header line."""
        tab = self._tab()
        tab.display_loaded_vod_snapshot(3)

        tab.set_vod_compare_start(1)

        hint = tab._compare_hint_label.text()
        self.assertIn('<b style="color:#38BDF8;">A</b>', hint)
        self.assertIn('<b style="color:#C084FC;">B</b>', hint)
        self.assertLess(hint.index(SNAPSHOTS[3].time_label), hint.index(SNAPSHOTS[1].time_label))

    def test_the_pin_drives_the_compare_baseline(self) -> None:
        tab = self._tab()
        tab.set_vod_compare_start(0)
        tab.display_loaded_vod_snapshot(4)

        self.assertIs(tab._resolve_vod_compare_base_snapshot(4), SNAPSHOTS[0])
        self.assertEqual(len(tab._vod_compare_segment_snapshots(4)), 5)


if __name__ == "__main__":
    unittest.main()
