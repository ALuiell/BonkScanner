from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import src  # noqa: F401

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QTabWidget,
)

from projections import scrubber
from projections.recording_sort import RECORDING_SORT_NEWEST, RECORDING_SORT_SNAPSHOTS
from projections import formatting
from projections.metric_table import MetricRow, MetricSection, MetricTable
from projections.timeline_axis import build_axis_projection
from ui.compare_overview import CompareRunsAxisView, CompareRunsLuckLootView
from ui.metric_table import CompactMetricCardGridView, MetricTableView
from ui.shared import LabeledSwitch
from ui.tabs.compare_runs.tab import CompareRunsTab
# `AXIS_PROGRESS` and `axis_positions` come from their owner rather than through
# the timeline widget. The widget imported both and used neither: they were a
# re-export this file was the only reader of, so the import survived in `ui/`
# purely to be reached from here.
from projections.timeline_axis import AXIS_PROGRESS, axis_positions
from ui.tabs.compare_runs.timeline import (
    AXIS_TIME,
    CompareRunsTimeline,
    shared_series_scales,
    snapshot_times,
    stage_start_deltas,
)


def _snapshot(
    at: float,
    *,
    stage: int = 0,
    damage: float = 0.0,
    stage_time: float | None = None,
    stage_ptr: int = 1,
):
    stat = SimpleNamespace(value=damage, display_value=str(damage))
    return SimpleNamespace(
        elapsed_seconds=at,
        game_time_seconds=at,
        time_label=f"{at:.0f}s",
        stage_index=stage,
        stage_time_seconds=at if stage_time is None else stage_time,
        stage_ptr=stage_ptr,
        map_seed=1234,
        stats={
            "Damage": stat,
            "Luck": SimpleNamespace(value=damage / 10.0, display_value=str(damage / 10.0)),
            "Difficulty": SimpleNamespace(value=damage / 20.0, display_value=str(damage / 20.0)),
            "Movement Speed": SimpleNamespace(value=100.0 + damage, display_value=f"{100.0 + damage}%"),
        },
        items=(),
        banishes=(),
    )


def _vod(times, *, stages=None):
    stages = stages or [0] * len(times)
    return SimpleNamespace(
        snapshots=tuple(
            _snapshot(at, stage=stage, damage=at * 10.0)
            for at, stage in zip(times, stages)
        )
    )


def test_time_axis_uses_the_longer_recording() -> None:
    short = _vod((0.0, 10.0, 20.0))
    long = _vod((0.0, 20.0, 40.0))
    assert axis_positions(short.snapshots, mode=AXIS_TIME, common_duration=40.0)[-1] == 0.5
    assert axis_positions(long.snapshots, mode=AXIS_TIME, common_duration=40.0)[-1] == 1.0


def test_progress_axis_normalizes_each_recording_independently() -> None:
    assert axis_positions(_vod((0.0, 10.0)).snapshots, mode=AXIS_PROGRESS) == (0.0, 1.0)
    assert axis_positions(
        _vod((0.0, 10.0, 20.0)).snapshots,
        mode=AXIS_PROGRESS,
    ) == (0.0, 0.5, 1.0)


def test_time_projection_is_monotonic_and_uses_index_fallback() -> None:
    snapshots = (
        SimpleNamespace(game_time_seconds=0.0),
        SimpleNamespace(game_time_seconds=20.0),
        SimpleNamespace(game_time_seconds=10.0),
        SimpleNamespace(),
    )
    projection = build_axis_projection(snapshots, mode=AXIS_TIME)

    assert projection.times == (0.0, 20.0, 20.0, 20.0)
    assert projection.positions == (0.0, 1.0, 1.0, 1.0)


def test_time_projection_rejects_non_finite_times() -> None:
    snapshots = (
        SimpleNamespace(game_time_seconds=float("nan"), elapsed_seconds=None),
        SimpleNamespace(game_time_seconds=float("inf"), elapsed_seconds=None),
    )
    projection = build_axis_projection(snapshots, mode=AXIS_TIME)

    assert projection.times == (0.0, 1.0)
    assert projection.positions == (0.0, 1.0)


def test_time_projection_nearest_tie_keeps_the_lower_original_index() -> None:
    projection = build_axis_projection(
        _vod((0.0, 10.0, 20.0)).snapshots,
        mode=AXIS_TIME,
    )

    assert projection.nearest_index(0.25) == 0


def test_time_projection_duplicate_plateau_keeps_the_first_snapshot() -> None:
    projection = build_axis_projection(
        _vod((0.0, 10.0, 10.0, 10.0, 20.0)).snapshots,
        mode=AXIS_TIME,
    )

    assert projection.nearest_index(0.6) == 1


def test_single_snapshot_projection_does_not_divide_by_zero() -> None:
    projection = build_axis_projection(
        _vod((0.0,)).snapshots,
        mode=AXIS_TIME,
    )

    assert projection.positions == (0.0,)
    assert projection.nearest_index(1.0) == 0


def test_shared_scale_is_the_maximum_of_both_runs() -> None:
    a = _vod((0.0, 2.0))
    b = _vod((0.0, 5.0))
    model_a = scrubber.build_model(a.snapshots, series_keys=("Damage",))
    model_b = scrubber.build_model(b.snapshots, series_keys=("Damage",))
    assert shared_series_scales(model_a, model_b, ("Damage",))["Damage"] == 50.0


def test_shared_scale_includes_a_visible_cap() -> None:
    a = _vod((0.0, 2.0))
    b = _vod((0.0, 5.0))
    model_a = scrubber.build_model(a.snapshots, series_keys=("Difficulty",))
    model_b = scrubber.build_model(b.snapshots, series_keys=("Difficulty",))

    scales = shared_series_scales(
        model_a,
        model_b,
        ("Difficulty",),
        cap_keys=("Difficulty",),
    )

    assert scales["Difficulty"] == 5.71


def test_stage_delta_matches_equal_stage_numbers() -> None:
    a = _vod((0.0, 10.0, 20.0), stages=(0, 1, 1))
    b = _vod((0.0, 13.0, 25.0), stages=(0, 1, 1))
    model_a = scrubber.build_model(a.snapshots)
    model_b = scrubber.build_model(b.snapshots)
    assert stage_start_deltas(
        model_a,
        model_b,
        snapshot_times(a.snapshots),
        snapshot_times(b.snapshots),
    )[1] == 3.0


def test_structured_stats_are_flat_and_stage_table_has_required_metrics() -> None:
    a = _vod((0.0, 10.0), stages=(0, 0))
    b = _vod((0.0, 12.0), stages=(0, 0))
    stats = formatting.build_compare_runs_stats_table(
        a.snapshots[-1],
        b.snapshots[-1],
        stat_labels=("Damage",),
    )
    assert len(stats.sections) == 1
    assert stats.sections[0].title == ""
    assert [row.label for row in stats.sections[0].rows] == ["Damage"]

    stages = formatting.build_compare_runs_stages_table(a, 1, b, 1)
    assert [row.label for row in stages.sections[0].rows] == [
        "Time",
        "Kills",
        "Chests",
        "Items",
    ]

    first = _snapshot(0.0, stage=0)
    second = _snapshot(10.0, stage=0)
    second.items = ("Wrench x1",)
    item_vod = SimpleNamespace(snapshots=(first, second))
    item_stages = formatting.build_compare_runs_stages_table(
        item_vod,
        1,
        item_vod,
        1,
    )
    items_row = next(
        row for row in item_stages.sections[0].rows if row.label == "Items"
    )
    assert items_row.value_a == "1"
    assert items_row.delta == "+0"


def test_snapshot_comparison_is_an_aligned_a_b_delta_table() -> None:
    snapshot_a = SimpleNamespace(
        elapsed_seconds=110,
        time_label="01:50",
        game_time_seconds=795,
        mob_kills=20_679,
        player_level=274,
        items=("Key x34",),
    )
    snapshot_b = SimpleNamespace(
        elapsed_seconds=30,
        time_label="00:30",
        game_time_seconds=0,
        mob_kills=None,
        player_level=0,
        items=(),
    )
    vod_a = SimpleNamespace(snapshots=(snapshot_a,) * 605)
    vod_b = SimpleNamespace(snapshots=(snapshot_b,) * 713)

    table = formatting.build_compare_runs_snapshot_table(
        vod_a,
        0,
        snapshot_a,
        vod_b,
        0,
        snapshot_b,
    )

    section = table.sections[0]
    assert section.headers == ("Value", "A", "B", "Delta")
    assert [row.label for row in section.rows] == [
        "Snapshot",
        "Record",
        "In-game",
        "Kills",
        "Level",
        "Items",
    ]
    # `A - B`: run A recorded 80 seconds later and holds 34 more items.
    assert section.rows[1].delta == "+01:20"
    assert section.rows[-1].delta == "+34"


def test_stage_table_keeps_boss_room_as_stage_four() -> None:
    snapshots = (
        _snapshot(0.0, stage=2, stage_time=300.0, stage_ptr=7),
        _snapshot(30.0, stage=2, stage_time=400.0, stage_ptr=7),
        _snapshot(60.0, stage=2, stage_time=1.0, stage_ptr=7),
        _snapshot(90.0, stage=2, stage_time=40.0, stage_ptr=7),
    )
    for snapshot in snapshots:
        snapshot.chests_opened_by_stage = {3: 18, 4: 2}
    vod = SimpleNamespace(snapshots=snapshots)

    table = formatting.build_compare_runs_stages_table(vod, 3, vod, 3)

    assert [section.title for section in table.sections] == ["Stage 3", "Stage 4"]
    stage_four_chests = next(
        row for row in table.sections[1].rows if row.label == "Chests"
    )
    assert stage_four_chests.value_a == "2"


def test_stage_cards_use_a_pooled_two_column_grid() -> None:
    app = QApplication.instance() or QApplication([])
    view = CompactMetricCardGridView(
        section_capacity=4,
        metric_capacity=4,
        metrics_per_row=4,
    )
    view.resize(1200, 400)
    view.show()
    app.processEvents()

    rows = (
        MetricRow("Time", "03:41", "03:29", "-12s"),
        MetricRow("Kills", "41,200", "42,000", "+800"),
        MetricRow("Chests", "2", "2", "+0"),
        MetricRow("Items", "3", "3", "+0"),
    )
    table = MetricTable(
        sections=tuple(
            MetricSection(
                headers=("Metric", "Run A", "Run B", "Delta"),
                rows=rows,
                title=f"Stage {stage}",
            )
            for stage in range(1, 5)
        )
    )
    pooled_cards = tuple(view._cards)
    pooled_cells = tuple(tuple(card._cells) for card in pooled_cards)

    view.set_table(table)
    app.processEvents()

    assert view.column_count == 2
    assert [
        view._grid.getItemPosition(view._grid.indexOf(card))[:2]
        for card in view._cards
    ] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert tuple(view._cards) == pooled_cards
    assert tuple(tuple(card._cells) for card in view._cards) == pooled_cells
    assert "#FB7185" in view._cards[0]._cells[0]._delta.styleSheet()

    updated_rows = (MetricRow("Time", "24:54", "24:43", "+11s"),) + rows[1:]
    view.set_table(
        MetricTable(
            sections=tuple(
                MetricSection(
                    headers=("Metric", "Run A", "Run B", "Delta"),
                    rows=updated_rows,
                    title=f"Stage {stage}",
                )
                for stage in range(1, 5)
            )
        )
    )
    assert tuple(view._cards) == pooled_cards
    assert tuple(tuple(card._cells) for card in view._cards) == pooled_cells
    assert "#22C55E" in view._cards[0]._cells[0]._delta.styleSheet()

    view.resize(700, 400)
    app.processEvents()
    assert view.column_count == 1
    view.close()


def test_playhead_updates_do_not_rebuild_static_timeline() -> None:
    app = QApplication.instance() or QApplication([])
    timeline = CompareRunsTimeline()
    timeline.resize(1200, 214)
    times = tuple(float(index) for index in range(700))
    timeline.set_runs(
        _vod(times),
        _vod(times),
        series_keys=("Damage", "Luck", "Difficulty", "Movement Speed"),
    )
    timeline.show()
    app.processEvents()
    rebuilds = timeline.static_rebuilds

    started = time.perf_counter()
    for index in range(240):
        timeline.set_position(index / 239.0)
    elapsed = time.perf_counter() - started
    app.processEvents()

    assert timeline.static_rebuilds == rebuilds
    assert elapsed / 240.0 < 0.008
    timeline.close()


def test_compact_timeline_reduces_height_and_can_be_restored() -> None:
    app = QApplication.instance() or QApplication([])
    timeline = CompareRunsTimeline()
    normal_height = timeline.height()

    timeline.set_compact(True)
    app.processEvents()

    assert timeline.compact is True
    assert timeline.height() < normal_height
    assert timeline.minimumHeight() == timeline.maximumHeight() == timeline.height()

    timeline.set_compact(False)
    app.processEvents()

    assert timeline.compact is False
    assert timeline.height() == normal_height
    timeline.close()


def test_workspace_exposes_all_full_width_tabs_and_renders_lazily() -> None:
    app = QApplication.instance() or QApplication([])

    class Library:
        index = ()

        def ensure_refresh(self):
            return None

    tabs = QTabWidget()
    compare = CompareRunsTab(
        tabview=tabs,
        vod_library=Library(),
        is_active=lambda: True,
    )
    compare.build()
    tabs.resize(1400, 900)
    tabs.show()
    app.processEvents()
    assert [compare._detail_tabs.tabText(index) for index in range(7)] == [
        "Overview",
        "Stats",
        "Stages",
        "Items",
        "Weapons",
        "Tomes",
        "Chaos",
    ]
    assert compare._timeline.objectName() == "CompareRunsTimeline"
    assert all(
        button.property("timelineSlot") is True
        and not button.text().startswith("Series ")
        for button in compare._series_slot_buttons
    )
    assert [
        action.text()
        for action in compare._series_slot_buttons[0].menu().actions()
        if action.menu() is not None
    ] == ["Dmg", "Effects", "Run", "Rewards & spawns"]
    assert compare._compact_timeline_btn.property("timelineCompact") is True
    assert not hasattr(compare, "_axis_time_btn")
    assert not hasattr(compare, "_axis_progress_btn")
    assert compare._timeline.axis_mode == AXIS_TIME
    assert compare._timeline_position_label.property("timelinePosition") is True
    # Overview is the axis and the loot block now; the snapshot table it used to
    # carry said what the plaques and the legend above it already said.
    assert isinstance(compare._axis_view, CompareRunsAxisView)
    assert isinstance(compare._luck_loot_view, CompareRunsLuckLootView)
    timeline_card = compare._timeline.parentWidget()
    slot_center_y = compare._series_slot_buttons[0].mapTo(
        timeline_card, QPoint(0, compare._series_slot_buttons[0].height() // 2)
    ).y()
    position_center_y = compare._timeline_position_label.mapTo(
        timeline_card, QPoint(0, compare._timeline_position_label.height() // 2)
    ).y()
    compact_center_y = compare._compact_timeline_btn.mapTo(
        timeline_card, QPoint(0, compare._compact_timeline_btn.height() // 2)
    ).y()
    timeline_top = compare._timeline.mapTo(timeline_card, QPoint()).y()
    assert slot_center_y < timeline_top
    # One control row above the track: title, series pickers, the compact
    # switch and the readout. A second row holding only the word TIMELINE was
    # height spent on nothing.
    assert isinstance(compare._compact_timeline_btn, LabeledSwitch)
    assert abs(slot_center_y - compact_center_y) <= 2
    assert abs(slot_center_y - position_center_y) <= 2
    slot_bottom = compare._series_slot_buttons[0].mapTo(
        timeline_card, QPoint(0, compare._series_slot_buttons[0].height())
    ).y()
    painted_track_top = timeline_top + int(compare._timeline._track_rect().top())
    assert painted_track_top - slot_bottom <= 10
    assert isinstance(compare._diff_stages_table, CompactMetricCardGridView)
    assert len(compare._diff_stages_table._cards) == 4
    assert isinstance(compare._stats_table, MetricTableView)
    assert isinstance(compare._diff_items_table, MetricTableView)
    assert isinstance(compare._diff_weapons_table, MetricTableView)

    table = MetricTable(
        sections=(
            MetricSection(
                headers=("Weapon stat", "Run A", "Run B", "Delta"),
                rows=(MetricRow("Dmg", "10", "12", "+2"),),
                title="Sword",
            ),
        )
    )
    compare._diff_weapons_table.set_table = MagicMock()
    compare._set_compare_runs_diff_cards("overview", weapons_table=table)
    compare._diff_weapons_table.set_table.assert_not_called()
    compare._detail_tabs.setCurrentIndex(4)
    app.processEvents()
    compare._diff_weapons_table.set_table.assert_called_once_with(table)
    tabs.close()


def test_timeline_footer_shows_visible_series_a_b_and_delta() -> None:
    app = QApplication.instance() or QApplication([])

    class Library:
        index = ()

        def ensure_refresh(self):
            return None

    tabs = QTabWidget()
    compare = CompareRunsTab(
        tabview=tabs,
        vod_library=Library(),
        is_active=lambda: True,
    )
    compare.build()
    # The tab's contents wait for a show; this test drives the widgets without
    # one, so it asks for them. See `LazyPage`.
    compare.build_now()
    compare._vod_a = _vod((1.0,))
    compare._vod_b = _vod((2.0,))
    compare._index_a = 0
    compare._index_b = 0
    compare._series_slots = (("Damage",), (), (), ())

    compare._refresh_compare_timeline_legend()
    app.processEvents()

    assert compare._timeline_legend.keys == ("Damage",)
    game = compare._timeline_legend._game
    assert game._name.text() == "Game"
    assert game._value_a.text() == "A 00:01"
    assert game._arrow.text() == "→"
    assert game._value_b.text() == "B 00:02"
    assert game._delta.text() == "Δ -00:01"
    item = compare._timeline_legend._items[0]
    assert item._name.text() == "DMG"
    assert item._value_a.text() == "A 10.0"
    assert item._arrow.text() == "→"
    assert item._value_b.text() == "B 20.0"
    # `A - B`, the same direction every card below the timeline uses.
    assert item._delta.text() == "Δ -10"
    tabs.close()


def test_caps_are_drawn_without_plotting_their_curve() -> None:
    """The whole point of the checkboxes.

    A cap is a rule of the game, not a reading of the run, so asking to see the
    Difficulty ceiling must not cost one of the four series slots. It used to:
    `_paint_caps` iterated the *plotted* keys, so the only way to see a cap was
    to plot its stat.
    """
    app = QApplication.instance() or QApplication([])
    timeline = CompareRunsTimeline()
    a = _vod((0.0, 60.0, 120.0), stages=(0, 1, 2))
    b = _vod((0.0, 70.0, 140.0), stages=(0, 1, 2))
    # A cap is only drawable where its stat was recorded, so the fixture has to
    # carry XP Gain for the XP cap to have anywhere to sit.
    for vod in (a, b):
        for snapshot in vod.snapshots:
            snapshot.stats["XP Gain"] = SimpleNamespace(value=3.0, display_value="3")

    timeline.set_runs(a, b, series_keys=(), cap_keys=("Difficulty", "XP Gain"))

    assert timeline._series_keys == (), "no curve was asked for"
    assert timeline._cap_keys == ("Difficulty", "XP Gain")
    # What the painter will iterate. Asserting `_cap_keys` alone does not catch
    # a `_paint_caps` that has gone back to following the plotted series.
    assert timeline.drawable_cap_keys(timeline._lane_a) == ("Difficulty", "XP Gain")
    # The cap line needs its stat's scale to know what height to sit at, so the
    # model has to carry the series even though nothing plots it.
    assert timeline._shared_scales.get("Difficulty", 0.0) > 0.0
    assert timeline._lane_a.model.caps("Difficulty")
    assert timeline._lane_a.model.caps("XP Gain")

    # Switching them off rebuilds: `_cap_keys` is the gate `_paint_caps` reads,
    # and with nothing plotted and nothing capped there is no scale left to
    # compute. (The model keeps its cap steps either way -- `build_model`
    # always derives them, which costs nothing and is not what gates drawing.)
    timeline.set_cap_keys(())
    assert timeline._cap_keys == ()
    assert timeline._shared_scales == {}
    app.processEvents()


def test_the_cap_checkboxes_drive_the_timeline() -> None:
    app = QApplication.instance() or QApplication([])

    class Library:
        index = ()

        def ensure_refresh(self):
            return None

    tabs = QTabWidget()
    compare = CompareRunsTab(tabview=tabs, vod_library=Library(), is_active=lambda: True)
    compare.build()
    compare.build_now()  # no show in this test; see `LazyPage`
    compare._vod_a = _vod((0.0, 60.0), stages=(0, 1))
    compare._vod_b = _vod((0.0, 70.0), stages=(0, 1))

    compare._cap_checkboxes["Difficulty"].setChecked(True)
    compare._cap_checkboxes["XP Gain"].setChecked(False)
    compare._refresh_compare_runs_timeline_model()
    app.processEvents()

    assert compare._timeline._cap_keys == ("Difficulty",)

    compare._cap_checkboxes["XP Gain"].setChecked(True)
    app.processEvents()
    assert compare._timeline._cap_keys == ("Difficulty", "XP Gain")

    compare._cap_checkboxes["Difficulty"].setChecked(False)
    compare._cap_checkboxes["XP Gain"].setChecked(False)
    app.processEvents()
    tabs.close()


def test_recording_chooser_replaces_workspace_and_uses_available_height() -> None:
    app = QApplication.instance() or QApplication([])

    class Library:
        # `created_at` is what the library sorts by and `created_label` is what
        # the row prints; real `VodMetadata` carries both, so the double does
        # too. Note the index is deliberately *not* in newest-first order --
        # the chooser sorts it rather than trusting whatever order it is handed.
        index = (
            SimpleNamespace(
                path="run-a.json",
                name="950k",
                created_at="2026-07-14T20:58:58",
                created_label="2026-07-14 20:58:58",
                snapshot_count=713,
                duration_seconds=9467,
            ),
            SimpleNamespace(
                path="run-b.json",
                name="Run 2026-07-18 16:33:12",
                created_at="2026-07-18T16:33:12",
                created_label="2026-07-18 16:33:12",
                snapshot_count=141,
                duration_seconds=1964,
            ),
        )

        def ensure_refresh(self):
            return None

    tabs = QTabWidget()
    compare = CompareRunsTab(
        tabview=tabs,
        vod_library=Library(),
        is_active=lambda: True,
    )
    compare.build()
    tabs.resize(1400, 900)
    tabs.show()
    app.processEvents()

    assert compare._workspace_stack.currentWidget() is compare._workspace_page

    compare._run_a_change_btn.click()
    app.processEvents()

    assert compare._workspace_stack.currentWidget() is compare._chooser_page
    assert compare._chooser_group.isVisible()
    assert compare._run_a_change_btn.text() == "Done"
    assert compare._run_b_change_btn.text() == "Done"
    assert compare._run_a_list_frame.height() > 280
    assert (
        compare._run_a_list_frame.sizePolicy().verticalPolicy()
        == QSizePolicy.Policy.Expanding
    )
    assert (
        compare._run_b_list_frame.sizePolicy().verticalPolicy()
        == QSizePolicy.Policy.Expanding
    )
    # Set the order rather than trusting the saved one: the mode persists to
    # the shared config, so a test that assumed the default would pass or fail
    # depending on what the developer running it last clicked in the app.
    compare._sort_combo.setCurrentIndex(
        compare._sort_combo.findData(RECORDING_SORT_NEWEST)
    )
    app.processEvents()

    # Newest first, so the 07-18 recording leads even though the library
    # handed the 07-14 one over first.
    first_item = compare._run_a_list_frame.item(0)
    first_row = compare._run_a_list_frame.itemWidget(first_item)
    assert first_row is not None
    assert first_row.objectName() == "RecordingRow"
    assert first_row.findChild(QLabel, "RecordingRowName").text() == "Run 2026-07-18 16:33:12"

    second_row = compare._run_a_list_frame.itemWidget(compare._run_a_list_frame.item(1))
    assert second_row.findChild(QLabel, "RecordingRowName").text() == "950k"
    assert (
        second_row.findChild(QLabel, "RecordingRowMeta").text()
        == "2026-07-14 20:58:58  ·  713 snapshots  ·  02:37:47"
    )
    assert second_row.findChild(QProgressBar, "RecordingRowBar").value() == 1000

    # Switching the order repaints. The list signature has to carry the mode,
    # or this is a no-op with nothing to say why.
    compare._sort_combo.setCurrentIndex(
        compare._sort_combo.findData(RECORDING_SORT_SNAPSHOTS)
    )
    app.processEvents()
    reordered = compare._run_a_list_frame.itemWidget(compare._run_a_list_frame.item(0))
    assert reordered.findChild(QLabel, "RecordingRowName").text() == "950k"

    compare._run_a_change_btn.click()
    app.processEvents()
    assert compare._workspace_stack.currentWidget() is compare._workspace_page
    assert compare._run_a_change_btn.text() == "Change"
    assert compare._run_b_change_btn.text() == "Change"
    tabs.close()
