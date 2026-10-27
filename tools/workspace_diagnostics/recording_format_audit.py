"""Read-only audit of real JSONL payloads; output goes to runtime diagnostics."""

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
import os, sys, json, time, zlib, hashlib, collections, statistics
from pathlib import Path
root=Path(os.environ['LOCALAPPDATA'])/'BonkScanner'/'stats_recordings'
def encode(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
files=sorted(root.glob('*.jsonl'))
totals=collections.Counter();versions=collections.Counter();counts=collections.Counter()
bytes_by_type=collections.Counter();field_bytes=collections.Counter();unchanged=collections.Counter()
rows=[];errors=[];changed=[]
started=time.perf_counter()
for path in files:
    before=path.stat();raw=path.read_bytes();after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        changed.append(path.name);continue
    row={'file':path.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    local=collections.Counter();local_bytes=collections.Counter();local_fields=collections.Counter()
    previous_snapshot=None;previous_effects=None;previous_powerup=None;capture_gaps=[]
    sample_bytes=0;positional_sample_bytes=0;delta_snapshot_bytes=0;canonical_snapshot_bytes=0
    runs=set();version=None;same_effects=0;same_clocks=0;valid=0;invalid=0
    for number,line in enumerate(raw.splitlines(keepends=True),1):
        if not line.strip():continue
        try:r=json.loads(line)
        except (ValueError,UnicodeError) as exc:
            errors.append({'file':path.name,'line':number,'error':type(exc).__name__});continue
        if not isinstance(r,dict):
            errors.append({'file':path.name,'line':number,'error':'non-object'});continue
        kind=r.get('type','unknown');local[kind]+=1;local_bytes[kind]+=len(line)
        if kind=='metadata':version=r.get('version',1);row['interval_seconds']=r.get('snapshot_interval_seconds')
        if kind=='summary':row['duration_seconds']=r.get('duration_seconds')
        if kind=='snapshot':
            canonical_snapshot_bytes+=len(encode(r))+1
            for key,value in r.items():
                local_fields[key]+=len(encode(value))
                if previous_snapshot is not None and key in previous_snapshot and previous_snapshot[key]==value:
                    unchanged[key]+=1
            if previous_snapshot is None:delta_snapshot_bytes+=len(encode(r))+1
            else:
                delta={k:v for k,v in r.items() if k not in previous_snapshot or previous_snapshot[k]!=v}
                removed=[k for k in previous_snapshot if k not in r]
                delta_snapshot_bytes+=len(encode({'type':'snapshot_delta','set':delta,'removed':removed}))+1
            previous_snapshot=r
        elif kind=='powerup_sample':
            sample_bytes+=len(encode(r))+1
            positional_sample_bytes+=len(encode(['p',r.get('captured_at'),r.get('my_time'),r.get('axis_time'),r.get('run_id'),r.get('valid'),r.get('effects')]))+1
            runs.add(r.get('run_id'))
            if r.get('valid') is True:valid+=1
            else:invalid+=1
            effects=r.get('effects')
            same_effects+=previous_powerup is not None and effects==previous_effects
            same_clocks+=bool(previous_powerup and r.get('my_time')==previous_powerup.get('my_time')
                              and r.get('axis_time')==previous_powerup.get('axis_time')
                              and r.get('valid')==previous_powerup.get('valid') and effects==previous_effects)
            if previous_powerup is not None:
                gap=r.get('captured_at',0)-previous_powerup.get('captured_at',0)
                capture_gaps.append(gap)
            previous_effects=effects;previous_powerup=r
    row.update(version=version,counts=dict(local),bytes_by_type=dict(local_bytes),
               zlib1_bytes=len(zlib.compress(raw,1)),snapshot_field_payload_bytes=dict(local_fields),
               canonical_snapshot_bytes=canonical_snapshot_bytes,candidate_delta_snapshot_bytes=delta_snapshot_bytes,
               canonical_powerup_bytes=sample_bytes,candidate_positional_powerup_bytes=positional_sample_bytes,
               repeated_effect_samples=same_effects,repeated_clock_and_effect_samples=same_clocks,
               valid_powerup_samples=valid,invalid_powerup_samples=invalid,run_ids=len(runs))
    if capture_gaps:
        gaps=sorted(capture_gaps)
        row['sample_gap_seconds']={'median':statistics.median(gaps),'p95':gaps[int((len(gaps)-1)*.95)],'max':max(gaps)}
    rows.append(row);versions[version]+=1;counts.update(local);bytes_by_type.update(local_bytes);field_bytes.update(local_fields)
    for key in ('bytes','zlib1_bytes','canonical_snapshot_bytes','candidate_delta_snapshot_bytes','canonical_powerup_bytes',
                'candidate_positional_powerup_bytes','repeated_effect_samples','repeated_clock_and_effect_samples',
                'valid_powerup_samples','invalid_powerup_samples'):totals[key]+=row[key]
result={'root':str(root),'files':len(rows),'versions':dict(versions),'totals':dict(totals),'counts':dict(counts),
        'bytes_by_type':dict(bytes_by_type),'snapshot_field_payload_bytes':dict(field_bytes),
        'snapshot_unchanged_field_counts':dict(unchanged),'changed_during_read':changed,'errors':errors,
        'elapsed_seconds':round(time.perf_counter()-started,2),'files_detail':rows}
output_path('recording-format-audit.json').write_text(json.dumps(result,indent=2),'utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='files_detail'},indent=2))
print('LARGEST FILES')
for row in sorted(rows,key=lambda r:r['bytes'],reverse=True)[:8]:
    print(json.dumps({k:v for k,v in row.items() if k not in ('sha256','snapshot_field_payload_bytes')}))
