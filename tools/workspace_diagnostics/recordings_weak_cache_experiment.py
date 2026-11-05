"""Launch the existing headful probe with an experimental weak VOD cache."""

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
import os, sys, runpy, threading, weakref
from pathlib import Path
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE']='1'
sys.path[:0]=[str(REPO_ROOT),str(REPO_ROOT/'src')]
import src
import app.prepared_recording as prepared
original=prepared.load_vod
cache=weakref.WeakValueDictionary()
lock=threading.Lock()
def load(path, **kwargs):
    path=Path(path).resolve(); stat=path.stat(); key=(path,stat.st_mtime_ns,stat.st_size)
    with lock: result=cache.get(key)
    if result is not None:return result
    result=original(path,**kwargs)
    after=path.stat()
    if (after.st_mtime_ns,after.st_size)==(stat.st_mtime_ns,stat.st_size):
        with lock:cache[key]=result
    return result
prepared.load_vod=load
runpy.run_path(str(CODE_ROOT / "recordings_responsiveness_probe.py"),run_name='__main__')
