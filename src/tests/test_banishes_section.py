from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from ui.shared import FlowLayout
from ui.tabs.player_stats.items_section import BanishesSectionView


def test_banishes_are_rarity_chips_and_empty_state_is_plain_text() -> None:
    app = QApplication.instance() or QApplication([])
    label = QLabel("No banishes yet")
    chips_container = QWidget()
    FlowLayout(chips_container, margin=0, spacing=5)
    view = BanishesSectionView(label=label, chips_container=chips_container)

    view.update(("Big Bonk", "Beefy Ring", "Beer", "Key", "Golden Tome"))
    app.processEvents()

    assert label.isHidden()
    assert not chips_container.isHidden()
    assert [
        (chip.text(), chip.objectName())
        for chip in chips_container.findChildren(QLabel)
    ] == [
        ("Big Bonk", "tagLegendary"),
        ("Beefy Ring", "tagRare"),
        ("Beer", "tagUncommon"),
        ("Key", "tagCommon"),
        ("Golden Tome", "tagNeutral"),
    ]

    view.update(())
    app.processEvents()

    assert not label.isHidden()
    assert label.text() == "No banishes yet"
    assert chips_container.isHidden()
    assert chips_container.layout().count() == 0
