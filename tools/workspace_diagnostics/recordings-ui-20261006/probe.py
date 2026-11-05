
# Resolve this checkout and keep diagnostic output separate from source/evidence.
import sys as _diag_sys
from pathlib import Path as _DiagPath
for _diag_parent in _DiagPath(__file__).resolve().parents:
    if (_diag_parent / "workspace_paths.py").is_file():
        _diag_sys.path.insert(0, str(_diag_parent))
        break
from workspace_paths import (REPO_ROOT, CODE_ROOT, output_path, output_directory,
                             session_directory, local_asset_path, stage_recording_fixtures)
_diag_sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "src"), str(REPO_ROOT / "src/tests")]
import os
import sys
import json
import time
import ctypes
from pathlib import Path

ROOT = REPO_ROOT
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE'] = '1'
# Respect the caller's platform selection, including offscreen verification.
import src
from PySide6.QtCore import QObject, Signal, QTimer, QEvent, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget
from app import config
from app.vod_library import VodLibrary
from infra.vod_storage import list_vods
from ui.tabs.player_stats.recordings import RecordingsTab
from ui.styles import build_qt_app_stylesheet

folder = session_directory("recordings-ui-20261006")
stage_recording_fixtures(folder / "recordings")
phase = sys.argv[1] if len(sys.argv) > 1 else 'before'
if 'baseline' in phase:
    import importlib.util
    spec = importlib.util.spec_from_file_location('baseline_recordings', CODE_ROOT / 'recordings-ui-20261006/baseline_recordings.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    RecordingsTab = baseline.RecordingsTab
logfile = (folder / (phase + '.jsonl')).open('w', encoding='utf-8')
config.save_config = lambda payload: True
config.user_config['RECORDINGS_LIBRARY_OPEN'] = False
config.user_config['LIVE_STATS_EXPANDED'] = True

class Dispatch(QObject):
    requested = Signal(object)
    def __init__(self):
        super().__init__()
        self.requested.connect(lambda cb: cb(), Qt.QueuedConnection)

app = QApplication([])
app.setStyleSheet(build_qt_app_stylesheet(''))
dispatch = Dispatch()
window = QMainWindow()
window.setWindowTitle('BonkScanner Original - Recordings UI probe ' + phase)
window.setMinimumSize(480, 360)
central = QWidget()
window.setCentralWidget(central)
layout = QVBoxLayout(central)
actions = QHBoxLayout()
layout.addLayout(actions)
tabs = QTabWidget()
layout.addWidget(tabs, 1)
library = VodLibrary(load_cached=lambda: tuple(list_vods(folder / 'recordings')), refresh_index=lambda: tuple(list_vods(folder / 'recordings')))
view = RecordingsTab(tabview=tabs, vod_library=library, window=lambda:window, vod_recorder=lambda:None, is_active=lambda:True, log=lambda *a, **k:None, schedule=dispatch.requested.emit)
view.build()
view.build_now()
view.set_recordings_chooser_expanded(True, guided=not phase.startswith('pinned'), remember=False)

def button(text, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    actions.addWidget(widget)
    return widget
button('Reset guided selection', lambda: view._clear_loaded_vod_selection())
button('Pin library open', lambda: view.set_recordings_chooser_expanded(True, guided=False, remember=False))
button('1100 x 830', lambda: window.resize(1100, 830))
button('650 x 500', lambda: window.resize(650, 500))
button('Close probe', window.close)

user32 = ctypes.windll.user32
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
class Rect(ctypes.Structure):
    _fields_ = [('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
started = time.perf_counter()
last = None
def state():
    title = view._title_label
    plaque = title.parentWidget()
    rect = Rect()
    user32.GetWindowRect(int(window.winId()), ctypes.byref(rect))
    return dict(window=[window.width(), window.height()], native=[rect.left,rect.top,rect.right,rect.bottom], splitter=view._body_splitter.sizes(), plaque=[plaque.width(),plaque.height()], title=[title.x(),title.y(),title.width(),title.height()], text=title.text(), spinner=view._detail_loading_spinner.isVisible(), loading=view._load_in_progress, chooser=view._chooser_expanded, status=view._status_label.text())
def report(kind, force=False):
    global last
    current = state()
    if current != last or force:
        logfile.write(json.dumps(dict(t=round(time.perf_counter()-started,4),kind=kind,**current),ensure_ascii=False)+'\n')
        logfile.flush()
        last = current
class Watch(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint:
            report('paint', True)
        return False
watch = Watch()
view._title_label.parentWidget().installEventFilter(watch)
timer = QTimer()
timer.timeout.connect(lambda: report('sample'))
timer.start(16)
window.resize(1100 if 'matched' in phase else 1600 if 'wide' in phase else 1320 if phase.startswith('pinned') else 900, 830 if phase.startswith('pinned') else 600)
window.show()
print('READY',phase,'pid',os.getpid(),'hwnd',int(window.winId()),flush=True)
app.exec()
logfile.close()
os._exit(0)
