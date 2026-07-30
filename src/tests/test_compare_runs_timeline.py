from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import src  # noqa: F401

from PySide6.QtWidgets import QApplication, QTabWidget

from projections import scrubber
from projections import formatting
from projections.metric_table import MetricRow, MetricSection, MetricTable
from ui.tabs.compare_runs.tab import CompareRunsTab
from ui.tabs.compare_runs.timeline import (
    AXIS_PROGRESS,
    AXIS_TIME,
    CompareRunsTimeline,
    axis_positions,
    shared_series_scales,
    snapshot_times,
    stage_start_deltas,
)


def _snapshot(at: float, *, stage: int = 0, damage: float = 0.0):
    stat = SimpleNamespace(value=damage, display_value=str(damage))
    return SimpleNamespace(
        elapsed_seconds=at,
        game_time_seconds=at,
        time_label=f"{at:.0f}s",
        stage_index=stage,
        stage_time_seconds=at,
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


def test_shared_scale_is_the_maximum_of_both_runs() -> None:
    a = _vod((0.0, 2.0))
    b = _vod((0.0, 5.0))
    model_a = scrubber.build_model(a.snapshots, series_keys=("Damage",))
    model_b = scrubber.build_model(b.snapshots, series_keys=("Damage",))
    assert shared_series_scales(model_a, model_b, ("Damage",))["Damage"] == 50.0


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
