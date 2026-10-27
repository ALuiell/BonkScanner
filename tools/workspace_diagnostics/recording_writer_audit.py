"""Exercise the recorder only in a temporary directory, using real payloads."""
import os,sys,time,json,tempfile,statistics,dataclasses,gzip,io
from pathlib import Path
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE']='1'
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
import src
from infra.vod_storage import VodRecorder,load_vod
from core.vod_capture import VodCapturePayload
root=Path(os.environ['LOCALAPPDATA'])/'BonkScanner'/'stats_recordings'
source=max((p for p in root.glob('*.jsonl') if p.name.startswith('2026-10-20')),key=lambda p:p.stat().st_size)
vod=load_vod(source)
def describe(values):
    values=sorted(values)
    return {'count':len(values),'median_ms':round(statistics.median(values),4),
            'p95_ms':round(values[int((len(values)-1)*.95)],4),'max_ms':round(max(values),4)}
class Settings:
    def read_minimum_snapshot_count(self):return 0
now=[0.0];result={'source':str(source)}
with tempfile.TemporaryDirectory(prefix='bonk-recording-audit-') as directory:
    recorder=VodRecorder(vods_dir=Path(directory),clock=lambda:now[0],settings=Settings())
    recorder.start(name='Temporary writer audit')
    samples=[]
    for observation in vod.powerup_history.observations:
        started=time.perf_counter_ns();recorder.observe_powerups(observation)
        samples.append((time.perf_counter_ns()-started)/1e6)
    result['observe_powerups_all']=describe(samples)
    result['observe_powerups_first_1000']=describe(samples[:1000])
    result['observe_powerups_last_1000']=describe(samples[-1000:])
    snapshot=vod.snapshots[-1]
    payload=VodCapturePayload(**{field.name:getattr(snapshot,field.name) for field in dataclasses.fields(VodCapturePayload)})
    captures=[]
    for _ in range(100):
        now[0]+=10
        started=time.perf_counter_ns();recorder.capture(payload)
        captures.append((time.perf_counter_ns()-started)/1e6)
    result['heavy_snapshot_capture']=describe(captures)
    started=time.perf_counter_ns();recorder.stop()
    result['stop_ms']=round((time.perf_counter_ns()-started)/1e6,4)
    result['temporary_file_bytes']=recorder.path.stat().st_size
    loaded=load_vod(recorder.path)
    result['temporary_roundtrip_counts']={'snapshots':len(loaded.snapshots),'powerups':len(loaded.powerup_history.observations)}
raw=source.read_bytes();compressed=gzip.compress(raw,compresslevel=1,mtime=0)
reads=[]
for mode in ('plain','gzip'):
    times=[]
    for _ in range(3):
        start=time.perf_counter()
        data=raw if mode=='plain' else gzip.decompress(compressed)
        count=sum(1 for line in data.splitlines() if line.strip() and isinstance(json.loads(line),dict))
        times.append((time.perf_counter()-start)*1000)
    reads.append({'mode':mode,'bytes':len(raw) if mode=='plain' else len(compressed),
                  'median_decode_ms':round(statistics.median(times),2),'records':count})
result['gzip_experiment']=reads
Path('scratch/recording-writer-audit.json').write_text(json.dumps(result,indent=2),'utf-8')
print(json.dumps(result,indent=2))
