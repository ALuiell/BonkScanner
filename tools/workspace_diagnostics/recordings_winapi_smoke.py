
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
import win32gui, win32ui, win32con
from PySide6.QtGui import QImage

def state():
    for _ in range(10):
        try:return json.loads(output_path('recordings-ui-state.json').read_text('utf-8'))
        except (OSError,ValueError):time.sleep(.03)
    raise RuntimeError('Missing probe state')
s=state(); hwnd=s['hwnd']
assert win32gui.GetWindowText(hwnd)=='BonkScanner Recordings responsiveness probe'
def click_at(x,y):
    width=win32gui.GetClientRect(hwnd)[2]
    scale=width/state()['width']
    point=round(x*scale)|(round(y*scale)<<16)
    win32gui.PostMessage(hwnd,win32con.WM_LBUTTONDOWN,win32con.MK_LBUTTON,point)
    win32gui.PostMessage(hwnd,win32con.WM_LBUTTONUP,0,point)
    time.sleep(.6)
def click(name,fx=.5,fy=.5):
    x,y,w,h=state()['rects'][name];click_at(x+w*fx,y+h*fy)
def text(value):
    for ch in value:win32gui.PostMessage(hwnd,win32con.WM_CHAR,ord(ch),1)
    time.sleep(.6)
def screenshot(path):
    left,top,right,bottom=win32gui.GetWindowRect(hwnd)
    width,height=right-left,bottom-top
    dc=win32gui.GetWindowDC(hwnd); src=win32ui.CreateDCFromHandle(dc); dst=src.CreateCompatibleDC()
    bitmap=win32ui.CreateBitmap();bitmap.CreateCompatibleBitmap(src,width,height);dst.SelectObject(bitmap)
    result=ctypes.windll.user32.PrintWindow(hwnd,dst.GetSafeHdc(),2)
    assert result
    bmp=path.with_suffix('.bmp');bitmap.SaveBitmapFile(dst,str(bmp))
    assert QImage(str(bmp)).save(str(path))
    bmp.unlink()
    dst.DeleteDC();src.DeleteDC();win32gui.ReleaseDC(hwnd,dc);win32gui.DeleteObject(bitmap.GetHandle())
def ping():
    start=time.perf_counter()
    win32gui.SendMessageTimeout(hwnd,win32con.WM_NULL,0,0,win32con.SMTO_ABORTIFHUNG,1000)
    return round((time.perf_counter()-start)*1000,2)
out={}
# Native messages target only the probe HWND: no cursor movement or activation.
click_at(120,22);assert state()['tab']==1
if state()['rects']['rec_library'][0]<100:click('rec_library')
if state()['rec_query']:click('rec_search',.95,.5)
all_recordings_count=state()['rec_visible']
click('rec_search');text('Dice')
assert state()['rec_query']=='Dice';assert 0<state()['rec_visible']<all_recordings_count
out['recordings_search_visible']=state()['rec_visible']
out['recordings_ping_ms']=ping()
screenshot(output_path('recordings-winapi.png'))
# The native mouse path also exercises the edit's built-in clear button.
click('rec_search',.95,.5)
time.sleep(.6);assert state()['rec_query']=='';assert state()['rec_visible']==all_recordings_count
click('rec_list',.5,.10);time.sleep(1.5)
assert state()['rec_selected']
out['recordings_selected']=Path(state()['rec_selected']).name
click_at(240,22);assert state()['tab']==2
click('comp_change');click('comp_search_a');text('Dice')
assert state()['a_query']=='Dice';assert 0<state()['a_visible']<all_recordings_count
out['compare_search_visible']=state()['a_visible']
click('comp_list_a',.5,.10);time.sleep(1.5)
out['compare_selected_a']=Path(state()['a_selected']).name
out['compare_ping_ms']=ping()
screenshot(output_path('compare-winapi.png'))
output_path('recordings-winapi-smoke.json').write_text(json.dumps(out,indent=2),'utf-8')
print(json.dumps(out))
