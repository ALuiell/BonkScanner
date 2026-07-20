"""Coverage for the Live Stats Powerups card.

`format_live_powerups_card` and `_apply_live_powerups_card` had **no covering
tests at all** -- the only two suite references to the former are a module-map
assertion and a docstring. Mutating the renderer to a no-op left all 639 tests
green, because every test that reaches it goes through an injected view double.

Found while routing `refresh_powerups_card` onto `PlayerStatsView` at step 19,
and closed here rather than carried: this step gave that method a new name and
a new caller, so leaving it unasserted would mean the rename was unverified.

Step 19 converted the subject: these ran class-qualified against
`LiveStatsTabMixin` while it was a base of `MegabonkApp`, and now build a real
`LiveStatsTab` through `support.player_stats.build_live_stats_tab` and call it
bound. Two of the three assertions below are unchanged; only the construction
moved, which is the point of the builder.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from tests.support.player_stats import build_live_stats_tab

EFFECTS = ("Rage", "Clock", "Shield", "Stonks")


class FakeLabel:
    def __init__(self) -> None:
        self._text = ""

    def setText(self, text) -> None:
        self._text = str(text)

    def text(self) -> str:
        return self._text


class FakeGroup:
    def __init__(self) -> None:
        self._title = "Powerups"

    def setTitle(self, title) -> None:
        self._title = str(title)

    def title(self) -> str:
        return self._title


def owner_with(tracker, *, group=None, labels=None):
    """A real `LiveStatsTab` wired to `tracker`, with the card's two widgets.

    `_apply_live_powerups_card` calls `self.format_live_powerups_card`, so a
    bare `SimpleNamespace` cannot stand in -- and after step 19 it does not
    have to: the real constructor is cheap, and `build()` is what needs Qt.
    The two widget attributes are assigned directly because they are exactly
    what these tests assert on.
    """
    view = build_live_stats_tab(live_run_tracker=lambda: tracker)
    view._powerups_group = group
    view._powerup_labels = labels
    return view


def tracker_without_snapshot():
    """A tracker whose powerups snapshot is unavailable, so stats decide."""
    return SimpleNamespace(powerups_snapshot=lambda: SimpleNamespace(available=False))


def tracker_with_snapshot(**kwargs):
    snapshot = SimpleNamespace(available=True, active=(), **kwargs)
    return SimpleNamespace(powerups_snapshot=lambda: snapshot)


class FormatLivePowerupsCardTests(unittest.TestCase):
    def test_no_snapshot_and_no_stats_leaves_every_effect_dashed(self) -> None:
        title, values = owner_with(tracker_without_snapshot()).format_live_powerups_card({})
        self.assertEqual(title, "Powerups")
        self.assertEqual(values, {name: "--" for name in EFFECTS})

    def test_a_powerup_multiplier_stat_drives_the_title_and_durations(self) -> None:
        """Without a snapshot, the card is derived from the stat alone.

        Clock uses a 12 s base and the others 15 s; that asymmetry is the
        thing worth pinning, because it is silent if it inverts.
        """
        stats = {
            "Powerup Multiplier": SimpleNamespace(value=2.0, display_value="2.00x")
        }

        title, values = owner_with(tracker_without_snapshot()).format_live_powerups_card(stats)

        self.assertEqual(title, "Powerups (PM 2.00x)")
        self.assertEqual(values["Clock"], "-- (24s)")
        for name in ("Rage", "Shield", "Stonks"):
            self.assertEqual(values[name], "-- (30s)", name)

    def test_a_non_numeric_multiplier_is_ignored(self) -> None:
        stats = {"Powerup Multiplier": SimpleNamespace(value=None, display_value="--")}
        title, values = owner_with(tracker_without_snapshot()).format_live_powerups_card(stats)
        self.assertEqual(title, "Powerups")
        self.assertEqual(values["Rage"], "--")

    def test_an_infinite_multiplier_is_ignored(self) -> None:
        stats = {
            "Powerup Multiplier": SimpleNamespace(value=float("inf"), display_value="inf")
        }
        title, values = owner_with(tracker_without_snapshot()).format_live_powerups_card(stats)
        self.assertEqual(title, "Powerups")
        self.assertEqual(values["Rage"], "--")

    def test_an_available_snapshot_wins_over_the_stat(self) -> None:
        tracker = tracker_with_snapshot(
            powerup_multiplier_display="3.00x",
            standard_duration_seconds=45.0,
            clock_duration_seconds=36.0,
        )
        stats = {
            "Powerup Multiplier": SimpleNamespace(value=2.0, display_value="2.00x")
        }

        title, values = owner_with(tracker).format_live_powerups_card(stats)

        self.assertEqual(title, "Powerups (PM 3.00x)")
        self.assertEqual(values["Clock"], "-- (36s)")
        self.assertEqual(values["Rage"], "-- (45s)")

    def test_an_active_effect_renders_its_window_and_remaining(self) -> None:
        effect = SimpleNamespace(
            name="Rage",
            remaining_seconds=7.0,
            pickup_ui="01:00",
            expires_ui="01:15",
        )
        tracker = SimpleNamespace(
            powerups_snapshot=lambda: SimpleNamespace(
                available=True,
                active=(effect,),
                powerup_multiplier_display="1.00x",
                standard_duration_seconds=15.0,
                clock_duration_seconds=12.0,
            )
        )

        _title, values = owner_with(tracker).format_live_powerups_card({})

        self.assertEqual(values["Rage"], "01:00 -> 01:15 (7s)")
        self.assertEqual(values["Shield"], "-- (15s)")

    def test_an_active_effect_without_a_window_shows_only_remaining(self) -> None:
        effect = SimpleNamespace(
            name="Shield", remaining_seconds=3.0, pickup_ui=None, expires_ui=None
        )
        tracker = SimpleNamespace(
            powerups_snapshot=lambda: SimpleNamespace(
                available=True,
                active=(effect,),
                powerup_multiplier_display="--",
                standard_duration_seconds=15.0,
                clock_duration_seconds=12.0,
            )
        )

        title, values = owner_with(tracker).format_live_powerups_card({})

        self.assertEqual(title, "Powerups", "a '--' multiplier must not reach the title")
        self.assertEqual(values["Shield"], "(3s)")


class ApplyLivePowerupsCardTests(unittest.TestCase):
    def test_the_card_title_and_every_label_are_written(self) -> None:
        group = FakeGroup()
        labels = {name: FakeLabel() for name in EFFECTS}
        stats = {
            "Powerup Multiplier": SimpleNamespace(value=1.0, display_value="1.00x")
        }
        owner = owner_with(tracker_without_snapshot(), group=group, labels=labels)

        owner._apply_live_powerups_card(stats)

        self.assertEqual(group.title(), "Powerups (PM 1.00x)")
        self.assertEqual(labels["Clock"].text(), "Clock: -- (12s)")
        self.assertEqual(labels["Rage"].text(), "Rage: -- (15s)")

    def test_missing_widgets_are_a_no_op(self) -> None:
        """The tab is not built yet during early refresh ticks."""
        owner_with(tracker_without_snapshot(), group=None, labels=None)._apply_live_powerups_card({})
        owner_with(tracker_without_snapshot(), group=FakeGroup(), labels=None)._apply_live_powerups_card({})


class RefreshPowerupsCardPortTests(unittest.TestCase):
    """The `PlayerStatsView` operation itself, renamed at step 19.

    Separate because neutering the delegation -- the one line that hands
    `None` to the renderer -- left the suite green even with the renderer
    covered, the same gap `set_stage_summary_rows` had.
    """

    def test_the_port_operation_repaints_from_the_tracker(self) -> None:
        group = FakeGroup()
        labels = {name: FakeLabel() for name in EFFECTS}
        tracker = tracker_with_snapshot(
            powerup_multiplier_display="2.00x",
            standard_duration_seconds=30.0,
            clock_duration_seconds=24.0,
        )
        owner = owner_with(tracker, group=group, labels=labels)

        owner.refresh_powerups_card()

        self.assertEqual(group.title(), "Powerups (PM 2.00x)")
        self.assertEqual(labels["Clock"].text(), "Clock: -- (24s)")

    def test_the_port_operation_ignores_stats_and_reads_the_tracker(self) -> None:
        """It passes `None` for stats, so only the tracker can drive it."""
        group = FakeGroup()
        labels = {name: FakeLabel() for name in EFFECTS}
        owner = owner_with(tracker_without_snapshot(), group=group, labels=labels)

        owner.refresh_powerups_card()

        self.assertEqual(group.title(), "Powerups")
        self.assertEqual(labels["Rage"].text(), "Rage: --")


if __name__ == "__main__":
    unittest.main()
