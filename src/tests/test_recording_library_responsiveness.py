"""Large libraries must retain their rows through filtering and index updates."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class RecordingLibraryResponsivenessTests(unittest.TestCase):
    def test_both_tabs_reuse_rows_and_finish_with_latest_library(self):
        script = textwrap.dedent('''
            import os
            os.environ['QT_QPA_PLATFORM'] = 'offscreen'
            import src
            from dataclasses import replace
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QEvent, Qt
            from PySide6.QtWidgets import QApplication, QListWidget, QMainWindow, QTabWidget, QWidget
            from app import config
            from app.vod_library import VodLibrary
            from infra.vod_storage import VodMetadata
            from projections.recording_sort import RECORDING_SORT_SNAPSHOTS
            from ui.tabs.player_stats.recordings import RecordingsTab
            from ui.tabs.compare_runs.tab import CompareRunsTab
            from ui.recording_library import RecordingLibraryRow, sync_recording_rows

            app = QApplication([])
            config.save_config = lambda *_a, **_kw: True
            config.update_config = lambda *_a, **_kw: True
            vods = tuple(VodMetadata(Path(f'run-{i}.jsonl'), f'Run {i:03}',
                         '2026-10-25T12:00:00', 10, i * 10, i + 1)
                         for i in range(120))
            library = VodLibrary(load_cached=lambda: vods, refresh_index=lambda: vods)
            library.ensure_refresh = lambda: None
            window = QMainWindow()
            tabs = QTabWidget(); tabs.addTab(QWidget(), 'Home'); window.setCentralWidget(tabs)
            rec = RecordingsTab(tabview=tabs, vod_library=library, window=lambda:window,
                                vod_recorder=lambda:None, is_active=lambda:True,
                                log=lambda *_a, **_kw:None)
            comp = CompareRunsTab(tabview=tabs, vod_library=library, is_active=lambda:True)
            rec.build(); comp.build()

            # A refresh delivered between row batches must not race the staged
            # iterator or leave stale rows from its older metadata snapshot.
            for view, refresh, invalidate, frame in (
                (rec, rec.refresh_vods_list, rec.invalidate_vods_list, lambda:rec._list_frame),
                (comp, comp.refresh_compare_runs_list, comp.invalidate_compare_runs_list, lambda:comp._run_a_list_frame),
            ):
                while frame() is None or frame().count() < 8:
                    assert view._tab._consume_step()
                library._index = (*vods[1:], replace(vods[0], name='Changed while loading'))
                invalidate(); refresh(refresh_index=False)
                view.build_now()
                assert frame().count() == 120
                rows = rec._list_rows_by_path if view is rec else comp._list_rows['a']
                assert rows[str(vods[0].path)].metadata.name == 'Changed while loading'
                assert not frame().signalsBlocked()
                library._index = vods

            rec.refresh_vods_list(refresh_index=False)
            comp.refresh_compare_runs_list(refresh_index=False)
            # Ordinary playhead moves within a stage must not repeatedly
            # repolish every chapter label; real state transitions still do.
            card = rec._stage_cards[0]
            style = card.style()
            with patch.object(style, 'polish', wraps=style.polish) as polish:
                card.set_state(has_data=True, is_current=True, is_anchor=False)
                writes = polish.call_count
                assert writes > 0
                card.set_state(has_data=True, is_current=True, is_anchor=False)
                assert polish.call_count == writes
                card.set_state(has_data=True, is_current=True, is_anchor=True)
                assert polish.call_count > writes
                assert card.property('rangeAnchor')
            original_rec = dict(rec._list_rows_by_path)
            original_comp = {s:dict(comp._list_rows[s]) for s in ('a','b')}
            picked = rec._list_items_by_path[str(vods[60].path)]
            blocked = rec._list_frame.blockSignals(True)
            rec._list_frame.setCurrentItem(picked)
            rec._list_frame.blockSignals(blocked)
            with patch.object(library, 'ensure_refresh', side_effect=AssertionError('search scanned disk')):
                for query in ('Run 00', 'does not exist', '', 'RUN 00', ''):
                    rec._search_entry.setText(query)
                    expected = sum(not query or query.casefold() in v.name.casefold() for v in vods)
                    assert sum(not item.isHidden() for item in rec._list_items_by_path.values()) == expected
                assert rec._list_frame.currentItem() is picked
                for view in (rec, comp):
                    view._sort_combo.setCurrentIndex(view._sort_combo.findData(RECORDING_SORT_SNAPSHOTS))
            assert rec._list_rows_by_path == original_rec
            assert comp._list_rows == original_comp
            assert rec._list_frame.item(0).data(Qt.UserRole) == str(vods[-1].path)
            for side in ('a','b'):
                frame = comp._compare_run_widget(side,'list_frame')
                assert frame.item(0).data(Qt.UserRole) == str(vods[-1].path)
                assert not frame.signalsBlocked()

            # Rename/add/remove changes just the affected data and membership.
            renamed = replace(vods[30], name='Renamed recording')
            added = replace(vods[0], path=Path('added.jsonl'), name='New recording')
            library._index = (*vods[1:30], renamed, *vods[31:], added)
            for view, refresh, invalidate in ((rec,rec.refresh_vods_list,rec.invalidate_vods_list),
                                              (comp,comp.refresh_compare_runs_list,comp.invalidate_compare_runs_list)):
                invalidate(); refresh(refresh_index=False)
            for key in map(str, (v.path for v in vods[1:])):
                assert rec._list_rows_by_path[key] is original_rec[key]
                for side in ('a','b'): assert comp._list_rows[side][key] is original_comp[side][key]
            assert str(vods[0].path) not in rec._list_rows_by_path
            assert rec._list_rows_by_path[str(renamed.path)]._name_label.text() == renamed.name
            rec._search_entry.setText('Renamed')
            assert not rec._list_items_by_path[str(renamed.path)].isHidden()
            for side in ('a','b'):
                comp._compare_run_widget(side,'search').setText('Renamed')
                assert sum(not item.isHidden() for item in comp._list_items[side].values()) == 1

            # Empty -> populated -> empty never leaves a stale placeholder or
            # blocks selection signals, including interrupted staged iteration.
            for index in ((), vods, ()):
                library._index = index
                rec.invalidate_vods_list(); rec.refresh_vods_list(refresh_index=False)
                comp.invalidate_compare_runs_list(); comp.refresh_compare_runs_list(refresh_index=False)
            assert rec._list_frame.count() == 1
            assert comp._run_a_list_frame.count() == 1
            steps = sync_recording_rows(rec._list_frame, vods, rec._list_items_by_path,
                rec._list_rows_by_path, longest_seconds=1200, is_live=lambda _p:False, batch_size=8)
            next(steps)
            assert not rec._list_frame.signalsBlocked()
            steps.close()
            assert not rec._list_frame.signalsBlocked()
            transient = QListWidget()
            steps = sync_recording_rows(transient, vods, {}, {}, longest_seconds=1200,
                                        is_live=lambda _p:False, batch_size=8)
            next(steps)
            transient.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            steps.close()
            os._exit(0)
        ''')
        environment = os.environ.copy()
        environment['BONKSCANNER_IGNORE_SHARED_STORAGE'] = '1'
        root = Path(__file__).resolve().parents[2]
        environment['PYTHONPATH'] = os.pathsep.join((str(root.parent), str(root)))
        result = subprocess.run([sys.executable, '-c', script], cwd=root.parent,
                                env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
