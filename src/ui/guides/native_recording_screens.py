"""Capture short excerpts of the production Recordings tab for the guide."""
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QRect, QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QTabWidget

from app.prepared_recording import prepare_loaded_recording
from app.vod_library import TIMELINE_STANDARD
from core.powerup_history import POWERUPS_SERIES
from projections.scrubber import KILLS_SERIES
from .run_sample import load_run_example
from ui import i18n as l10n
from ui.tabs.player_stats.recordings import RecordingsTab
from ui.timeline_controls import TimelineSeriesSlots


def _settle_layout():
    for _ in range(4):
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)


def capture_recording_screens(app):
    """Render (timeline, compare details, damage sources) without opening a file."""
    example = load_run_example()
    vod = example.vod
    host = QTabWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen)
    host.setAttribute(Qt.WA_ShowWithoutActivating)
    host.setStyleSheet(app.window.styleSheet())
    host.resize(1080, 1000)
    empty_library = SimpleNamespace(index=(), ensure_refresh=lambda: None, state_for=lambda _: None)
    view = RecordingsTab(
        tabview=host, vod_library=empty_library, window=lambda: host,
        vod_recorder=lambda: None, is_active=lambda: False, log=lambda *args, **kw: None,
        timeline_series_slots=TimelineSeriesSlots((("Difficulty",), (KILLS_SERIES,), ("XP Gain",), (POWERUPS_SERIES,))),
    )
    try:
        view._timeline_size_mode = TIMELINE_STANDARD
        view.build()
        view.build_now()
        # Set the guide's illustrative controls without changing saved preferences.
        for key, checkbox in view._cap_checkboxes.items():
            with QSignalBlocker(checkbox):
                checkbox.setChecked(key == "Difficulty")
        view.set_recordings_chooser_expanded(False, guided=False, remember=False)
        view._prepared_recording = prepare_loaded_recording(
            vod, series_keys=view._recording_model_keys(), cap_keys=("Difficulty",),
        )
        view._loaded_vod = vod
        # Show one selected position during a continuously observed Time Stop.
        view._snapshot_index = 300
        view.refresh_loaded_vod_ui(prepared=view._prepared_recording)
        view._set_vod_loading_state(False)
        view._refresh_live_controls()
        # Give the four stage cards the timeline width for this compact crop.
        # This isolated view has no effect on the user's Recordings tab.
        items_group = view._items_section._group
        page_layout = items_group.parentWidget().layout()
        items_column_stretch = page_layout.columnStretch(1)
        items_group.hide()
        page_layout.setColumnStretch(1, 0)
        host.show()
        _settle_layout()

        chart = view._scrubber
        body = chart.parentWidget()
        controls = view._slot_buttons[0]
        top = controls.mapTo(body, controls.rect().topLeft()).y()
        # Include the stage chapters immediately below the selected snapshot's
        # legend, while leaving the rest of the recording page out of the crop.
        stage_card = view._stage_cards[0]
        bottom = stage_card.mapTo(body, stage_card.rect().bottomLeft()).y()
        timeline = body.grab(QRect(chart.x(), top - 2, chart.width(), bottom - top + 5))

        # Compare an earlier and later point in the same real recording.
        page_layout.setColumnStretch(1, items_column_stretch)
        items_group.show()
        view.display_loaded_vod_snapshot(125)
        view.set_vod_compare_start(357)
        _settle_layout()
        details = view._compare_details_group
        empty_note = view._compare_detail_empty_label
        if empty_note.isVisible():
            details.findChild(QScrollArea).setFixedHeight(empty_note.sizeHint().height() + 12)
            _settle_layout()
        comparison = details.grab()

        view.clear_vod_compare_start()
        tabs = view._detail_tabs
        damage_index = next(i for i in range(tabs.count()) if l10n.tab_identity(tabs, i) == "Damage Sources")
        tabs.setCurrentIndex(damage_index)
        view.display_loaded_vod_snapshot(795)
        _settle_layout()
        damage = tabs.grab(QRect(0, 0, tabs.width(), min(208, tabs.height())))
        return timeline, comparison, damage
    finally:
        host.close()
        host.deleteLater()
