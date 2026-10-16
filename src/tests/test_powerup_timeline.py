"""Exercise actual Qt viewers in an isolated process (no desktop input)."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

import src  # noqa: F401


QT_SCENARIO = r'''
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import src
from pathlib import Path
from dataclasses import replace
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtWidgets import QApplication, QTabWidget, QLabel, QWidget
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter
from app import config
from app.active_recording_feed import ActiveRecordingFeed
from app.prepared_recording import prepare_loaded_recording
from app.vod_library import VodLibrary
from core.powerup_history import PowerupHistory, PowerupObservation, RecordedEffect
from infra.vod_storage import LoadedVod, VodMetadata, VodSnapshot, VodStatValue
from ui.powerup_timeline import PowerupTimelineRow
from ui.styles import build_qt_app_stylesheet
from ui.timeline_controls import TimelineSeriesSlots
from ui.tabs.player_stats.recordings import RecordingsTab
from ui.tabs.compare_runs.tab import CompareRunsTab

app = QApplication([])
if not QFontDatabase.families():
    for filename in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / filename))
    app.setFont(QFont('Segoe UI', 10))
app.setStyleSheet(build_qt_app_stylesheet(''))
config.save_config = lambda _payload: None
slots = TimelineSeriesSlots((('Difficulty',), ('@powerups',), (), ()))
samples = []
for tick in range(41):
    at = tick / 2
    effects = tuple(RecordedEffect(effect_id, start, end) for effect_id, start, end in
                    ((1, 2, 15), (2, 5, 18), (3, 7, 20), (4, 9, 16)) if start <= at < end)
    samples.append(PowerupObservation(at, at, at, 'run', True, effects))
history = PowerupHistory(tuple(samples), True)
snapshots = tuple(VodSnapshot(at, at, {key: VodStatValue(at * scale, str(at * scale))
                  for key, scale in (('Difficulty', 10), ('XP Gain', 2), ('Damage', 3), ('Luck', 4))},
                            game_time_seconds=at, stage_index=0, stage_time_seconds=at)
                  for at in range(0, 21, 2))
metadata = VodMetadata(Path('powerup-qa.jsonl'), 'Powerup timeline', '2026-10-07T12:00:00', 10, 20, len(snapshots))
vod = LoadedVod(metadata, snapshots, history)
prepared = prepare_loaded_recording(vod, series_keys=('Difficulty', '@powerups'))
tabs = QTabWidget()
tabs.resize(1500, 920)
library = VodLibrary(load_cached=tuple, refresh_index=tuple)
recordings = RecordingsTab(tabview=tabs, vod_library=library, window=lambda: None,
                          vod_recorder=lambda: None, is_active=lambda: True,
                          log=lambda *_a, **_k: None, timeline_series_slots=slots)
recordings.build()
recordings.build_now()
recordings._loaded_vod = vod
recordings._prepared_recording = prepared
recordings._snapshot_index = 5
recordings.refresh_loaded_vod_ui(prepared=prepared)
tabs.show()
app.processEvents()
assert recordings._powerup_row.isVisible()
assert recordings._powerup_row.entries[0][3]
assert recordings._powerup_row.entries[0][2] == '0:08'
assert len(recordings._powerup_row.entries) == 4
assert recordings._powerup_row.parentWidget() is recordings._scrubber
assert recordings._powerup_row.geometry().bottom() < recordings._scrubber._plot_rect().top()
assert recordings._scrubber.height() == 150
assert recordings._powerups_checkbox.text() == 'Powerups'
assert recordings._powerups_checkbox.isChecked()
assert all('@powerups' not in slot for slot in slots.slots)
assert 'Power-ups' not in [action.text() for action in recordings._slot_buttons[0].menu().actions()]
assert 'A</b>' in recordings._compare_hint_label.text()
assert '00:10' in recordings._compare_hint_label.text()
assert 'Shift+RMB' in recordings._timeline_help_button.toolTip()
recordings._scrubber.grab()
assert len(recordings._scrubber._powerup_hits) == 4
assert len(recordings._scrubber._cached_paths) == 1
rect, tooltip = recordings._scrubber._powerup_hits[0]
assert 'Rage' in recordings._scrubber._marker_tooltip_at(rect.center())
old_plot = recordings._scrubber._plot_rect()
old_path = recordings._scrubber._cached_paths[0][0]
recordings.set_vod_compare_start(2)
assert 'A–B 00:04' in recordings._powerup_row.entries[0][4]
assert recordings._powerup_row.entries[0][2] == '0:06'
recordings.clear_vod_compare_start()
slots.set_powerups_enabled(False)
recordings._scrubber.grab()
assert recordings._scrubber._plot_rect().height() == old_plot.height() + 23
assert recordings._scrubber._plot_rect().top() == old_plot.top()
assert not recordings._powerup_row.isVisible()
slots.set_powerups_enabled(True)

compare = CompareRunsTab(tabview=tabs, vod_library=library, is_active=lambda: True,
                        timeline_series_slots=slots)
compare.build()
compare.build_now()
compare._vod_a = vod
compare._vod_b = replace(vod, metadata=replace(metadata, path=Path('old-powerup-qa.jsonl')), powerup_history=None)
compare._index_a = 5
compare._index_b = 5
compare._prepared_sides['a'] = prepared
compare._prepared_sides['b'] = prepare_loaded_recording(compare._vod_b, series_keys=('Difficulty', '@powerups'))
compare._timeline_compact = False
compare._refresh_compare_runs_timeline_model()
tabs.setCurrentWidget(compare._tab)
app.processEvents()
compare._timeline.grab()
assert not compare._powerup_rows['a'].isHidden()
assert compare._powerup_rows['a'].entries[0][3]
assert compare._powerup_rows['b'].note == 'No data'
assert all(entry[2] == '—' for entry in compare._powerup_rows['b'].entries)
compare._set_timeline_compact(True)
assert compare._powerup_rows['a'].isHidden()
# Compact retains numeric curves even with all four activity lanes enabled.
from unittest.mock import patch
import ui.tabs.compare_runs.timeline as timeline_module
compare._timeline._cache_key = None
with patch.object(timeline_module, 'build_series_path', wraps=timeline_module.build_series_path) as draw_paths:
    compare._timeline.grab()
assert draw_paths.call_count >= 2
assert all(call.args[2].height() > 0 for call in draw_paths.call_args_list)
assert len([text for rect, text in compare._timeline._marker_hits if text.startswith(('Rage', 'Shield', 'Stonks', 'Clock'))]) == 4
compare._set_timeline_compact(False)
assert not compare._powerup_rows['a'].isHidden()
compare._powerups_checkbox.setChecked(False)
assert not recordings._powerups_checkbox.isChecked()
assert not recordings._powerup_row.isVisible()
recordings._powerups_checkbox.setChecked(True)
assert compare._powerups_checkbox.isChecked()
for slot, key in ((1, 'XP Gain'), (2, 'Damage'), (3, 'Luck')):
    slots.set_slot(slot, (key,))
recordings._scrubber.grab()
assert len(recordings._scrubber._cached_paths) == 4
assert len(recordings._scrubber._powerup_hits) == 4
compare._timeline.grab()
powerup_hits = [text for rect, text in compare._timeline._marker_hits if any(text.startswith(n) for n in ('Rage', 'Shield', 'Stonks', 'Clock'))]
assert len(powerup_hits) == 4, powerup_hits
assert recordings._scrubber.height() == 150

# A frozen run-time axis still has a visible Clock stroke and true duration.
flat_history = PowerupHistory(tuple(PowerupObservation(i, i, 0, 'run', True,
                                 (RecordedEffect(4, 0, 5),)) for i in range(6)))
from projections.powerup_history import PowerupProjection
recordings._scrubber.set_powerups(PowerupProjection(flat_history))
recordings._scrubber.grab()
assert any('Clock' in text and '0m 05s' in text and rect.width() >= 6
           for rect, text in recordings._scrubber._powerup_hits)
short_history = PowerupHistory((PowerupObservation(0, 0, 0, 'run', True, ()),
    PowerupObservation(1, 1, 1, 'run', True, (RecordedEffect(4, .25, .5),))))
recordings._scrubber.set_powerups(PowerupProjection(short_history))
recordings._scrubber.grab()
assert any('0.250 s' in text for rect, text in recordings._scrubber._powerup_hits)
recordings._scrubber.set_powerups(prepared.powerups)

recordings._powerup_row.set_state(prepared.powerups, 18, axis_a=18)
recordings._powerup_row.grab()
assert not recordings._powerup_row.entries[0][3]
assert recordings._powerup_row.entries[0][2] == '0:13'
icon_rect, icon_tooltip = recordings._powerup_row._hits[0]
assert 'Rage' in recordings._scrubber._marker_tooltip_at(icon_rect.center().toPoint() + recordings._powerup_row.pos())

# Use the real wrapping row at a narrow width, retaining all four icons.
row = PowerupTimelineRow()
row.resize(320, 120)
row.show()
row.set_state(prepared.powerups, 10, axis_a=10)
app.processEvents()
assert row.height() == 17
assert len(row.entries) == 4
row.grab()
assert all(hit.right() <= row.width() for hit, tooltip in row._hits)
unknown_history = PowerupHistory((PowerupObservation(0, 0, 0, 'run', True, ()),
                                 PowerupObservation(1, None, None, 'run', False, ())))
row.set_state(PowerupProjection(unknown_history), 1, axis_a=1)
assert row.note == 'Unknown'
assert not any(entry[3] for entry in row.entries)
row.set_state(prepared.powerups, 10, axis_a=10)

# The first snapshot may already be offset from the beginning of the time axis.
# The legend must follow the actual caption, and a global font stylesheet must
# not enlarge its text or make its measurement differ from the stage font.
from math import ceil, floor
from types import SimpleNamespace
from projections.powerup_history import EffectSpan
from ui.powerup_timeline import paint_powerups, place_powerup_readout
from ui.timeline_visuals import paint_stage_band
header_font = QFont(app.font())
header_font.setPointSizeF(7)
header_font.setBold(True)
header_host = QWidget()
row.setParent(header_host)
row.show()
track = QRectF(0, 0, 600, 100)
caption = 'Stage 1 · 08:18'
header = place_powerup_readout(row, track, caption, header_font, caption_left=40)
metrics = QFontMetricsF(header_font)
assert header.left() >= 40 + 5 + ceil(metrics.horizontalAdvance(caption)) + 8
expected_width = sum(19 + metrics.horizontalAdvance(entry[2]) + 13 for entry in row.entries)
assert row.width() == ceil(expected_width)
stage_images = []
for exclusion in (None, header):
    image = QImage(600, 100, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    paint_stage_band(painter, QRectF(40, 0, 450, 100), fill=QColor('#182832'),
                     text=caption, font=header_font, header_exclusion=exclusion)
    painter.end()
    stage_images.append(image)
assert stage_images[0] == stage_images[1], 'Power-up legend cropped the stage timer'

# Distinct captured intervals can occupy the same pixels when Clock freezes
# the timeline. Alpha is applied once to their union, with no bright endpoints
# or antialiased halo, including fractional Windows DPI scaling.
spans = (EffectSpan(1, 0, 10, 10, 70, 60),
         EffectSpan(1, 11, 12, 70, 70, 1),
         EffectSpan(1, 13, 14, 70.25, 70.25, 1))
for dpr in (1.0, 1.25, 1.5625):
    image = QImage(ceil(320 * dpr), ceil(80 * dpr), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    hits = paint_powerups(painter, SimpleNamespace(intervals=spans), QRectF(10, 10, 300, 60), 100)
    painter.end()
    assert len(hits) == len(spans), 'Exact intervals must remain available in tooltips'
    y = floor(51 * dpr)
    colors = {image.pixelColor(x, y).rgba() for x in range(ceil(45 * dpr), floor(221 * dpr))}
    assert len(colors) == 1, f'Uneven activity opacity at DPR {dpr}: {colors}'
    assert image.pixelColor(ceil(224 * dpr), y) == image.pixelColor(ceil(280 * dpr), y)

if os.environ.get('BONK_POWERUP_QA_DIR'):
    output = Path(os.environ['BONK_POWERUP_QA_DIR'])
    output.mkdir(parents=True, exist_ok=True)
    tabs.setCurrentWidget(recordings._tab)
    app.processEvents()
    top = recordings._slot_buttons[0].mapTo(recordings._tab, recordings._slot_buttons[0].rect().topLeft()).y()
    bottom = recordings._legend_label.mapTo(recordings._tab, recordings._legend_label.rect().bottomLeft()).y() + 8
    recordings._tab.grab(QRect(0, top, recordings._tab.width(), bottom - top)).save(str(output / 'recordings-powerups.png'))
    tabs.setCurrentWidget(compare._tab)
    app.processEvents()
    top = compare._series_slot_buttons[0].mapTo(compare._tab, compare._series_slot_buttons[0].rect().topLeft()).y()
    bottom = compare._timeline.mapTo(compare._tab, compare._timeline.rect().bottomLeft()).y() + 8
    compare._tab.grab(QRect(0, top, compare._tab.width(), bottom - top)).save(str(output / 'compare-powerups.png'))

# A fast observation advances A even when no new heavy stat snapshot exists.
feed = ActiveRecordingFeed()
feed.start(metadata)
for snapshot in snapshots:
    feed.append(metadata, snapshot)
feed.update_powerups(PowerupHistory(history.observations))
live_library = VodLibrary(load_cached=tuple, refresh_index=tuple, active_recording_feed=feed)
recordings._library = live_library
recordings._live_follow = True
recordings._snapshot_index = len(snapshots) - 1
recordings._prepared_recording = prepare_loaded_recording(feed.active_state.loaded_vod,
                                series_keys=recordings._recording_model_keys(),
                                cap_keys=recordings._prepared_recording.cap_signature)
recordings._loaded_vod = recordings._prepared_recording.vod
latest_history = PowerupHistory(history.observations + (
    PowerupObservation(20.5, 20.5, 20.5, 'run', True, (RecordedEffect(1, 20.25, 30),)),))
latest_state = feed.update_powerups(latest_history)
recordings._submit_live_state(latest_state)
assert recordings._scrubber._live_position == 1.0
assert 'LIVE' in recordings._position_label.text()
assert recordings._powerup_row.entries[0][3]
recordings.on_scrub_index_changed(len(snapshots) - 1)
assert recordings._scrubber._live_position is None
assert not recordings._powerup_row.entries[0][3]
assert not recordings._live_follow

compare._library = live_library
compare._live_follow = True
compare._index_a = len(snapshots) - 1
compare._prepared_sides['a'] = prepare_loaded_recording(feed.active_state.loaded_vod,
                              series_keys=compare._compare_model_keys(), cap_keys=compare._enabled_cap_keys())
compare._vod_a = compare._prepared_sides['a'].vod
compare._submit_compare_live_state('a', latest_state)
assert abs(compare._timeline.position - 1.0) < 1e-9
assert compare._powerup_rows['a'].entries[0][3]
assert compare._powerup_rows['b'].note == 'No data'
assert all(entry[2] == '—' for entry in compare._powerup_rows['b'].entries)
print('Qt power-up viewers OK')
'''


class PowerupTimelineTests(unittest.TestCase):
    def test_real_viewers_geometry_rows_tooltips_shared_slots_and_compact(self):
        result = subprocess.run([sys.executable, "-c", textwrap.dedent(QT_SCENARIO)],
                                cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Qt power-up viewers OK", result.stdout)
