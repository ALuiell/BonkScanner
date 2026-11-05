
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
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE'] = '1'
import sys, json, time, argparse, faulthandler, gc, cProfile, pstats, io, statistics
faulthandler.dump_traceback_later(20, repeat=True)
from pathlib import Path
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / 'src')]
import src
from PySide6.QtCore import QObject, Signal, Qt, QTimer, QPoint
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget
from app import config
from app.vod_library import VodLibrary
from infra import vod_storage as storage
from ui.tabs.player_stats.recordings import RecordingsTab
from ui.tabs.compare_runs.tab import CompareRunsTab
from ui.styles import build_qt_app_stylesheet

parser = argparse.ArgumentParser()
parser.add_argument('--output', default=str(output_path("recordings-before.json")))
parser.add_argument('--interactive', action='store_true')
parser.add_argument('--staged', action='store_true')
parser.add_argument('--cooperate', action='store_true')
parser.add_argument('--scrub', action='store_true')
args = parser.parse_args()
if args.cooperate:
    original_records=storage._iter_records
    def cooperative_records(*a,**kw):
        deadline=time.perf_counter()+0.008
        for record in original_records(*a,**kw):
            yield record
            if time.perf_counter()>=deadline:
                time.sleep(0.001)
                deadline=time.perf_counter()+0.008
    storage._iter_records=cooperative_records
root = session_directory("recordings-responsiveness")
stage_recording_fixtures(root / "stats_recordings")
class Settings:
    def __init__(self): self.index = {}
    def read_metadata_index(self): return self.index
    def write_metadata_index(self, payload): self.index = payload
settings = Settings()
storage.RECORDINGS_DIR = root/'stats_recordings'
storage.LEGACY_VODS_DIR = root/'vods'
storage.refresh_vod_metadata_index(settings)
results = {}
collections=[]
gc_start={}
def gc_probe(phase, info):
    if phase=='start': gc_start[info['generation']]=time.perf_counter()
    else:
        elapsed=(time.perf_counter()-gc_start.get(info['generation'],time.perf_counter()))*1000
        if elapsed>5: collections.append((info['generation'],round(elapsed,2)))
gc.callbacks.append(gc_probe)
def measure(name, callback):
    print('START', name, flush=True)
    start = time.perf_counter()
    result = callback()
    results[name] = round((time.perf_counter()-start)*1000, 2)
    return result
metadata = measure('cached_index_ms', lambda: storage.load_cached_vods(settings))
measure('warm_index_ms', lambda: storage.refresh_vod_metadata_index(settings))
results['recordings'] = len(metadata)
results['largest_bytes'] = max(v.path.stat().st_size for v in metadata)
app = QApplication([])
app.setStyleSheet(build_qt_app_stylesheet(''))
config.save_config = lambda *_args, **_kwargs: True
config.update_config = lambda *_args, **_kwargs: True
class Invoker(QObject):
    posted = Signal(object)
    def __init__(self):
        super().__init__()
        self.posted.connect(lambda fn: fn(), Qt.QueuedConnection)
    def schedule(self, fn): self.posted.emit(fn)
invoker = Invoker()
library = VodLibrary(load_cached=lambda: metadata, refresh_index=lambda: metadata, schedule=invoker.schedule)
window = QMainWindow()
window.setAttribute(Qt.WA_ShowWithoutActivating, True)
window.setWindowTitle('BonkScanner Recordings responsiveness probe')
tabs = QTabWidget()
tabs.addTab(QWidget(), 'Home')
window.setCentralWidget(tabs)
recordings = RecordingsTab(tabview=tabs, vod_library=library, window=lambda:window, vod_recorder=lambda:None,
                          is_active=lambda:tabs.currentIndex()==1, log=lambda *a,**kw:None, schedule=invoker.schedule)
compare = CompareRunsTab(tabview=tabs, vod_library=library, is_active=lambda:tabs.currentIndex()==2, schedule=invoker.schedule)
recordings.build(); compare.build()
window.resize(1280, 800); window.show()
def export_state():
    widgets={'tabs':tabs.tabBar(), 'rec_search':recordings._search_entry, 'rec_list':recordings._list_frame,
             'rec_sort':recordings._sort_combo, 'rec_scrubber':recordings._scrubber,
             'rec_library':recordings._select_btn, 'comp_change':compare._run_a_change_btn,
             'comp_search_a':compare._run_a_search, 'comp_search_b':compare._run_b_search,
             'comp_list_a':compare._run_a_list_frame, 'comp_list_b':compare._run_b_list_frame,
             'comp_sort':compare._sort_combo, 'comp_timeline':compare._timeline, 'comp_details':compare._detail_tabs,
             'rec_details':recordings._detail_tabs}
    rects={}
    for name,w in widgets.items():
        if w is not None:
            p=w.mapTo(window,QPoint(0,0)); rects[name]=[p.x(),p.y(),w.width(),w.height()]
    def selected(v): return str(v.metadata.path) if v is not None else None
    payload={'hwnd':int(window.winId()),'width':window.width(),'rects':rects,'tab':tabs.currentIndex(),
             'rec_selected':selected(recordings._loaded_vod),'a_selected':selected(compare._vod_a),'b_selected':selected(compare._vod_b),
             'rec_query':recordings._search_entry.text() if recordings._search_entry else '',
             'a_query':compare._run_a_search.text() if compare._run_a_search else '',
             'b_query':compare._run_b_search.text() if compare._run_b_search else '',
             'rec_visible':sum(not i.isHidden() for i in recordings._list_items_by_path.values()),
             'a_visible':sum(not i.isHidden() for i in compare._list_items['a'].values()),
             'rec_index':recordings._snapshot_index, 'a_index':compare._index_a,'b_index':compare._index_b,
             'rec_detail':recordings._detail_tabs.currentIndex() if recordings._detail_tabs else None,
             'comp_detail':compare._detail_tabs.currentIndex() if compare._detail_tabs else None}
    output_path('recordings-ui-state.json').write_text(json.dumps(payload),'utf-8')
export_timer=QTimer(); export_timer.timeout.connect(export_state); export_timer.start(200)
gaps = []
last_tick = time.perf_counter()
def tick():
    global last_tick
    now = time.perf_counter()
    gaps.append((now-last_tick)*1000)
    last_tick = now
heartbeat = QTimer(); heartbeat.setTimerType(Qt.PreciseTimer); heartbeat.setInterval(10)
heartbeat.timeout.connect(tick); heartbeat.start()
def flush():
    for _ in range(4): app.processEvents()
def run():
    measure('recordings_build_ms', recordings.build_now)
    tabs.setCurrentIndex(1); recordings.ensure_recordings_chooser_for_empty_selection(); flush()
    measure('recordings_refresh_ms', lambda: recordings.refresh_vods_list(refresh_index=False))
    measure('recordings_search_ms', lambda: recordings._search_entry.setText('Dice'))
    measure('recordings_clear_search_ms', lambda: recordings._search_entry.clear())
    measure('recordings_search_paint_ms', flush)
    measure('recordings_sort_ms', lambda: recordings._sort_combo.setCurrentIndex((recordings._sort_combo.currentIndex()+1)%recordings._sort_combo.count()))
    measure('recordings_sort_paint_ms', flush)
    measure('compare_build_ms', compare.build_now)
    tabs.setCurrentIndex(2); compare.ensure_compare_runs_chooser_for_empty_selection(); flush()
    measure('compare_refresh_ms', lambda: compare.refresh_compare_runs_list(refresh_index=False))
    measure('compare_sort_ms', lambda: compare._sort_combo.setCurrentIndex((compare._sort_combo.currentIndex()+1)%compare._sort_combo.count()))
    measure('compare_sort_paint_ms', flush)
    measure('compare_search_ms', lambda: compare._run_a_search.setText('Dice'))
    measure('compare_search_paint_ms', flush)
    compare._run_a_search.clear()
    Path(args.output).write_text(json.dumps(results, indent=2), 'utf-8')
    print(json.dumps(results), flush=True)
    if not args.interactive: os._exit(0)
def save():
    Path(args.output).write_text(json.dumps(results, indent=2), 'utf-8')
    print(json.dumps(results), flush=True)
def later_until(predicate, done, start=None):
    start = start or time.perf_counter()
    if predicate(): done()
    elif time.perf_counter()-start > 45:
        results['timeout'] = True; save(); os._exit(2)
    else: QTimer.singleShot(20, lambda: later_until(predicate, done, start))
def phase(name, action, predicate, next_phase):
    gaps.clear()
    start = time.perf_counter()
    action()
    def done():
        results[name+'_ms'] = round((time.perf_counter()-start)*1000, 2)
        results[name+'_max_gui_gap_ms'] = round(max(gaps, default=0), 2)
        print(name, results[name+'_ms'], results[name+'_max_gui_gap_ms'], flush=True)
        QTimer.singleShot(100, next_phase)
    later_until(predicate, done)
def staged():
    stages = {'recordings':[], 'compare':[]}
    for name, view in [('recordings',recordings),('compare',compare)]:
        original = view._tab._consume_step
        def traced(original=original, name=name):
            start=time.perf_counter()
            result=original()
            stages[name].append(round((time.perf_counter()-start)*1000,2))
            return result
        view._tab._consume_step=traced
    largest = max(metadata,key=lambda v:v.path.stat().st_size)
    second = sorted(metadata,key=lambda v:v.path.stat().st_size)[-2]
    def compare_build():
        phase('compare_staged_build',lambda: tabs.setCurrentIndex(2),lambda:compare._tab.is_built,load_recordings)
    def load_recordings():
        tabs.setCurrentIndex(1); recordings.ensure_recordings_chooser_for_empty_selection()
        phase('recordings_largest_load',lambda:recordings.load_selected_vod(largest.path),
              lambda:recordings._loaded_vod is not None,load_compare)
    def load_compare():
        tabs.setCurrentIndex(2); compare.ensure_compare_runs_chooser_for_empty_selection()
        def load():
            submitted=time.perf_counter()
            compare.load_compare_run('a',largest.path); compare.load_compare_run('b',second.path)
            def observe_a():
                if compare._vod_a is None: QTimer.singleShot(10, observe_a)
                else:
                    results['compare_reused_a_ready_ms']=round((time.perf_counter()-submitted)*1000,2)
                    results['shared_snapshot_identity']=compare._vod_a.snapshots is recordings._loaded_vod.snapshots
            QTimer.singleShot(10, observe_a)
        phase('compare_two_large_load',load,lambda:compare._vod_a is not None and compare._vod_b is not None,finish)
    def finish():
        if args.scrub:
            tabs.setCurrentIndex(1);flush()
            frames=[];profile=cProfile.Profile()
            for i in range(0,len(recordings._loaded_vod.snapshots),24):
                start=time.perf_counter();recordings.display_loaded_vod_snapshot(i)
                frames.append((time.perf_counter()-start)*1000);flush()
            results['recordings_scrub_median_ms']=round(statistics.median(frames),2)
            results['recordings_scrub_max_ms']=round(max(frames),2)
            profile.enable()
            for i in range(0,len(recordings._loaded_vod.snapshots),36):recordings.display_loaded_vod_snapshot(i)
            profile.disable();output=io.StringIO();pstats.Stats(profile,stream=output).sort_stats('cumtime').print_stats(18)
            print(output.getvalue(),flush=True)
        results['stage_max_ms']={k:max(v,default=0) for k,v in stages.items()}
        results['stage_times_ms']=stages
        results['gc_pauses_ms']=collections
        save()
        if not args.interactive: os._exit(0)
    phase('recordings_staged_build',lambda: tabs.setCurrentIndex(1),lambda:recordings._tab.is_built,compare_build)
QTimer.singleShot(50, staged if args.staged else run)
app.exec()
