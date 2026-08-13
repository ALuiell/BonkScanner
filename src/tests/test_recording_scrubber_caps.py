from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from projections.scrubber import CapStep, ScrubberModel, Series
from projections.timeline_axis import AXIS_TIME, TimelineAxisProjection
from ui.tabs.player_stats.recording_scrubber import RecordingScrubber


def _series(key: str, values: tuple[float, ...], *, scale: float) -> Series:
    return Series(
        key=key,
        label=key,
        color="#F0787E",
        values=values,
        scale=scale,
        available=True,
    )


def test_difficulty_caps_carry_percent_labels_without_over_cap_geometry() -> None:
    app = QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(500, 150)
    widget.set_slots((("Difficulty",),))
    # Caps are opt-in now: the ceiling is asked for separately from the curve.
    widget.set_cap_keys(("Difficulty",))
    widget.set_model(
        ScrubberModel(
            count=4,
            _series={"Difficulty": _series("Difficulty", (1.0, 4.0, 6.0, 7.0), scale=7.0)},
            _caps={"Difficulty": (CapStep(0, 3, 5.71),)},
        )
    )
    widget._ensure_render_cache()

    assert len(widget._cached_caps) == 1
    x0, x1, _y, _colour, label = widget._cached_caps[0]
    assert x1 > x0
    assert label == "571%"
    # Rendering the cached cap now paints only the dashed line and its label;
    # the former "first crossing -> right edge" coordinate no longer exists.
    widget.show()
    app.processEvents()
    assert not widget.grab().isNull()


def test_visible_cap_expands_scale_instead_of_collapsing_onto_curve() -> None:
    QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(500, 150)
    widget.set_slots((("Difficulty",),))
    widget.set_cap_keys(("Difficulty",))
    widget.set_model(
        ScrubberModel(
            count=2,
            _series={
                "Difficulty": _series("Difficulty", (1.0, 1.396), scale=1.396)
            },
            _caps={"Difficulty": (CapStep(0, 1, 5.71),)},
        )
    )
    widget._ensure_render_cache()

    cap_y = widget._cached_caps[0][2]
    curve = widget._cached_paths[0][0]
    curve_end_y = curve.elementAt(curve.elementCount() - 1).y
    assert curve_end_y > cap_y
    assert widget._model.series_scale("Difficulty", include_cap=True) == 5.71


def test_xp_cap_keeps_its_line_without_a_difficulty_percent_caption() -> None:
    app = QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(500, 150)
    widget.set_slots((("XP Gain",),))
    widget.set_cap_keys(("XP Gain",))
    widget.set_model(
        ScrubberModel(
            count=4,
            _series={"XP Gain": _series("XP Gain", (1.0, 2.0, 3.0, 4.0), scale=4.0)},
            _caps={"XP Gain": (CapStep(0, 3, 3.0),)},
        )
    )
    widget._ensure_render_cache()

    assert widget._cached_caps[0][4] is None
    app.processEvents()


def test_b_key_pins_compare_point_b_at_the_current_playhead() -> None:
    QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.set_model(ScrubberModel(count=4))
    widget.set_index(2)

    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.NoModifier))

    assert widget.index() == 2
    assert widget.pin() == 2


def test_shift_drag_moves_compare_point_b_until_release() -> None:
    app = QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(500, 150)
    widget.set_model(ScrubberModel(count=5))
    widget.set_index(2)
    widget.show()
    app.processEvents()

    QTest.mousePress(widget, Qt.LeftButton, Qt.ShiftModifier, QPoint(100, 75))
    first_pin = widget.pin()
    QTest.mouseMove(widget, QPoint(400, 75))
    moved_pin = widget.pin()
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(400, 75))
    QTest.mouseMove(widget, QPoint(200, 75))

    assert first_pin is not None
    assert moved_pin is not None
    assert moved_pin > first_pin
    assert widget.pin() == moved_pin
    assert widget.index() == 2


def test_playhead_updates_do_not_rebuild_recording_static_layer() -> None:
    app = QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(900, 150)
    count = 700
    positions = tuple(index / (count - 1) for index in range(count))
    widget.set_model(
        ScrubberModel(count=count),
        projection=TimelineAxisProjection(
            tuple(float(index) for index in range(count)),
            positions,
            float(count - 1),
            AXIS_TIME,
        ),
    )
    widget.show()
    app.processEvents()
    rebuilds = widget.static_rebuilds

    for index in range(0, count, 7):
        widget.set_index(index)
        widget.repaint()

    assert widget.static_rebuilds == rebuilds
    widget.close()


def test_a_ceiling_is_drawn_without_plotting_its_curve() -> None:
    """The point of the checkbox: seeing a cap must not cost a series slot.

    `_build_cap_geometry` used to iterate the *selected* series, so the only
    way to see the Difficulty ceiling was to spend one of four slots on
    Difficulty. The two are separate questions and now have separate controls.
    """
    QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(500, 150)
    widget.set_slots(((),))
    widget.set_cap_keys(("Difficulty",))
    widget.set_model(
        ScrubberModel(
            count=4,
            _series={"Difficulty": _series("Difficulty", (1.0, 4.0, 6.0, 7.0), scale=7.0)},
            _caps={"Difficulty": (CapStep(0, 3, 5.71),)},
        )
    )
    widget._ensure_render_cache()

    assert widget.series_keys == (), "no curve was asked for"
    assert widget.drawable_cap_keys() == ("Difficulty",)
    assert len(widget._cached_caps) == 1

    # And the model has to carry the series the cap needs a scale from, even
    # though no slot asked for it.
    assert widget.model_keys == ("Difficulty",)


def test_an_unchecked_ceiling_is_not_drawn_even_when_its_curve_is() -> None:
    QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(500, 150)
    widget.set_slots((("Difficulty",),))
    widget.set_model(
        ScrubberModel(
            count=4,
            _series={"Difficulty": _series("Difficulty", (1.0, 4.0, 6.0, 7.0), scale=7.0)},
            _caps={"Difficulty": (CapStep(0, 3, 5.71),)},
        )
    )
    widget._ensure_render_cache()

    assert widget.drawable_cap_keys() == ()
    assert widget._cached_caps == []
