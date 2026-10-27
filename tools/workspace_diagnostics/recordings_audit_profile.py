import os
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE']='1'
import sys, time, json, cProfile, pstats, gc, io
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
import src
from infra.vod_storage import load_vod
from app.prepared_recording import prepare_loaded_recording
root=Path(os.environ['LOCALAPPDATA'])/'BonkScanner'/'stats_recordings'
files=sorted(root.glob('*.jsonl'),key=lambda p:p.stat().st_size,reverse=True)
kept=[];results=[]
for path in files[:2]:
    profile=cProfile.Profile();start=time.perf_counter();profile.enable()
    vod=load_vod(path)
    profile.disable();load_ms=(time.perf_counter()-start)*1000
    start=time.perf_counter();prepared=prepare_loaded_recording(vod,series_keys=('kills','difficulty','luck'))
    prepare_ms=(time.perf_counter()-start)*1000
    text=io.StringIO();pstats.Stats(profile,stream=text).sort_stats('cumtime').print_stats(24)
    print(path.name,load_ms,prepare_ms,flush=True);print(text.getvalue(),flush=True)
    results.append({'path':str(path),'bytes':path.stat().st_size,'snapshots':len(vod.snapshots),'load_ms':round(load_ms,2),'prepare_ms':round(prepare_ms,2)})
    kept.append(prepared)
Path('scratch/recordings-audit-profile.json').write_text(json.dumps(results,indent=2))
