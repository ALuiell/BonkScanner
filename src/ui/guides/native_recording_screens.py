"""Capture short excerpts of the production Recordings tab for the guide."""
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QRect, Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from app.prepared_recording import prepare_loaded_recording
from app.vod_library import TIMELINE_EXPANDED
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
    snapshots = example.snapshots
    vod = example.vod
    host = QTabWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen)
    host.setAttribute(Qt.WA_ShowWithoutActivating)
    host.setStyleSheet(app.window.styleSheet())
    host.resize(940, 1000)
    empty_library = SimpleNamespace(index=(), ensure_refresh=lambda: None, state_for=lambda _: None)
    view = RecordingsTab(
        tabview=host, vod_library=empty_library, window=lambda: host,
        vod_recorder=lambda: None, is_active=lambda: False, log=lambda *args, **kw: None,
        timeline_series_slots=TimelineSeriesSlots((("Difficulty",), (KILLS_SERIES,), ("XP Gain",), ())),
    )
    try:
        view._timeline_size_mode = TIMELINE_EXPANDED
        view.build()
        view.build_now()
        view.set_recordings_chooser_expanded(False, guided=False, remember=False)
        view._prepared_recording = prepare_loaded_recording(vod, series_keys=view._recording_model_keys())
        view._loaded_vod = vod
        view._snapshot_index = 125
        view._compare_start_index = 357
        view.refresh_loaded_vod_ui(prepared=view._prepared_recording)
        view._set_vod_loading_state(False)
        view._refresh_live_controls()
        view._legend_meta_label.hide()
        host.show()
        _settle_layout()

        chart = view._scrubber
        body = chart.parentWidget()
        controls = view._slot_buttons[0]
        top = controls.mapTo(body, controls.rect().topLeft()).y()
        legend = view._legend_label
        bottom = legend.mapTo(body, legend.rect().bottomLeft()).y()
        timeline = body.grab(QRect(chart.x(), top - 2, chart.width(), bottom - top + 5))
        comparison = view._compare_details_group.grab()

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
