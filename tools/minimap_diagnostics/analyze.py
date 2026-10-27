"""Offline pixel tracking and camera-delay fit for the blue microwave."""
import io
import json
from pathlib import Path
import statistics
import sys
import numpy as np
from PIL import Image

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "capture-111030"
rows = [json.loads(line) for line in (p / "samples.jsonl").read_text().splitlines()]
start_time = float(sys.argv[2]) if len(sys.argv) > 2 else 76
end_time = float(sys.argv[3]) if len(sys.argv) > 3 else float('inf')
pose_rows = [r for r in rows if "projection" in r and start_time < r["t"] < end_time]
pose_time = np.array([r["pose_time"] for r in pose_rows])
poses = [r["projection"] for r in pose_rows]
fields = {name: np.array([v[name] for v in poses]) for name in
          ["camera_world_x", "camera_world_z", "camera_right_x", "camera_right_z", "camera_up_x", "camera_up_z", "orthographic_size", "aspect"]}
observations = []
with (p / "frames.bin").open("rb") as stream:
    for r in pose_rows:
        if "offset" not in r:
            continue
        stream.seek(r["offset"])
        a = np.array(Image.open(io.BytesIO(stream.read(r["length"]))))
        q = r["projection"]
        cx = q["center_x"] - r["crop"]["left"]
        cy = q["center_y"] - r["crop"]["top"]
        yy, xx = np.indices(a.shape[:2])
        interior = (xx-cx)**2 + (yy-cy)**2 < (q["radius"]-6)**2
        cyan = ((a[:,:,0] < 90) & (a[:,:,1] > 185) & (a[:,:,2] > 215)
                & (a[:,:,1].astype(float) > .8*a[:,:,2]) & interior)
        y, x = np.nonzero(cyan)
        if len(x) < 45:
            continue
        # One uncut microwave outline, excluding edge clipping and paused menus.
        if not (22 < x.max()-x.min() < 45 and 12 < y.max()-y.min() < 40):
            continue
        mx, my = x.mean(), y.mean()
        if np.hypot(mx-cx, my-cy) > q["radius"]-30:
            continue
        observations.append({"t":r["screen_time"], "x":mx-cx, "y":my-cy,
                             "pixels":len(x), "frame_t":r["t"],
                             "width":q["content_rect"]["width"],
                             "height":q["content_rect"]["height"]})

t = np.array([r["t"] for r in observations])
xy = np.array([[r["x"],r["y"]] for r in observations])
width = np.array([r["width"] for r in observations])
height = np.array([r["height"] for r in observations])
def fit(delay_ms, mask=None):
    ts = t-delay_ms/1000
    z = {name:np.interp(ts,pose_time,values) for name,values in fields.items()}
    sx=width/(2*z["orthographic_size"]*z["aspect"])
    sy=height/(2*z["orthographic_size"])
    n=len(t)
    A=np.zeros((2*n,4))
    A[0::2,0]=sx*z["camera_right_x"]
    A[0::2,1]=sx*z["camera_right_z"]
    A[0::2,2]=1
    A[1::2,0]=-sy*z["camera_up_x"]
    A[1::2,1]=-sy*z["camera_up_z"]
    A[1::2,3]=1
    b=np.empty(2*n)
    b[0::2]=sx*(z["camera_world_x"]*z["camera_right_x"]+z["camera_world_z"]*z["camera_right_z"])
    b[1::2]=-sy*(z["camera_world_x"]*z["camera_up_x"]+z["camera_world_z"]*z["camera_up_z"])
    rhs=xy.reshape(-1)+b
    keep=np.repeat(mask,2) if mask is not None else np.ones(2*n,dtype=bool)
    solution=np.linalg.lstsq(A[keep],rhs[keep],rcond=None)[0]
    predicted=(A@solution-b).reshape(-1,2)
    residual=np.linalg.norm(predicted-xy,axis=1)
    selected=residual[mask] if mask is not None else residual
    return float(np.sqrt(np.mean(selected**2))),solution,predicted,residual

if len(t) < 50:
    raise RuntimeError(f"Insufficient blue icon samples: {len(t)}")
delays=np.arange(-30,151,1)
initial=[fit(d)[0] for d in delays]
best_delay=int(delays[np.argmin(initial)])
rms,solution,predicted,residual=fit(best_delay)
mask=residual<max(3,np.quantile(residual,.95))
curve=[fit(d,mask)[0] for d in delays]
best_delay=int(delays[np.argmin(curve)])
rms,solution,predicted,residual=fit(best_delay,mask)
zero_rms,_,_,_=fit(0,mask)

dt=np.diff(t)
motion=np.linalg.norm(np.diff(xy,axis=0),axis=1)
continuous=dt<.020
changes=(motion>.45)&continuous
change_t=t[1:][changes]
change_dt=np.diff(change_t)
change_dt=change_dt[(change_dt>.005)&(change_dt<.1)]
def stats(v):
    v=np.asarray(v)
    return {"median":float(np.median(v)),"p95":float(np.quantile(v,.95)),"max":float(np.max(v))} if len(v) else None
projection_rows=[r for r in rows if "projection" in r and "offset" in r]
result={"observations":len(t), "inliers":int(mask.sum()), "time_range":[float(t.min()),float(t.max())],
        "apparent_camera_to_icon_delay_ms":best_delay,
        "best_fit_rms_pixels":rms,"zero_delay_fit_rms_pixels":zero_rms,
        "inferred_world_position":solution[:2].tolist(),"centroid_offset_pixels":solution[2:].tolist(),
        "residual_pixels":stats(residual[mask]),
        "screen_frame_interval_ms":stats(dt[continuous]*1000),
        "visible_position_change_interval_ms":stats(change_dt*1000),
        "position_changes":int(changes.sum()),
        "fast_poll_ms":stats([r["poll_ms"] for r in projection_rows if r["read_calls"]<100]),
        "capture_ms":stats([r["capture_ms"] for r in projection_rows]),
        "fit_curve":[[int(d),round(float(e),4)] for d,e in zip(delays,curve)],
        "limits":["Visual lag fit includes game render/capture phase; not direct in-process timer or paint instrumentation.",
                  "Position-change intervals depend on pixel threshold and camera motion.",
                  "Temporary probe itself adds read/capture load."]}
(p/"analysis.json").write_text(json.dumps(result,indent=2))
(p/"icon_positions.json").write_text(json.dumps(observations))
print(json.dumps({k:v for k,v in result.items() if k!='fit_curve'},indent=2))
