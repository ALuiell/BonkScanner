"""Scrubbing the Compare Runs and Recordings timelines.

The three timelines answered every `valueChanged` -- one per pixel of mouse
travel -- with the full render. These cases pin the four mechanisms that
replaced that, each written so it *fails* if the mechanism is removed rather
than merely passing while it is present:

* the split between the caption (immediate) and the render (coalesced);
* the formatted-diff cache, and the two events that must invalidate it;
* the pre-sorted snapshot time index, against the linear scan it replaces;
* the dirty check on the diff cards.

Every throttle here is driven over a fake clock and a fake scheduler, so
"queued, then fired" is an assertion rather than a sleep.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections import formatting
from projections.metric_table import MetricRow, MetricSection, MetricTable
from support.compare_runs import build_compare_runs_tab
from support.player_stats import build_recordings_tab, build_recording_timeline_view
from test_ui_throttle import FakeClock, FakeScheduler
from ui.throttle import UiUpdateThrottle
from ui.tabs.compare_runs import tab as compare_runs_tab
from ui.tabs.compare_runs.tab import SnapshotTimeIndex


class FakeLabel:
    def __init__(self, text: str = "") -> None:
        self.value = text
        self.writes: list[str] = []

    def setText(self, text: str) -> None:
        self.value = text
        self.writes.append(text)

    def text(self) -> str:
        return self.value


class FakeMetricTable:
    """Stands in for `MetricTableView`, which needs real Qt to construct.

    Same shape as `FakeLabel` so the dirty-check assertions read the same way
    for the widget-rendered cards as for the rich-text ones.
    """

    def __init__(self) -> None:
        self.value = None
        self.writes: list[object] = []

    def set_table(self, table) -> None:
        self.value = table
        self.writes.append(table)


def paused_throttle(interval_ms: float = 100.0):
    """A throttle whose window has already opened and never closes on its own."""
    clock = FakeClock()
    scheduler = FakeScheduler()
    return UiUpdateThrottle(interval_ms, clock=clock, schedule=scheduler), scheduler


def snapshot(time_label: str, game_time: float, **extra):
    return SimpleNamespace(
        time_label=time_label,
        game_time_seconds=game_time,
        elapsed_seconds=game_time,
        stats={},
        items=(),
        **extra,
    )


def fake_vod(name: str, times: tuple[float, ...]):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, path=f"/{name}", duration_seconds=times[-1]),
        snapshots=tuple(snapshot(f"{int(t):02d}s", t) for t in times),
    )


class SnapshotTimeIndexTests(unittest.TestCase):
    """Parity with the linear scan, including its tie-breaking."""

    @staticmethod
    def _linear_scan(snapshots, target_time: float) -> int:
        """The pre-optimization implementation, kept here as the oracle."""
        best_index = 0
        best_distance = float("inf")
        for index, snap in enumerate(snapshots):
            snapshot_time = formatting._snapshot_compare_time(snap)
            if snapshot_time is None:
                continue
            distance = abs(float(snapshot_time) - float(target_time))
            if distance < best_distance:
                best_index = index
                best_distance = distance
        return best_index

    def _assert_parity(self, snapshots, targets) -> None:
        index = SnapshotTimeIndex.build(snapshots)
        for target in targets:
            self.assertEqual(
                self._linear_scan(snapshots, target),
                index.nearest(target),
                f"disagreed at target {target}",
            )

    def test_matches_the_linear_scan_across_a_recording(self) -> None:
        snapshots = tuple(snapshot(f"{i:02d}", float(i) * 3.0) for i in range(40))
        self._assert_parity(snapshots, [-5.0, 0.0, 1.4, 1.5, 43.0, 117.0, 500.0])

    def test_a_target_exactly_between_two_snapshots_keeps_the_lower_index(self) -> None:
        """The scan kept the *first* strictly-closer snapshot; so must the bisect."""
        snapshots = (snapshot("a", 10.0), snapshot("b", 20.0))

        self.assertEqual(0, SnapshotTimeIndex.build(snapshots).nearest(15.0))
        self._assert_parity(snapshots, [15.0])

    def test_duplicate_times_resolve_to_the_earliest_snapshot(self) -> None:
        snapshots = (snapshot("a", 5.0), snapshot("b", 9.0), snapshot("c", 9.0))

        self.assertEqual(1, SnapshotTimeIndex.build(snapshots).nearest(9.2))
        self._assert_parity(snapshots, [8.0, 9.0, 9.2])

    def test_untimed_snapshots_use_the_shared_projection_fallback(self) -> None:
        snapshots = (
            SimpleNamespace(game_time_seconds=None, elapsed_seconds=None),
            snapshot("b", 40.0),
        )

        self.assertEqual(1, SnapshotTimeIndex.build(snapshots).nearest(43.0))
        self.assertEqual(0, SnapshotTimeIndex.build(snapshots).nearest(0.0))

    def test_an_empty_recording_answers_zero(self) -> None:
        self.assertEqual(0, SnapshotTimeIndex.build(()).nearest(12.0))

    def test_the_module_level_helper_still_answers(self) -> None:
        """`_nearest_snapshot_index` is the uncached entry point; it stays."""
        snapshots = (snapshot("a", 10.0), snapshot("b", 40.0), snapshot("c", 90.0))

        self.assertEqual(1, compare_runs_tab._nearest_snapshot_index(snapshots, 43.0))


def build_scrubbable_compare_tab(throttle):
    tab = build_compare_runs_tab(diff_throttle=throttle)
    tab._vod_a = fake_vod("Run A", (0.0, 10.0, 20.0, 30.0))
    tab._vod_b = fake_vod("Run B", (0.0, 11.0, 21.0, 31.0))
    tab._index_a = 0
    tab._index_b = 0
    tab._run_a_timeline_label = FakeLabel()
    tab._run_b_timeline_label = FakeLabel()
    tab._run_a_slider = MagicMock()
    tab._run_b_slider = MagicMock()
    tab.refresh_compare_runs_ui = MagicMock()
    return tab


class CompareRunsScrubTests(unittest.TestCase):
    def test_first_slider_step_renders_immediately(self) -> None:
        """A single step must not be deferred; the throttle's leading edge."""
        throttle, _scheduler = paused_throttle()
        tab = build_scrubbable_compare_tab(throttle)

        tab.on_compare_run_slider_changed("a", 2)

        tab.refresh_compare_runs_ui.assert_called_once_with(changed_side="a")

    def test_a_drag_updates_both_captions_but_renders_once(self) -> None:
        throttle, scheduler = paused_throttle()
        tab = build_scrubbable_compare_tab(throttle)

        for value in (1, 2, 3):
            tab.on_compare_run_slider_changed("a", value)

        # Every tick moved the captions -- both sides, because moving one
        # slider time-syncs the other.
        self.assertEqual(
            ["Timeline: 00s - 30s | Selected: 10s",
             "Timeline: 00s - 30s | Selected: 20s",
             "Timeline: 00s - 30s | Selected: 30s"],
            tab._run_a_timeline_label.writes,
        )
        self.assertEqual(3, len(tab._run_b_timeline_label.writes))
        # ...but only the first tick rendered; the other two coalesced into one
        # queued frame.
        self.assertEqual(1, tab.refresh_compare_runs_ui.call_count)
        self.assertEqual(1, len(scheduler.queued))

        scheduler.fire()

        self.assertEqual(2, tab.refresh_compare_runs_ui.call_count)

    def test_the_coalesced_frame_renders_the_snapshot_the_slider_stopped_on(self) -> None:
        throttle, scheduler = paused_throttle()
        tab = build_scrubbable_compare_tab(throttle)
        for value in (1, 2, 3):
            tab.on_compare_run_slider_changed("a", value)
        scheduler.fire()

        self.assertEqual(3, tab._index_a, "the last value the drag passed through")

    def test_a_repeated_value_is_not_work(self) -> None:
        throttle, scheduler = paused_throttle()
        tab = build_scrubbable_compare_tab(throttle)

        tab.on_compare_run_slider_changed("a", 0)

        tab.refresh_compare_runs_ui.assert_not_called()
        self.assertEqual([], tab._run_a_timeline_label.writes)
        self.assertEqual([], scheduler.queued)

    def test_a_load_error_drops_the_queued_frame(self) -> None:
        """The queued frame describes a selection that no longer exists."""
        throttle, scheduler = paused_throttle()
        tab = build_scrubbable_compare_tab(throttle)
        tab._run_a_status_label = FakeLabel()
        tab._run_a_summary_label = FakeLabel()
        tab._run_a_items_view = MagicMock()
        tab._set_compare_runs_diff_cards = MagicMock()
        tab._refresh_compare_runs_item_details_button = MagicMock()
        tab._refresh_compare_runs_selected_labels = MagicMock()
        for value in (1, 2):
            tab.on_compare_run_slider_changed("a", value)
        rendered_before = tab.refresh_compare_runs_ui.call_count

        tab._set_compare_run_error("a", "Could not load recording")
        scheduler.fire()

        self.assertEqual(rendered_before, tab.refresh_compare_runs_ui.call_count)


def build_diffable_compare_tab():
    tab = build_compare_runs_tab()
    tab._vod_a = fake_vod("Run A", (0.0, 10.0))
    tab._vod_b = fake_vod("Run B", (0.0, 11.0))
    tab._index_a = 0
    tab._index_b = 0
    tab._items_enabled = False
    tab._stage_summary_enabled = False
    tab._weapons_enabled = False
    tab._tomes_enabled = False
    tab._chaos_enabled = False
    tab._compare_run_selected_stat_labels = MagicMock(return_value=("Damage",))
    tab._refresh_compare_runs_item_details_button = MagicMock()
    return tab


def patched_formatters():
    return patch.multiple(
        formatting,
        format_compare_runs_overview_compact_diff=MagicMock(return_value="overview"),
        format_compare_runs_stats_diff=MagicMock(return_value="stats"),
        build_compare_runs_items_summary=MagicMock(return_value="items"),
        build_compare_runs_items_table=MagicMock(return_value="items table"),
        format_compare_runs_stage_summary_diff=MagicMock(return_value="stages"),
        build_compare_runs_weapons_table=MagicMock(return_value="weapons"),
        build_compare_runs_tomes_table=MagicMock(return_value="tomes"),
        build_compare_runs_chaos_table=MagicMock(return_value="chaos"),
    )


class CompareRunsDiffCacheTests(unittest.TestCase):
    def test_scrubbing_back_to_a_seen_frame_reformats_nothing(self) -> None:
        tab = build_diffable_compare_tab()
        tab._set_compare_runs_diff_cards = MagicMock()

        with patched_formatters():
            tab._refresh_compare_runs_diff()
            tab._index_a = 1
            tab._refresh_compare_runs_diff()
            tab._index_a = 0
            tab._refresh_compare_runs_diff()  # back to the first frame

            self.assertEqual(
                2,
                formatting.format_compare_runs_overview_compact_diff.call_count,
                "the third refresh must come from the cache",
            )

        # A cache hit still paints, and paints the same thing.
        self.assertEqual(3, tab._set_compare_runs_diff_cards.call_count)
        first, _second, third = tab._set_compare_runs_diff_cards.call_args_list
        self.assertEqual(first, third)

    def test_turning_a_section_on_is_not_a_cache_hit(self) -> None:
        tab = build_diffable_compare_tab()
        tab._set_compare_runs_diff_cards = MagicMock()

        with patched_formatters():
            tab._refresh_compare_runs_diff()
            tab._weapons_enabled = True
            tab._refresh_compare_runs_diff()

            formatting.build_compare_runs_weapons_table.assert_called_once()

        self.assertEqual(
            "weapons",
            tab._set_compare_runs_diff_cards.call_args_list[-1].kwargs["weapons_table"],
        )

    def test_changing_the_selected_stats_is_not_a_cache_hit(self) -> None:
        tab = build_diffable_compare_tab()
        tab._set_compare_runs_diff_cards = MagicMock()

        with patched_formatters():
            tab._refresh_compare_runs_diff()
            tab._compare_run_selected_stat_labels = MagicMock(return_value=("Luck",))
            tab._refresh_compare_runs_diff()

            self.assertEqual(2, formatting.format_compare_runs_stats_diff.call_count)

    def test_loading_a_different_recording_clears_the_cache(self) -> None:
        """Otherwise a recycled `id()` could be read as a hit for another run."""
        tab = build_diffable_compare_tab()
        tab._set_compare_runs_diff_cards = MagicMock()

        with patched_formatters():
            tab._refresh_compare_runs_diff()
            self.assertTrue(tab._diff_cache)

            tab._set_compare_run_vod("a", fake_vod("Run C", (0.0, 10.0)))

            self.assertEqual({}, dict(tab._diff_cache))

    def test_swapping_the_runs_clears_the_cache(self) -> None:
        """A/B is baked into the overview text: 'Run B compared to Run A'."""
        tab = build_diffable_compare_tab()
        tab._set_compare_runs_diff_cards = MagicMock()
        tab.refresh_compare_runs_list = MagicMock()
        tab.refresh_compare_runs_ui = MagicMock()

        with patched_formatters():
            tab._refresh_compare_runs_diff()
            self.assertTrue(tab._diff_cache)

            tab.swap_compare_runs()

            self.assertEqual({}, dict(tab._diff_cache))

    def test_the_cache_is_bounded(self) -> None:
        tab = build_diffable_compare_tab()
        tab._vod_a = fake_vod("Run A", tuple(float(i) for i in range(400)))
        tab._set_compare_runs_diff_cards = MagicMock()

        with patched_formatters():
            for index in range(compare_runs_tab.COMPARE_RUN_DIFF_CACHE_SIZE + 20):
                tab._index_a = index
                tab._refresh_compare_runs_diff()

        self.assertEqual(
            compare_runs_tab.COMPARE_RUN_DIFF_CACHE_SIZE, len(tab._diff_cache)
        )


class CompareRunsStaleDataTests(unittest.TestCase):
    """The cache must never be the reason new data does not appear.

    Two mechanisms here return *previously computed* output -- the diff cache
    and the diff-card dirty check -- and the dirty check sits downstream of the
    cache, so a stale hit would be painted-over twice: once by returning the
    old strings, once by deciding there is nothing to repaint. These cases
    drive the real path a user takes to get newer data in front of them.
    """

    def _built_enough_tab(self):
        tab = build_compare_runs_tab()
        for side in ("a", "b"):
            setattr(tab, f"_run_{side}_status_label", FakeLabel())
            setattr(tab, f"_run_{side}_timeline_label", FakeLabel())
            setattr(tab, f"_run_{side}_summary_label", FakeLabel())
            setattr(tab, f"_run_{side}_slider", MagicMock())
            setattr(tab, f"_run_{side}_items_view", MagicMock())
        tab._diff_overview_label = FakeLabel()
        tab._diff_stats_label = FakeLabel()
        tab._diff_items_label = FakeLabel()
        tab._diff_stage_summary_label = FakeLabel()
        tab._diff_items_table = FakeMetricTable()
        tab._diff_weapons_table = FakeMetricTable()
        tab._diff_tomes_table = FakeMetricTable()
        tab._diff_chaos_table = FakeMetricTable()
        tab._refresh_compare_runs_item_details_button = MagicMock()
        tab.refresh_compare_runs_list = MagicMock()
        tab._refresh_compare_runs_chooser = MagicMock()
        tab._refresh_compare_runs_stats_config = MagicMock()
        return tab

    def test_reloading_a_recording_that_grew_shows_the_new_snapshots(self) -> None:
        """The scenario a live run produces: the file gained snapshots.

        `LoadedVod` is frozen and `load_vod` re-reads the file, so the reload
        yields a *different* object -- which is exactly what the cache key's
        `id(vod)` and the time index key off.
        """
        tab = self._built_enough_tab()
        short_run = fake_vod("Run A", (0.0, 10.0))
        grown_run = fake_vod("Run A", (0.0, 10.0, 20.0, 30.0))
        tab._vod_b = fake_vod("Run B", (0.0, 10.0, 20.0, 30.0))
        tab._index_b = 0

        with patch.object(compare_runs_tab, "load_vod", return_value=short_run):
            tab.load_compare_run("a", "run-a.jsonl")
        self.assertIn("1/2", tab._run_a_status_label.text())
        overview_before = tab._diff_overview_label.text()

        with patch.object(compare_runs_tab, "load_vod", return_value=grown_run):
            tab.load_compare_run("a", "run-a.jsonl")

        self.assertIs(grown_run, tab._vod_a)
        self.assertIn("1/4", tab._run_a_status_label.text(), "the new snapshot count")
        # The cache is repopulated by the refresh that follows the load, so it
        # is not empty -- what matters is that nothing in it still refers to
        # the recording that was replaced.
        self.assertNotIn(
            id(short_run),
            {key[0] for key in tab._diff_cache} | {key[2] for key in tab._diff_cache},
            "a cached diff outlived the recording it was computed from",
        )
        # And the time index followed the new object rather than the old times.
        self.assertEqual(3, tab._compare_run_time_index("a").nearest(30.0))
        self.assertNotEqual([], tab._diff_overview_label.writes)
        self.assertIsNotNone(overview_before)

    def test_a_reload_repaints_even_when_the_diff_text_is_unchanged(self) -> None:
        """The dirty check must not swallow a genuine reload.

        It cannot: it compares the payload, and identical payload means
        identical pixels. Pinned because the check sits downstream of the
        cache, where a wrong answer would be invisible.
        """
        tab = self._built_enough_tab()
        tab._vod_a = fake_vod("Run A", (0.0, 10.0))
        tab._vod_b = fake_vod("Run B", (0.0, 10.0))
        tab._index_a = 0
        tab._index_b = 0
        tab.refresh_compare_runs_ui()
        painted = tab._diff_overview_label.text()

        # A different recording whose overview happens to render identically.
        replacement = fake_vod("Run A", (0.0, 10.0))
        tab._set_compare_run_vod("a", replacement)
        tab.refresh_compare_runs_ui()

        self.assertEqual(painted, tab._diff_overview_label.text())
        self.assertIn(
            id(replacement),
            {key[0] for key in tab._diff_cache},
            "the diff was recomputed for the new recording, not served stale",
        )

    def test_selecting_a_different_recording_invalidates_the_time_index(self) -> None:
        """Otherwise time-sync would snap side B to the previous run's times."""
        tab = self._built_enough_tab()
        tab._vod_a = fake_vod("Run A", (0.0, 10.0, 20.0))
        self.assertEqual(2, tab._compare_run_time_index("a").nearest(20.0))

        tab._set_compare_run_vod("a", fake_vod("Run A", (100.0, 200.0, 300.0)))

        self.assertEqual(0, tab._compare_run_time_index("a").nearest(20.0))


class CompareRunsDiffCardDirtyCheckTests(unittest.TestCase):
    def _cards(self, tab) -> dict[str, object]:
        cards: dict[str, object] = {
            name: FakeLabel()
            for name in (
                "_diff_overview_label",
                "_diff_stats_label",
                "_diff_items_label",
                "_diff_stage_summary_label",
            )
        }
        cards.update(
            {
                name: FakeMetricTable()
                for name in (
                    "_diff_items_table",
                    "_diff_weapons_table",
                    "_diff_tomes_table",
                    "_diff_chaos_table",
                )
            }
        )
        for name, card in cards.items():
            setattr(tab, name, card)
        return cards

    def test_an_unchanged_diff_is_not_rewritten(self) -> None:
        """Consecutive game seconds very often produce an identical diff."""
        tab = build_compare_runs_tab()
        labels = self._cards(tab)

        tab._set_compare_runs_diff_cards("overview", stats_text="stats")
        tab._set_compare_runs_diff_cards("overview", stats_text="stats")

        self.assertEqual(["overview"], labels["_diff_overview_label"].writes)
        self.assertEqual(["stats"], labels["_diff_stats_label"].writes)

    def test_a_changed_diff_is_written(self) -> None:
        tab = build_compare_runs_tab()
        labels = self._cards(tab)

        tab._set_compare_runs_diff_cards("overview", stats_text="stats")
        tab._set_compare_runs_diff_cards("overview", stats_text="other")

        self.assertEqual(["stats", "other"], labels["_diff_stats_label"].writes)

    def test_a_visibility_only_change_is_written(self) -> None:
        """Section visibility is part of the payload, not just the text."""
        tab = build_compare_runs_tab()
        labels = self._cards(tab)

        tab._set_compare_runs_diff_cards("overview", show_weapons=False)
        tab._set_compare_runs_diff_cards("overview", show_weapons=True)

        self.assertEqual(["overview", "overview"], labels["_diff_overview_label"].writes)

    def test_an_unchanged_metric_table_is_not_rewritten(self) -> None:
        """The widget cards go through the same dirty check as the labels.

        `MetricTable` is a frozen dataclass, so an equal-but-not-identical
        table must compare equal here -- otherwise every frame would repaint
        the three most expensive cards.
        """
        tab = build_compare_runs_tab()
        cards = self._cards(tab)
        table = MetricTable(
            sections=(
                MetricSection(
                    headers=("", "A", "B", "Diff"),
                    rows=(MetricRow("Level", "3", "5", "+2"),),
                    title="Sword",
                ),
            )
        )
        rebuilt = MetricTable(
            sections=(
                MetricSection(
                    headers=("", "A", "B", "Diff"),
                    rows=(MetricRow("Level", "3", "5", "+2"),),
                    title="Sword",
                ),
            )
        )

        tab._set_compare_runs_diff_cards("overview", weapons_table=table)
        tab._set_compare_runs_diff_cards("overview", weapons_table=rebuilt)

        self.assertEqual([table], cards["_diff_weapons_table"].writes)


class RecordingsScrubTests(unittest.TestCase):
    def _tab(self, throttle):
        tab = build_recordings_tab(snapshot_throttle=throttle)
        tab._loaded_vod = fake_vod("Run", (0.0, 10.0, 20.0, 30.0))
        tab._snapshot_index = 0
        tab._requested_snapshot_index = 0
        tab._position_label = FakeLabel()
        tab._legend_label = FakeLabel()
        tab.display_loaded_vod_snapshot = MagicMock()
        return tab

    def test_first_slider_step_renders_immediately(self) -> None:
        throttle, _scheduler = paused_throttle()
        tab = self._tab(throttle)

        tab.on_scrub_index_changed(2)

        tab.display_loaded_vod_snapshot.assert_called_once_with(2)

    def test_a_drag_updates_the_readout_but_renders_once(self) -> None:
        """The cheap half of a drag frame is the readout, and only that.

        The scrubber repaints itself from state it already holds; what the
        *tab* must do on every pointer move is write the position line, and
        defer the ~40-widget snapshot render to the throttle.
        """
        throttle, scheduler = paused_throttle()
        tab = self._tab(throttle)

        for value in (1, 2, 3):
            tab.on_scrub_index_changed(value)

        self.assertEqual(
            ["2 / 4  ·  10s", "3 / 4  ·  20s", "4 / 4  ·  30s"],
            tab._position_label.writes,
        )
        self.assertIn("Game</span> <b", tab._legend_label.writes[-1])
        self.assertIn(">00:30</b>", tab._legend_label.writes[-1])
        self.assertEqual([((1,), {})], [
            (call.args, call.kwargs) for call in tab.display_loaded_vod_snapshot.call_args_list
        ])

        scheduler.fire()

        tab.display_loaded_vod_snapshot.assert_called_with(3)

    def test_returning_to_the_painted_snapshot_still_queues_a_frame(self) -> None:
        """The queued frame is for index 3; the slider is back on 0.

        Comparing against the *rendered* index would exit early here and leave
        that stale frame to repaint a snapshot the user scrubbed away from.
        """
        throttle, scheduler = paused_throttle()
        tab = self._tab(throttle)
        tab.on_scrub_index_changed(1)  # renders immediately, index 1
        tab._snapshot_index = 1
        tab.on_scrub_index_changed(3)  # queued
        tab.on_scrub_index_changed(1)  # back to the rendered snapshot

        scheduler.fire()

        tab.display_loaded_vod_snapshot.assert_called_with(1)

    def test_a_repeated_value_is_not_work(self) -> None:
        throttle, scheduler = paused_throttle()
        tab = self._tab(throttle)

        tab.on_scrub_index_changed(0)

        tab.display_loaded_vod_snapshot.assert_not_called()
        self.assertEqual([], tab._position_label.writes)
        self.assertEqual([], scheduler.queued)

    def test_loading_another_recording_drops_the_queued_frame(self) -> None:
        throttle, scheduler = paused_throttle()
        tab = self._tab(throttle)
        tab._status_label = FakeLabel()
        tab._set_vod_loading_state = MagicMock()
        # The load itself fails (no such file) and lands in the clear path,
        # which needs the tab's widgets; the cancel under test is the one in
        # `load_selected_vod`'s prologue, before any of that.
        tab._clear_loaded_vod_selection = MagicMock()
        tab.on_scrub_index_changed(1)
        tab.on_scrub_index_changed(3)  # queued
        rendered_before = tab.display_loaded_vod_snapshot.call_count

        tab.load_selected_vod("does-not-exist.json")
        scheduler.fire()

        self.assertEqual(rendered_before, tab.display_loaded_vod_snapshot.call_count)


class LiveTimelineScrubTests(unittest.TestCase):
    def test_first_slider_step_selects_immediately(self) -> None:
        throttle, _scheduler = paused_throttle()
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("00:10", "00:20", "00:30"),
            selected_index=0,
            throttle=throttle,
        )

        harness.view.handle_slider_value(2)

        self.assertEqual([2], harness.selections)

    def test_a_drag_updates_the_caption_but_selects_once(self) -> None:
        throttle, scheduler = paused_throttle()
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("00:10", "00:20", "00:30", "00:40"),
            selected_index=0,
            throttle=throttle,
        )

        for value in (1, 2, 3):
            harness.view.handle_slider_value(value)

        self.assertEqual([1], harness.selections, "one render for the burst")
        self.assertEqual(
            "Timeline: 00:10 - 00:40 | Selected: 00:40",
            harness.slider_time_label.text,
            "the caption tracked every tick",
        )

        scheduler.fire()

        self.assertEqual([1, 3], harness.selections)

    def test_selecting_the_current_index_is_still_a_no_op(self) -> None:
        throttle, scheduler = paused_throttle()
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("00:10", "00:20"),
            selected_index=1,
            throttle=throttle,
        )

        harness.view.handle_slider_value(1)

        self.assertEqual([], harness.selections)
        self.assertEqual([], scheduler.queued)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
