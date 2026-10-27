
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
import os,sys,json
from pathlib import Path
os.environ['BONKSCANNER_IGNORE_SHARED_STORAGE']='1'
sys.path[:0]=[str(REPO_ROOT),str(REPO_ROOT/'src')]
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
