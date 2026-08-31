"""Behaviour of the Recordings scrubber's read model.

The arithmetic behind what the scrubber paints -- stage bands, the Difficulty
cap staircase, shared axis groups, event markers -- lives in
`projections/scrubber.py` precisely so it can be tested without an offscreen
`QApplication`. These tests drive it with hand-built snapshots rather than a
loaded recording: a fixture read from `stats_recordings/` would assert against
whatever that run happened to do, and the interesting cases here (a stage with
no cap, the post-boss timer spike, a series that is absent) are ones no single
real run contains all of.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core.stage_rules import (
    DIFFICULTY_CAP_BY_STAGE,
    GHOSTS_DELAY_SECONDS,
    STAGE_DURATION_SECONDS,
    XP_GAIN_CAP,
)
from projections import scrubber


def _stat(value):
    return SimpleNamespace(value=value, display_value=str(value))


def _snapshot(
    *,
    stage_index=0,
    stage_time=0.0,
    elapsed=0,
    kills=0,
    items=(),
    banishes=(),
    **stats,
):
    return SimpleNamespace(
        stage_index=stage_index,
        stage_time_seconds=stage_time,
        elapsed_seconds=elapsed,
        # The stage-4 heuristics diff the run clock across the boss-room
        # boundary, and treat a missing one as "cannot tell". Without this the
        # boss room is undetectable and the band test silently proves nothing.
        game_time_seconds=float(elapsed),
        mob_kills=kills,
        items=tuple(items),
        banishes=tuple(banishes),
        stats={label.replace("_", " "): _stat(value) for label, value in stats.items()},
    )


class StageBandTests(unittest.TestCase):
    def test_consecutive_stages_become_one_band_each(self) -> None:
        snapshots = [
            _snapshot(stage_index=0, elapsed=0),
            _snapshot(stage_index=0, elapsed=30),
            _snapshot(stage_index=1, elapsed=60),
            _snapshot(stage_index=1, elapsed=90),
            _snapshot(stage_index=2, elapsed=120),
        ]
        bands = scrubber.build_stage_bands(snapshots)
        self.assertEqual([band.label for band in bands], ["Stage 1", "Stage 2", "Stage 3"])
        self.assertEqual([(band.start, band.end) for band in bands], [(0, 1), (2, 3), (4, 4)])

    def test_band_carries_its_own_elapsed_span(self) -> None:
        snapshots = [
            _snapshot(stage_index=0, elapsed=100),
            _snapshot(stage_index=0, elapsed=400),
            _snapshot(stage_index=1, elapsed=500),
        ]
        bands = scrubber.build_stage_bands(snapshots)
        self.assertEqual(bands[0].elapsed_seconds, 300)

    def test_the_boss_room_is_its_own_band_despite_the_raw_index(self) -> None:
        """The raw index stays at 2 through Stage 4, so it cannot be grouped on.

        This is the fault the bands shipped with: a run whose Stage Summary
        showed four rows drew three bands, because `stage_index` never leaves 2
        once the boss room reuses the stage pointer. Bands go through
        `run_summary.stage_number_sequence` for exactly this case.
        """
        snapshots = [
            _snapshot(stage_index=2, stage_time=300.0, elapsed=0),
            _snapshot(stage_index=2, stage_time=400.0, elapsed=30),
            # The stage timer collapsing inside the same pointer is what the
            # tracker reads as the boss room.
            _snapshot(stage_index=2, stage_time=1.0, elapsed=60),
            _snapshot(stage_index=2, stage_time=40.0, elapsed=90),
        ]
        for snapshot in snapshots:
            snapshot.stage_ptr = 7
            snapshot.map_seed = 1234

        bands = scrubber.build_stage_bands(snapshots)

        self.assertEqual([band.label for band in bands], ["Stage 3", "Stage 4"])
        self.assertEqual([(band.start, band.end) for band in bands], [(0, 1), (2, 3)])

    def test_a_recording_without_stage_index_still_gets_bands(self) -> None:
        """Older recordings carry no `stage_index` -- and are not hopeless.

        `885k`, `970k` and `874k` have none, and all three resolve to four
        stages through stage-pointer changes. An earlier version of this
        function gave up whenever `stage_index` was missing and threw those
        bands away for a field the answer does not depend on.
        """
        snapshots = []
        for position, stage_ptr in enumerate((11, 11, 22, 22, 33)):
            snapshot = _snapshot(stage_index=None, elapsed=position * 30)
            snapshot.stage_ptr = stage_ptr
            snapshots.append(snapshot)

        bands = scrubber.build_stage_bands(snapshots)

        self.assertEqual([band.label for band in bands], ["Stage 1", "Stage 2", "Stage 3"])

    def test_a_run_with_no_observed_transition_is_one_band(self) -> None:
        """One band is a claim about the recording, and a true one."""
        snapshots = [_snapshot(stage_index=None), _snapshot(stage_index=None)]

        bands = scrubber.build_stage_bands(snapshots)

        self.assertEqual([band.label for band in bands], ["Stage 1"])


class DifficultyCapTests(unittest.TestCase):
    def test_base_cap_applies_before_the_ghosts_are_out(self) -> None:
        snapshots = [_snapshot(stage_index=1, stage_time=10.0)]
        steps = scrubber.build_cap_steps(snapshots, "Difficulty")
        self.assertEqual([step.value for step in steps], [DIFFICULTY_CAP_BY_STAGE[1][0]])

    def test_cap_drops_two_minutes_past_the_stage_duration(self) -> None:
        past = STAGE_DURATION_SECONDS[1] + GHOSTS_DELAY_SECONDS + 1.0
        snapshots = [
            _snapshot(stage_index=1, stage_time=10.0),
            _snapshot(stage_index=1, stage_time=past),
        ]
        steps = scrubber.build_cap_steps(snapshots, "Difficulty")
        self.assertEqual(
            [step.value for step in steps],
            [DIFFICULTY_CAP_BY_STAGE[1][0], DIFFICULTY_CAP_BY_STAGE[1][1]],
        )

    def test_stage_four_has_no_cap_and_contributes_no_step(self) -> None:
        snapshots = [_snapshot(stage_index=3, stage_time=10.0)]
        self.assertEqual(scrubber.build_cap_steps(snapshots, "Difficulty"), ())

    def test_cap_aware_scale_keeps_series_scale_when_no_cap_steps_exist(self) -> None:
        model = scrubber.build_model(
            [_snapshot(stage_index=3, stage_time=10.0, Difficulty=2.5)],
            series_keys=("Difficulty",),
        )

        self.assertEqual(model.caps("Difficulty"), ())
        self.assertEqual(
            model.series_scale("Difficulty", include_cap=True),
            2.5,
        )

    def test_a_one_snapshot_spike_between_equal_neighbours_is_absorbed(self) -> None:
        """The post-boss stage-timer offset must not paint as a real step.

        After the Graveyard boss the main map's stage timer resumes from an
        offset -- expected behaviour, not a bug -- which drops the elapsed
        timer back under the ghosts threshold for a snapshot or two. Left
        alone that renders as the cap jumping up and instantly back down,
        which the player never experienced.
        """
        past = STAGE_DURATION_SECONDS[2] + GHOSTS_DELAY_SECONDS + 1.0
        snapshots = (
            [_snapshot(stage_index=2, stage_time=past)] * 5
            + [_snapshot(stage_index=2, stage_time=10.0)]
            + [_snapshot(stage_index=2, stage_time=past)] * 5
        )
        steps = scrubber.build_cap_steps(snapshots, "Difficulty")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].value, DIFFICULTY_CAP_BY_STAGE[2][1])
        self.assertEqual((steps[0].start, steps[0].end), (0, 10))

    def test_a_real_stage_change_is_not_absorbed(self) -> None:
        snapshots = (
            [_snapshot(stage_index=0, stage_time=10.0)] * 5
            + [_snapshot(stage_index=1, stage_time=10.0)] * 5
            + [_snapshot(stage_index=0, stage_time=10.0)] * 5
        )
        steps = scrubber.build_cap_steps(snapshots, "Difficulty")
        self.assertEqual(len(steps), 3)

    def test_xp_gain_cap_is_flat_across_the_whole_run(self) -> None:
        snapshots = [_snapshot(stage_index=index % 3) for index in range(6)]
        steps = scrubber.build_cap_steps(snapshots, "XP Gain")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].value, XP_GAIN_CAP)
        self.assertEqual((steps[0].start, steps[0].end), (0, 5))

    def test_a_stat_without_a_cap_gets_no_steps(self) -> None:
        self.assertEqual(scrubber.build_cap_steps([_snapshot()], "Luck"), ())


class SeriesTests(unittest.TestCase):
    def test_powerup_pair_shares_one_axis(self) -> None:
        """PM and PDC are compared against each other, not each to itself.

        Both start at 1.0 and stay within one order of magnitude, which is what
        makes a shared axis honest for them; normalising each to its own
        maximum would draw a weaker PDC as if it had reached the same height.
        """
        snapshots = [
            _snapshot(Powerup_Multiplier=1.0, Powerup_Drop_Chance=1.0),
            _snapshot(Powerup_Multiplier=6.0, Powerup_Drop_Chance=3.0),
        ]
        series = scrubber.build_series(snapshots, ("Powerup Multiplier", "Powerup Drop Chance"))
        self.assertEqual(series["Powerup Multiplier"].scale, 6.0)
        self.assertEqual(series["Powerup Drop Chance"].scale, 6.0)
        self.assertEqual(series["Powerup Drop Chance"].normalised(1), 0.5)

    def test_an_ungrouped_series_scales_to_its_own_maximum(self) -> None:
        snapshots = [_snapshot(Luck=0.0), _snapshot(Luck=25.0)]
        series = scrubber.build_series(snapshots, ("Luck",))["Luck"]
        self.assertEqual(series.scale, 25.0)
        self.assertEqual(series.normalised(1), 1.0)

    def test_a_stat_absent_from_the_recording_is_unavailable_not_zero(self) -> None:
        snapshots = [_snapshot(), _snapshot()]
        series = scrubber.build_series(snapshots, ("Luck",))["Luck"]
        self.assertFalse(series.available)
        self.assertIsNone(series.normalised(0))

    def test_items_series_counts_stacks(self) -> None:
        snapshots = [_snapshot(items=("Anvil x1",)), _snapshot(items=("Anvil x3", "Key x2"))]
        series = scrubber.build_series(snapshots, (scrubber.ITEMS_SERIES,))[scrubber.ITEMS_SERIES]
        self.assertEqual(series.values, (1.0, 5.0))

    def test_kills_series_keeps_a_missing_reading_as_none(self) -> None:
        snapshots = [_snapshot(kills=10), _snapshot(kills=None), _snapshot(kills=30)]
        series = scrubber.build_series(snapshots, (scrubber.KILLS_SERIES,))[scrubber.KILLS_SERIES]
        self.assertEqual(series.values, (10.0, None, 30.0))
        self.assertIsNone(series.normalised(1))


class MarkerTests(unittest.TestCase):
    def test_a_legendary_gain_is_marked(self) -> None:
        snapshots = [_snapshot(items=()), _snapshot(items=("Anvil x1",))]
        markers = scrubber.build_markers(snapshots)
        self.assertEqual([(marker.index, marker.kind) for marker in markers], [(1, "legendary")])

    def test_a_rare_gain_uses_the_purple_timeline_marker(self) -> None:
        snapshots = [_snapshot(items=()), _snapshot(items=("Kevin x1",))]
        markers = scrubber.build_markers(snapshots)
        self.assertEqual(
            [(marker.kind, marker.color) for marker in markers],
            [("rare", "#A78BFA")],
        )

    def test_common_items_are_not_marked(self) -> None:
        """At ~900 snapshots a marker per common pickup is a solid bar."""
        snapshots = [_snapshot(items=()), _snapshot(items=("Moldy Cheese x1",))]
        self.assertEqual(scrubber.build_markers(snapshots), ())

    def test_the_first_snapshot_never_marks_its_starting_inventory(self) -> None:
        snapshots = [_snapshot(items=("Anvil x1",)), _snapshot(items=("Anvil x1",))]
        self.assertEqual(scrubber.build_markers(snapshots), ())

    def test_a_new_banish_is_marked_once(self) -> None:
        snapshots = [
            _snapshot(banishes=()),
            _snapshot(banishes=("Mirror",)),
            _snapshot(banishes=("Mirror",)),
        ]
        markers = scrubber.build_markers(snapshots)
        self.assertEqual([(marker.index, marker.kind) for marker in markers], [(1, "banish")])


class ModelTests(unittest.TestCase):
    def test_an_empty_recording_yields_an_empty_model(self) -> None:
        model = scrubber.build_model(())
        self.assertEqual(model.count, 0)
        self.assertEqual(model.stages, ())
        self.assertIsNone(model.series(scrubber.KILLS_SERIES))

    def test_position_and_index_round_trip(self) -> None:
        model = scrubber.build_model([_snapshot() for _ in range(11)])
        self.assertEqual(model.position(0), 0.0)
        self.assertEqual(model.position(10), 1.0)
        self.assertEqual(model.index_at(0.5), 5)
        self.assertEqual(model.index_at(2.0), 10)
        self.assertEqual(model.index_at(-1.0), 0)

    def test_a_single_snapshot_recording_does_not_divide_by_zero(self) -> None:
        model = scrubber.build_model([_snapshot()])
        self.assertEqual(model.position(0), 0.0)
        self.assertEqual(model.index_at(1.0), 0)

    def test_cap_at_reports_the_step_in_force(self) -> None:
        past = STAGE_DURATION_SECONDS[0] + GHOSTS_DELAY_SECONDS + 1.0
        snapshots = [_snapshot(stage_index=0, stage_time=10.0)] * 5 + [
            _snapshot(stage_index=0, stage_time=past)
        ] * 5
        model = scrubber.build_model(snapshots, series_keys=("Difficulty",))
        self.assertEqual(model.cap_at("Difficulty", 0), DIFFICULTY_CAP_BY_STAGE[0][0])
        self.assertEqual(model.cap_at("Difficulty", 9), DIFFICULTY_CAP_BY_STAGE[0][1])
        self.assertIsNone(model.cap_at("Luck", 0))


if __name__ == "__main__":
    unittest.main()
