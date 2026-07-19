"""Coverage for the Live Stats Powerups card.

`format_live_powerups_card` and `_apply_live_powerups_card` had **no covering
tests at all** -- the only two suite references to the former are a module-map
assertion and a docstring. Mutating the renderer to a no-op left all 639 tests
green, because every test that reaches it goes through an injected view double.

Found while routing `refresh_powerups_card` onto `PlayerStatsView` at step 19,
and closed here rather than carried: this step gave that method a new name and
a new caller, so leaving it unasserted would mean the rename was unverified.

Unbound calls against plain stubs, which is what the step-18 phase-1 plan
prescribes while the subject is still a mixin.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from ui.tabs.player_stats.live_stats import LiveStatsTabMixin

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


class PowerupsHost(LiveStatsTabMixin):
    """A double over the one mixin under test, not over `MegabonkApp`.

    `_apply_live_powerups_card` calls `self.format_live_powerups_card`, so a
    bare `SimpleNamespace` cannot stand in. Deriving from the single mixin
    gives the real sibling method without borrowing the app's whole MRO --
    which is what `object.__new__(MegabonkApp)` does and what the step-18
    phase-1 ratchet exists to stop spreading.
    """

    def __init__(self, tracker, *, group=None, labels=None) -> None:
        self.live_run_tracker = tracker
        self.player_stats_powerups_group = group
        self.player_stats_live_powerup_labels = labels


def owner_with(tracker, *, group=None, labels=None):
    return PowerupsHost(tracker, group=group, labels=labels)


def tracker_without_snapshot():
    """A tracker whose powerups snapshot is unavailable, so stats decide."""
    return SimpleNamespace(powerups_snapshot=lambda: SimpleNamespace(available=False))


def tracker_with_snapshot(**kwargs):
    snapshot = SimpleNamespace(available=True, active=(), **kwargs)
    return SimpleNamespace(powerups_snapshot=lambda: snapshot)


class FormatLivePowerupsCardTests(unittest.TestCase):
    def test_no_snapshot_and_no_stats_leaves_every_effect_dashed(self) -> None:
        title, values = LiveStatsTabMixin.format_live_powerups_card(
            owner_with(tracker_without_snapshot()), {}
        )
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

        title, values = LiveStatsTabMixin.format_live_powerups_card(
            owner_with(tracker_without_snapshot()), stats
        )

        self.assertEqual(title, "Powerups (PM 2.00x)")
        self.assertEqual(values["Clock"], "-- (24s)")
        for name in ("Rage", "Shield", "Stonks"):
            self.assertEqual(values[name], "-- (30s)", name)

    def test_a_non_numeric_multiplier_is_ignored(self) -> None:
        stats = {"Powerup Multiplier": SimpleNamespace(value=None, display_value="--")}
        title, values = LiveStatsTabMixin.format_live_powerups_card(
            owner_with(tracker_without_snapshot()), stats
        )
        self.assertEqual(title, "Powerups")
        self.assertEqual(values["Rage"], "--")

    def test_an_infinite_multiplier_is_ignored(self) -> None:
        stats = {
            "Powerup Multiplier": SimpleNamespace(value=float("inf"), display_value="inf")
        }
        title, values = LiveStatsTabMixin.format_live_powerups_card(
            owner_with(tracker_without_snapshot()), stats
        )
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

        title, values = LiveStatsTabMixin.format_live_powerups_card(
            owner_with(tracker), stats
        )

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

        _title, values = LiveStatsTabMixin.format_live_powerups_card(
            owner_with(tracker), {}
        )

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

        title, values = LiveStatsTabMixin.format_live_powerups_card(
            owner_with(tracker), {}
        )

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

        LiveStatsTabMixin._apply_live_powerups_card(owner, stats)

        self.assertEqual(group.title(), "Powerups (PM 1.00x)")
        self.assertEqual(labels["Clock"].text(), "Clock: -- (12s)")
        self.assertEqual(labels["Rage"].text(), "Rage: -- (15s)")

    def test_missing_widgets_are_a_no_op(self) -> None:
        """The tab is not built yet during early refresh ticks."""
        LiveStatsTabMixin._apply_live_powerups_card(
            owner_with(tracker_without_snapshot(), group=None, labels=None), {}
        )
        LiveStatsTabMixin._apply_live_powerups_card(
            owner_with(tracker_without_snapshot(), group=FakeGroup(), labels=None), {}
        )


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

        LiveStatsTabMixin.refresh_powerups_card(owner)

        self.assertEqual(group.title(), "Powerups (PM 2.00x)")
        self.assertEqual(labels["Clock"].text(), "Clock: -- (24s)")

    def test_the_port_operation_ignores_stats_and_reads_the_tracker(self) -> None:
        """It passes `None` for stats, so only the tracker can drive it."""
        group = FakeGroup()
        labels = {name: FakeLabel() for name in EFFECTS}
        owner = owner_with(tracker_without_snapshot(), group=group, labels=labels)

        LiveStatsTabMixin.refresh_powerups_card(owner)

        self.assertEqual(group.title(), "Powerups")
        self.assertEqual(labels["Rage"].text(), "Rage: --")


if __name__ == "__main__":
    unittest.main()
