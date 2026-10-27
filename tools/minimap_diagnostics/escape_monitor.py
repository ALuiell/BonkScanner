"""Bounded read-only minimap capture, including Escape menus."""
import collections
import ctypes
from ctypes import wintypes
import io
import json
import math
from pathlib import Path
import sys
import time
from _paths import capture_directory

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass
import mss
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from infra.memory.map_marker_client import MapMarkerMemoryClient
from infra.memory.game_data_client import GameDataClient

out = capture_directory('escape')
user = ctypes.windll.user32
user.GetForegroundWindow.restype = wintypes.HWND
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
client = MapMarkerMemoryClient('Megabonk.exe')
game = GameDataClient(memory=client.memory)
pause_fields = game._read_static_fields_cached(game.MY_TIME_TYPE_INFO_OFFSET)
if not pause_fields:
    raise RuntimeError('Pause flag unavailable')
pid = client.memory._pm.process_id
windows = []
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def enumerate_window(hwnd, _):
    owner = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value == pid and user.IsWindowVisible(hwnd):
        windows.append(hwnd)
    return True
user.EnumWindows(callback_type(enumerate_window), 0)
if len(windows) != 1:
    raise RuntimeError('Expected one visible game window')
hwnd = windows[0]
start = time.perf_counter()
cpu_start = time.process_time()
deadline = start
next_scope = start
next_report = start
crop = None
counts = collections.Counter()
paused_previous = None
active_s = 0.0
previous_active = None
print(json.dumps({'status':'armed','output':str(out),'capture_hz':120}), flush=True)
try:
    with mss.MSS() as capture, (out/'frames.bin').open('wb') as frames, (out/'samples.jsonl').open('w',encoding='utf-8') as telemetry:
        while time.perf_counter()-start < 100 and active_s < 60:
            now = time.perf_counter()
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(owner))
            if owner.value != pid:
                previous_active = None
                time.sleep(.05)
                deadline = time.perf_counter()
                continue
            row = {'t':now-start}
            try:
                read_start = time.perf_counter()
                paused = client.memory.read_u8(pause_fields + game.MY_TIME_PAUSED_OFFSET)
                if paused not in (0,1):
                    raise RuntimeError('Invalid pause value')
                row.update(paused=bool(paused),pause_time=(read_start+time.perf_counter())/2-start,
                           escape=bool(user.GetAsyncKeyState(0x1B)&0x8000))
                if paused_previous is not None and bool(paused) != paused_previous:
                    counts['pause_transitions'] += 1
                    print(json.dumps({'status':'pause_transition','paused':bool(paused),'t':round(now-start,3)}),flush=True)
                paused_previous = bool(paused)
                if now >= next_scope:
                    rect = wintypes.RECT()
                    user.GetClientRect(hwnd,ctypes.byref(rect))
                    origin = wintypes.POINT(0,0)
                    user.ClientToScreen(hwnd,ctypes.byref(origin))
                    frame = client.poll(client_width=rect.right,client_height=rect.bottom,minimap_enabled=True)
                    projection = frame.minimap_projection
                    if projection is not None:
                        box = projection.content_rect
                        crop = {'left':origin.x+math.floor(box.left)-8,'top':origin.y+math.floor(box.top)-8,
                                'width':math.ceil(box.width)+16,'height':math.ceil(box.height)+16}
                    next_scope = now+.1
                if client._full_map_ptr:
                    row['map_open'] = client.memory.read_i32(client._full_map_ptr+client.FULL_MAP_OPEN_COUNT_OFFSET)>0
                if crop is not None:
                    shot_start = time.perf_counter()
                    shot = capture.grab(crop)
                    shot_end = time.perf_counter()
                    jpg = io.BytesIO()
                    Image.frombytes('RGB',shot.size,shot.rgb).save(jpg,'JPEG',quality=94,subsampling=0)
                    data = jpg.getvalue()
                    row.update(screen_time=(shot_start+shot_end)/2-start,capture_ms=(shot_end-shot_start)*1000,
                               crop=crop,offset=frames.tell(),length=len(data))
                    frames.write(data)
                    counts['frames'] += 1
                    if previous_active is not None:
                        active_s += min(.1,now-previous_active)
                    previous_active = now
            except Exception as exc:
                row['error'] = f'{type(exc).__name__}: {exc}'
                counts['errors'] += 1
            telemetry.write(json.dumps(row,separators=(',',':'))+'\n')
            if now >= next_report:
                telemetry.flush()
                frames.flush()
                print(json.dumps({'status':'capturing','wall_s':round(now-start,1),'active_s':round(active_s,1),**counts}),flush=True)
                next_report = now+15
            deadline += 1/120
            if deadline < time.perf_counter()-.025:
                deadline = time.perf_counter()
            time.sleep(max(0,deadline-time.perf_counter()))
finally:
    client.close()
    result = {'wall_s':time.perf_counter()-start,'active_s':active_s,'cpu_s':time.process_time()-cpu_start,
              'counts':dict(counts),'output':str(out)}
    (out/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
