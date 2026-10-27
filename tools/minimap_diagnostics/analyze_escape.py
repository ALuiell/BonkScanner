import io
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw

p = Path(sys.argv[1])
rows = [json.loads(line) for line in (p/'samples.jsonl').read_text().splitlines()]
with (p/'frames.bin').open('rb') as stream:
    for r in rows:
        if 'offset' not in r:
            r['icon'] = None
            continue
        stream.seek(r['offset'])
        a = np.array(Image.open(io.BytesIO(stream.read(r['length']))))
        yy,xx = np.indices(a.shape[:2])
        cx,cy = a.shape[1]/2,a.shape[0]/2
        inside = (xx-cx)**2+(yy-cy)**2 < (min(cx,cy)-25)**2
        cyan = (a[:,:,0]<90)&(a[:,:,1]>185)&(a[:,:,2]>215)&(a[:,:,1].astype(float)>.8*a[:,:,2])&inside
        y,x = np.nonzero(cyan)
        r['cyan_pixels'] = len(x)
        r['icon'] = bool(len(x)>=45 and 22<x.max()-x.min()<45 and 12<y.max()-y.min()<40)
        if r['icon']:
            r['icon_box'] = [int(x.min()),int(y.min()),int(x.max()),int(y.max())]
transitions = [i for i in range(1,len(rows)) if rows[i].get('paused') is False and rows[i-1].get('paused') is True]
results = []
for i in transitions:
    t = rows[i]['pause_time']
    previous = i-1
    while previous>0 and rows[previous-1].get('paused') is True:
        previous -= 1
    end = i+1
    while end<len(rows) and rows[end].get('paused') is False and rows[end]['t']-rows[i]['t']<1:
        end += 1
    hidden = [r for r in rows[previous:i] if r['icon'] is False]
    observed = next((j for j in range(i,end-1) if rows[j]['icon'] is True and rows[j+1]['icon'] is True),None)
    entry = {'resume_t':t,'paused_duration_ms':1000*(t-rows[previous]['pause_time']),
             'hidden_frames_before_resume':len(hidden),'resume_frame_index':i}
    if not hidden:
        entry['status'] = 'no_hidden_frame_before_resume'
    elif observed is None:
        entry['status'] = 'not_seen_before_next_pause_or_one_second'
    else:
        entry.update(status='measured',first_icon_frame_index=observed,
                     return_ms=1000*(rows[observed]['screen_time']-t),
                     pause_sampling_uncertainty_ms=1000*(t-rows[i-1]['pause_time']))
    results.append(entry)
values = [r['return_ms'] for r in results if r['status']=='measured']
result = {'capture':str(p),'target':'Shady Guy cyan hat and outline', 'resumes':len(results),
          'measured_resumes':len(values),'return_ms':{'median':float(np.median(values)),
            'p95':float(np.quantile(values,.95)),'min':min(values),'max':max(values)} if values else None,
          'screen_frame_interval_ms_median':float(np.median(np.diff([r['screen_time'] for r in rows if 'screen_time' in r]))*1000),
          'transitions':results,
          'limits':['Pixel capture and raw pause flag sampled externally; this includes game render and capture phase.',
                    'Previous one-second delay was reported by the user, not measured in a matched before capture.']}
(p/'escape-analysis.json').write_text(json.dumps(result,indent=2))
(p/'icon-presence.json').write_text(json.dumps([{'t':r['t'],'screen_time':r.get('screen_time'),'paused':r.get('paused'),
    'icon':r['icon'],'cyan_pixels':r.get('cyan_pixels'),'box':r.get('icon_box')} for r in rows]))
print(json.dumps(result,indent=2))

# Annotated contact sheets around three representative transitions.
if values:
    measured = [r for r in results if r['status']=='measured']
    selected = [min(measured,key=lambda r:r['return_ms']),
                min(measured,key=lambda r:abs(r['return_ms']-np.median(values))),
                max(measured,key=lambda r:r['return_ms'])]
    sheet = Image.new('RGB',(6*370,3*395),'#202020')
    draw = ImageDraw.Draw(sheet)
    with (p/'frames.bin').open('rb') as stream:
        for row_index,event in enumerate(selected):
            t = event['resume_t']
            candidates = [r for r in rows if 'screen_time' in r]
            chosen = [min(candidates,key=lambda r:abs(r['screen_time']-(t+offset))) for offset in [-.025,0,.025,.05,.075,.1]]
            for col,r in enumerate(chosen):
                stream.seek(r['offset'])
                frame = Image.open(io.BytesIO(stream.read(r['length']))).convert('RGB')
                if r.get('icon_box'):
                    ImageDraw.Draw(frame).rectangle(r['icon_box'],outline='magenta',width=2)
                frame.thumbnail((365,365))
                x,y = col*370,row_index*395
                sheet.paste(frame,(x,y+28))
                draw.text((x+4,y+4),f"{(r['screen_time']-t)*1000:+.1f}ms pause={r['paused']} icon={r['icon']}",fill='white')
    sheet.save(p/'escape-transitions.jpg',quality=92)
