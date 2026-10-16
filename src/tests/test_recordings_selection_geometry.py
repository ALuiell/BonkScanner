"""Record selection must paint in settled geometry even in a narrow window."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class RecordingSelectionGeometryTests(unittest.TestCase):
    def test_narrow_selection_and_loading_header_stay_stable(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ['QT_QPA_PLATFORM'] = 'offscreen'
            import src
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget
            from app import config
            from app.vod_library import VodLibrary
            from app.prepared_recording import prepare_loaded_recording
            from infra.vod_storage import LoadedVod, VodMetadata, VodSnapshot
            from ui.tabs.player_stats.recordings import RecordingsTab
            from ui.styles import build_qt_app_stylesheet

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(''))
            config.save_config = lambda payload: True
            window = QMainWindow()
            window.setMinimumSize(480, 360)
            central = QWidget()
            window.setCentralWidget(central)
            tabs = QTabWidget()
            QVBoxLayout(central).addWidget(tabs)
            library = VodLibrary(load_cached=tuple, refresh_index=tuple)
            view = RecordingsTab(
                tabview=tabs, vod_library=library, window=lambda:window,
                vod_recorder=lambda:None, is_active=lambda:True,
                log=lambda *args, **kwargs:None,
            )
            view.build()
            view.build_now()
            window.resize(650, 500)
            window.show()
            def flush():
                for _ in range(8): app.processEvents()
            flush()
            title = view._title_label
            plaque = title.parentWidget()
            # A changing name in an existing narrow label must be shortened
            # on its very first paint, without waiting for another resize.
            long_name = 'A very long recording name ' * 8
            title.setText(long_name)
            flush()
            title.resize(90, 32)
            pixels = title.grab().toImage()
            assert not pixels.isNull()
            assert title.text() == long_name
            assert title.toolTip() == long_name
            assert title.fontMetrics().elidedText(title.text(), Qt.ElideRight, 90) != long_name
            assert title.minimumSizeHint().width() == 0

            # Both spinner transitions must leave the heading and buttons in
            # exactly the same position, including with the library pinned.
            view.set_recordings_chooser_expanded(True, guided=False, remember=False)
            title.setText('950k')
            flush()
            idle = (title.geometry(), view._rename_btn.geometry(), plaque.size())
            view._set_vod_loading_state(True)
            flush()
            loading = (title.geometry(), view._rename_btn.geometry(), plaque.size())
            view._set_vod_loading_state(False)
            flush()
            assert idle == loading, (idle, loading)
            assert idle == (title.geometry(), view._rename_btn.geometry(), plaque.size())

            original_refresh = view.refresh_loaded_vod_ui
            expected_guided = False
            def observe_install(**kwargs):
                # This is the instant a newly loaded recording replaces the
                # old heading. The splitter and the plaque must already have
                # their final widths; a later layout pass cannot fix a flash.
                if expected_guided:
                    assert view._body_splitter.sizes()[0] == 0
                    assert plaque.width() == view._body_splitter.widget(1).width()
                else:
                    assert view._chooser_group.isVisible()
                original_refresh(**kwargs)
            view.refresh_loaded_vod_ui = observe_install
            for expected_guided in (False, True):
                for name in ('950k', long_name):
                    view.set_recordings_chooser_expanded(True, guided=expected_guided, remember=False)
                    flush()
                    metadata = VodMetadata(Path('geometry.jsonl'), name, '2026-10-06T12:00:00', 10, 10, 1)
                    vod = LoadedVod(metadata, (VodSnapshot(0, 0, {}),))
                    with patch('ui.tabs.player_stats.recordings.load_vod', return_value=vod):
                        view.load_selected_vod(metadata.path)
                    flush()
                    assert title.text() == name, view._status_label.text()
                    assert view._chooser_expanded == (not expected_guided)
                    assert window.width() == 650

            # Keep a real selection pending across event-loop turns. The
            # populated compare hint used to constrain the detail's minimum
            # width; clearing it on load redistributed space to the library.
            class PendingLoad:
                def submit(self, path, **kwargs):
                    self.complete = kwargs['complete']
                def dispose(self):
                    pass
            pending = PendingLoad()
            view.refresh_loaded_vod_ui = original_refresh
            view._load_lane.dispose()
            view._load_lane = pending
            view._schedule = lambda callback: callback()
            for width in (650, 900, 1320, 1600, 1850):
                window.resize(width, 700)
                view.set_recordings_chooser_expanded(True, guided=False, remember=False)
                view._library_width = 368
                view._apply_library_width()
                flush()
                before = view._body_splitter.sizes()
                assert view._compare_hint_label.text()
                metadata = VodMetadata(Path('next.jsonl'), 'Next recording', '2026-10-06T12:00:00', 10, 10, 1)
                vod = LoadedVod(metadata, (VodSnapshot(0, 0, {}),))
                view.load_selected_vod(metadata.path)
                flush()
                assert view._load_in_progress
                assert view._body_splitter.sizes() == before, (width, before, view._body_splitter.sizes())
                assert window.width() == width
                pending.complete(prepare_loaded_recording(vod, series_keys=view._recording_model_keys(), cap_keys=()), None)
                flush()
                assert not view._load_in_progress
                assert view._body_splitter.sizes() == before, (width, before, view._body_splitter.sizes())
                assert window.width() == width

            # Loading occupies the existing toggle, leaving only the normal
            # six-pixel layout spacing between that button and the heading.
            assert title.x() == view._select_btn.geometry().right() + 1 + 6
            assert view._detail_loading_spinner.parentWidget() is view._select_btn
            # Isolate native widget teardown, like test_recordings_layout.py.
            os._exit(0)
            """
        )
        environment = os.environ.copy()
        environment['BONKSCANNER_IGNORE_SHARED_STORAGE'] = '1'
        result = subprocess.run(
            [sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
