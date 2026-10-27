import contextlib
import io
import json
import math
import numpy as np
from PIL import Image
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as a

def components(mask):
    todo=set(zip(*np.nonzero(mask)))
    groups=[]
    while todo:
        first=todo.pop()
        queue=[first]
        group=[first]
        while queue:
            y,x=queue.pop()
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    point=(y+dy,x+dx)
                    if point in todo:
                        todo.remove(point)
                        queue.append(point)
                        group.append(point)
        if len(group)>=8:
            ys,xs=zip(*group)
            if 4<=max(xs)-min(xs)<=20 and 4<=max(ys)-min(ys)<=20:
                groups.append((float(np.mean(xs)),float(np.mean(ys)),len(group)))
    return groups

observed={round(o['frame_t'],6):o for o in a.observations}
world=None
native=[]
with (a.p/'frames.bin').open('rb') as stream:
    for r in a.pose_rows:
        blue=observed.get(round(r['t'],6))
        if blue is None or 'offset' not in r:
            continue
        stream.seek(r['offset'])
        image=np.array(Image.open(io.BytesIO(stream.read(r['length']))))
        q=r['projection']
        cx=q['center_x']-r['crop']['left']
        cy=q['center_y']-r['crop']['top']
        yy,xx=np.indices(image.shape[:2])
        mask=((image[:,:,0]>155)&(image[:,:,1]>115)&(image[:,:,2]<100)
              &(image[:,:,1].astype(float)>.65*image[:,:,0])
              &((xx-cx)**2+(yy-cy)**2<(q['radius']-15)**2))
        candidates=[]
        for x,y,n in components(mask):
            sx=q['content_rect']['width']/(2*q['orthographic_size']*q['aspect'])
            sy=q['content_rect']['height']/(2*q['orthographic_size'])
            vx=(x-cx)/sx; vy=-(y-cy)/sy
            wx=q['camera_world_x']+vx*q['camera_right_x']+vy*q['camera_up_x']
            wz=q['camera_world_z']+vx*q['camera_right_z']+vy*q['camera_up_z']
            candidates.append((x-cx,y-cy,wx,wz,n))
        if not candidates:
            continue
        if world is None:
            c=min(candidates,key=lambda c:np.hypot(c[0]-blue['x'],c[1]-blue['y']))
            world=np.array(c[2:4])
        c=min(candidates,key=lambda c:np.linalg.norm(np.array(c[2:4])-world))
        if np.linalg.norm(np.array(c[2:4])-world)>12:
            continue
        native.append({'t':r['screen_time'],'x':c[0],'y':c[1],'frame_t':r['t'],
                       'width':q['content_rect']['width'],'height':q['content_rect']['height']})

# Repeat the same delay fit for a native yellow icon captured in the same frames.
blue_t=a.t.copy(); blue_xy=a.xy.copy()
a.t=np.array([n['t'] for n in native])
a.xy=np.array([[n['x'],n['y']] for n in native])
a.width=np.array([n['width'] for n in native]); a.height=np.array([n['height'] for n in native])
curves=[a.fit(d)[0] for d in a.delays]
delay=int(a.delays[np.argmin(curves)])
rms,solution,predicted,residual=a.fit(delay)
keep=residual<max(2,np.quantile(residual,.95))
curves=[a.fit(d,keep)[0] for d in a.delays]
delay=int(a.delays[np.argmin(curves)])
rms,solution,predicted,residual=a.fit(delay,keep)
dt=np.diff(a.t); motion=np.linalg.norm(np.diff(a.xy,axis=0),axis=1)
change_times=a.t[1:][(dt<.02)&(motion>.45)]
intervals=np.diff(change_times); intervals=intervals[(intervals>.005)&(intervals<.1)]

def change_stats(t,xy,threshold):
    dt=np.diff(t); motion=np.linalg.norm(np.diff(xy,axis=0),axis=1)
    changed=t[1:][(dt<.02)&(motion>threshold)]
    gaps=np.diff(changed); gaps=gaps[(gaps>.005)&(gaps<.1)]
    return a.stats(gaps*1000)

result={'native_observations':len(native),'native_time_range':[float(a.t.min()),float(a.t.max())],
        'native_apparent_delay_ms':delay,'native_fit_rms_pixels':rms,
        'overlay_extra_delay_vs_native_ms':a.best_delay-delay,
        'native_position_change_interval_ms':a.stats(intervals*1000),
        'blue_change_interval_by_threshold':{str(v):change_stats(blue_t,blue_xy,v) for v in [.25,.45,.75,1.0]},
        'native_change_interval_by_threshold':{str(v):change_stats(a.t,a.xy,v) for v in [.25,.45,.75,1.0]},
        'native_world_position':solution[:2].tolist()}
(a.output/'native_analysis.json').write_text(json.dumps(result,indent=2))
(a.output/'native_positions.json').write_text(json.dumps(native))
print(json.dumps(result,indent=2))
