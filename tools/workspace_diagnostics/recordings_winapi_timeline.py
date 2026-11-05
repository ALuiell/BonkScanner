
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
import ctypes, json, time
from pathlib import Path
import win32gui,win32con
def state():
    for _ in range(10):
        try:return json.loads(output_path('recordings-ui-state.json').read_text())
        except ValueError:time.sleep(.02)
    raise RuntimeError('State unavailable')
hwnd=state()['hwnd']
assert win32gui.GetWindowText(hwnd)=='BonkScanner Recordings responsiveness probe'
def post(message,x,y,flags=0):
    scale=win32gui.GetClientRect(hwnd)[2]/state()['width']
    win32gui.PostMessage(hwnd,message,flags,round(x*scale)|(round(y*scale)<<16))
def click(x,y):
    post(win32con.WM_LBUTTONDOWN,x,y,1);post(win32con.WM_LBUTTONUP,x,y);time.sleep(.5)
def widget(name,fx=.5,fy=.5):
    x,y,w,h=state()['rects'][name];click(x+w*fx,y+h*fy)
def drag(name,fy):
    x,y,w,h=state()['rects'][name]
    post(win32con.WM_LBUTTONDOWN,x+w*.1,y+h*fy,1)
    for i in range(2,9):
        post(win32con.WM_MOUSEMOVE,x+w*i/10,y+h*fy,1);time.sleep(.04)
    post(win32con.WM_LBUTTONUP,x+w*.8,y+h*fy);time.sleep(.5)
out={}
# Open Compare from the observed native tab strip before the drag.
click(240,22)
widget('comp_change')
before=state()['a_index'];drag('comp_timeline',.25)
out['compare_indices']=[before,state()['a_index'],state()['b_index']]
assert state()['a_index']!=before
click(120,22);assert state()['tab']==1
before=state()['rec_index'];drag('rec_scrubber',.5)
out['recordings_indices']=[before,state()['rec_index']]
assert state()['rec_index']!=before
# Use native scroll messages over the library without moving the real cursor.
x,y,w,h=state()['rects']['rec_list']
scale=win32gui.GetClientRect(hwnd)[2]/state()['width']
sx,sy=win32gui.ClientToScreen(hwnd,(round((x+w/2)*scale),round((y+h/2)*scale)))
win32gui.PostMessage(hwnd,win32con.WM_MOUSEWHEEL,((-600)&0xffff)<<16,(sx&0xffff)|((sy&0xffff)<<16))
time.sleep(.5)
for fx in (.15,.3,.45,.65,.85):widget('rec_details',fx,.04)
out['recordings_detail']=state()['rec_detail']
click(240,22)
for fx in (.12,.2,.27,.34,.42):widget('comp_details',fx,.04)
out['compare_detail']=state()['comp_detail']
output_path('recordings-winapi-timeline.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out))
