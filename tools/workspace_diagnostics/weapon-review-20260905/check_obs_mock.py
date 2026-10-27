
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
from pathlib import Path
fragment = local_asset_path('weapon-review-20260905/obs-weapon-tracker-fragment.html').read_text(encoding='utf-8')
out = output_directory("weapon-review-20260905")
assert len(fragment.encode()) < 1_000_000
assert '<html' not in fragment and '<body' not in fragment
assert 'fetch(' not in fragment
stub = '<script>window.tweaks=[];window.Tweak=class {constructor(c){this.c=c;}addToggle(o,k){window.tweaks.push({o,k,render:this.c.onChange});}};</script>'
check = '''<script>
const r=document.getElementById('bs-obs-weapon-mock');
const fail=[];const results=[];
for(const b of r.querySelectorAll('[data-variant]')){
 b.click(); const caps=b.dataset.variant.endsWith('-on');
 const values=[...r.querySelectorAll('strong')].map(n=>n.textContent);
 if(caps!==(r.querySelectorAll('.weapon-cap').length>0)) fail.push('caps');
 if((b.dataset.variant.startsWith('detailed')?4:0)!==r.querySelectorAll('.detailed').length) fail.push('layout');
 if(values.length!==21||values[1]!=='82')fail.push('values');
 if(r.scrollWidth>r.clientWidth+1)fail.push('overflow');
 results.push({variant:b.dataset.variant,caps:r.querySelectorAll('.weapon-cap').length,values:values.length});
}
const config=window.tweaks[0];config.o.allStats=false;config.o.header=false;config.o.background=false;config.o.border=false;config.render();
if(r.querySelectorAll('strong').length!==12||r.querySelector('.bs-panel-title'))fail.push('tweaks');
config.o.allStats=true;config.o.header=true;config.o.background=true;config.o.border=true;
config.o.variant='compact-on';config.render();
document.body.setAttribute('data-check',JSON.stringify({ok:!fail.length,fail,results,width:r.clientWidth}));
</script>'''
(out/'obs-mock-check.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:12px;background:#181818}</style>'+stub+fragment+check,encoding='utf-8')
