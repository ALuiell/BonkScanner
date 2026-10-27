"""Launch the existing headful probe with an experimental weak VOD cache."""
import os, sys, runpy, threading, weakref
from pathlib import Path
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE']='1'
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
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
runpy.run_path('scratch/recordings_responsiveness_probe.py',run_name='__main__')
