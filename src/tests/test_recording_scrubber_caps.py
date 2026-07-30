from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtWidgets import QApplication

from projections.scrubber import CapStep, ScrubberModel, Series
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


def test_xp_cap_keeps_its_line_without_a_difficulty_percent_caption() -> None:
    app = QApplication.instance() or QApplication([])
    widget = RecordingScrubber()
    widget.resize(500, 150)
    widget.set_slots((("XP Gain",),))
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
