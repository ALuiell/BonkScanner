"""Capture the production Live Stats tab for the native guide.

The host is isolated from the running Scanner: it uses a recorded snapshot,
inert callbacks and no runtime polling or persistence.
"""
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QRect, Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from .run_sample import load_run_example
from ui import formatting
from ui.tabs.player_stats.live_stats import LiveStatsTab
from ui.tabs.player_stats.summary_cards import set_chests_card_values, set_loot_rarity_card_values


def capture_live_screens(app):
    """Return (Stats, Loot) pixmaps of the real tab populated from a recording.

    ``app`` is the running MegabonkApp, whose window supplies the same
    stylesheet as the production interface. No live tab state is modified.
    """
    qt = QApplication.instance()
    if qt is None:
        raise RuntimeError("A QApplication is required to capture Live Stats")
    example = load_run_example()
    snapshot = example.live_snapshot
    host = QTabWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen)
    host.setAttribute(Qt.WA_ShowWithoutActivating)
    host.setStyleSheet(app.window.styleSheet())
    host.resize(1250, 1050)
    tracker = SimpleNamespace()
    view = LiveStatsTab(
        tabview=host,
        live_run_tracker=lambda: tracker,
        vod_recorder=lambda: SimpleNamespace(is_recording=False),
        vod_snapshots=lambda: (snapshot,),
        selected_snapshot_index=lambda: None,
        recording_waiting_mode=lambda: None,
        ensure_live_snapshot_store=lambda: None,
        is_recording_armed=lambda: False,
        on_toggle_recording=lambda: None,
        on_snapshot_selected=lambda *args, **kwargs: None,
    ).build()
    # Force the compact guide view without saving a user preference.
    view._stats_expanded_toggle.toggled.disconnect(view._save_stats_expanded_preference)
    view._stats_expanded_toggle.setChecked(False)
    view.display_player_stats_snapshot(snapshot)
    set_chests_card_values(
        view._chests_card_values,
        formatting.chests_card_values(
            snapshot.chests_opened_by_stage, snapshot.chests_total_by_stage,
            snapshot.chests_opened, snapshot.chests_total, snapshot.paid_chests,
            snapshot.key_procs, snapshot.free_chests, snapshot.keys_count,
            snapshot.expected_key_procs,
        ),
    )
    luck = snapshot.stats.get("Luck")
    loot = SimpleNamespace(
        available=snapshot.loot_actual is not None and snapshot.loot_expected is not None,
        actual=snapshot.loot_actual or {}, expected=snapshot.loot_expected or {},
    )
    set_loot_rarity_card_values(view._loot_rarity_card_values, getattr(luck, "value", None), loot)
    try:
        host.show()
        for _ in range(4):
            qt.processEvents(QEventLoop.ExcludeUserInputEvents)
        tabs = view._detail_tabs
        stats = tabs.grab(QRect(0, 0, tabs.width(), 240))
        tabs.setCurrentIndex(1)
        for _ in range(4):
            qt.processEvents(QEventLoop.ExcludeUserInputEvents)
        loot_pixmap = tabs.grab(QRect(0, 0, tabs.width(), 260))
        return stats, loot_pixmap
    finally:
        host.close()
        host.deleteLater()
