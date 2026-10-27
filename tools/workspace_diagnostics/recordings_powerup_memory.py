import os,sys,json
from pathlib import Path
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE']='1'
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
import src
from infra.vod_storage import load_vod
root=Path(os.environ['LOCALAPPDATA'])/'BonkScanner'/'stats_recordings'
path=max(root.glob('*.jsonl'),key=lambda p:p.stat().st_size)
vod=load_vod(path)
observations=vod.powerup_history.observations
effects=tuple(e for obs in observations for e in obs.effects)
def object_bytes(v):return sys.getsizeof(v)+(sys.getsizeof(v.__dict__) if hasattr(v,'__dict__') else 0)
ids={id(obs.run_id):obs.run_id for obs in observations if obs.run_id is not None}
print(json.dumps({'observations':len(observations),'effects':len(effects),
 'observation_bytes':sum(map(object_bytes,observations)),
 'effect_bytes':sum(map(object_bytes,effects)),
 'run_id_objects':len(ids),'run_id_bytes':sum(map(sys.getsizeof,ids.values()))}))
