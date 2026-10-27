"""Temporary read-only camera/screen probe; never sends game input."""
import ctypes
from ctypes import wintypes
import dataclasses
import io
import json
import math
from pathlib import Path
import sys
import time
import collections

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass
import mss
from PIL import Image

sys.path.insert(0, r"F:\Python\BonkScanner\src")
from infra.memory.map_marker_client import MapMarkerMemoryClient

out = Path(__file__).parent / time.strftime("capture-%H%M%S")
out.mkdir()
user = ctypes.windll.user32
user.GetForegroundWindow.restype = wintypes.HWND
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
client = MapMarkerMemoryClient("Megabonk.exe")
pid = client.memory._pm.process_id
windows = []
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def enumerate_window(hwnd, _):
    owner = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value == pid and user.IsWindowVisible(hwnd):
        windows.append(hwnd)
    return True
user.EnumWindows(CALLBACK(enumerate_window), 0)
if len(windows) != 1:
    raise RuntimeError(f"Expected one visible game window; got {len(windows)}")
hwnd = windows[0]
raw_read = client.memory.read_bytes
read_count = 0
def counted_read(address, size):
    global read_count
    read_count += 1
    return raw_read(address, size)
client.memory.read_bytes = counted_read
counts = collections.Counter()
rows = []
frame_offsets = []
last_scope = None
start = time.perf_counter()
cpu_start = time.process_time()
next_scope = start
next_report = start
deadline = start
active_seconds = 0.0
previous_active = None
print(json.dumps({"status": "armed", "output": str(out), "target_pid": pid,
                  "capture_hz": 120, "active_duration_seconds": 60,
                  "maximum_wall_seconds": 100}), flush=True)
try:
    with mss.mss() as capture, (out / "frames.bin").open("wb") as pixels, (out / "samples.jsonl").open("w", encoding="utf-8") as telemetry:
        while time.perf_counter() - start < 100 and active_seconds < 60:
            if (out.parent / "STOP").exists():
                break
            now = time.perf_counter()
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(owner))
            if owner.value != pid:
                counts["game_not_foreground"] += 1
                previous_active = None
                time.sleep(.05)
                deadline = time.perf_counter()
                continue
            rect = wintypes.RECT()
            user.GetClientRect(hwnd, ctypes.byref(rect))
            origin = wintypes.POINT(0, 0)
            user.ClientToScreen(hwnd, ctypes.byref(origin))
            row = {"t": now - start, "read_count_before": read_count}
            poll_start = time.perf_counter()
            try:
                if now >= next_scope:
                    frame = client.poll(client_width=rect.right, client_height=rect.bottom,
                                        display_scale=1, minimap_enabled=True)
                    projection = frame.minimap_projection
                    scope = frame.map_scope
                    row["scope_changed"] = last_scope is not None and scope != last_scope
                    counts["scope_changes"] += row["scope_changed"]
                    last_scope = scope
                    next_scope = now + .5
                else:
                    projection = client._read_minimap_projection(client._player_ptr, rect.right, rect.bottom, 1)
                row["poll_ms"] = (time.perf_counter() - poll_start) * 1000
                row["pose_time"] = (poll_start + time.perf_counter()) / 2 - start
                if projection is None:
                    counts["projection_missing"] += 1
                    previous_active = None
                else:
                    row["projection"] = dataclasses.asdict(projection)
                    box = projection.content_rect
                    crop = {"left": origin.x + math.floor(box.left) - 8,
                            "top": origin.y + math.floor(box.top) - 8,
                            "width": math.ceil(box.width) + 16,
                            "height": math.ceil(box.height) + 16}
                    # Store only the minimap region, only while the game owns focus.
                    shot_start = time.perf_counter()
                    shot = capture.grab(crop)
                    shot_end = time.perf_counter()
                    row["screen_time"] = (shot_start + shot_end) / 2 - start
                    row["capture_ms"] = (shot_end - shot_start) * 1000
                    jpg = io.BytesIO()
                    Image.frombytes("RGB", shot.size, shot.rgb).save(jpg, "JPEG", quality=94, subsampling=0)
                    data = jpg.getvalue()
                    row["offset"] = pixels.tell()
                    row["length"] = len(data)
                    row["crop"] = crop
                    pixels.write(data)
                    counts["captured"] += 1
                    if previous_active is not None:
                        active_seconds += min(.1, now - previous_active)
                    previous_active = now
            except Exception as exc:
                counts[type(exc).__name__] += 1
                row["error"] = type(exc).__name__ + ": " + str(exc)
                previous_active = None
                next_scope = 0
            row["read_calls"] = read_count - row.pop("read_count_before")
            row["total_ms"] = (time.perf_counter() - now) * 1000
            telemetry.write(json.dumps(row, separators=(",", ":")) + "\n")
            rows.append(row)
            if now >= next_report:
                telemetry.flush()
                print(json.dumps({"status": "capturing", "wall_s": round(now-start, 1),
                                  "active_s": round(active_seconds, 1), "frames": counts["captured"]}), flush=True)
                next_report = now + 15
            deadline += 1 / 120
            if deadline < time.perf_counter() - .025:
                counts["schedule_resets"] += 1
                deadline = time.perf_counter()
            time.sleep(max(0, deadline - time.perf_counter()))
finally:
    client.close()
    summary = {"wall_s": time.perf_counter()-start, "active_s": active_seconds,
               "cpu_s": time.process_time()-cpu_start, "read_calls": read_count,
               "counts": dict(counts), "output": str(out)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)
