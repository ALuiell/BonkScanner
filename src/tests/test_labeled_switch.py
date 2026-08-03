"""Interaction checks for the custom-painted :class:`LabeledSwitch`."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.shared import LabeledSwitch


def test_empty_label_switch_accepts_click_on_right_edge_of_painted_track() -> None:
    """The in-game table uses an empty caption and paints the track full-width.

    The inherited ``QCheckBox.hitButton`` only covered the native 14px
    indicator at the left, leaving the right half of the visible track dead.
    """
    app = QApplication.instance() or QApplication([])
    switch = LabeledSwitch("")
    switch.resize(switch.sizeHint())
    switch.show()
    app.processEvents()

    click = QPoint(switch.width() - 2, switch.height() // 2)
    assert switch.hitButton(click)
    QTest.mouseClick(switch, Qt.LeftButton, Qt.NoModifier, click)

    assert switch.isChecked()
