
"""Read-only Win32 snapshots of owned Scanner onefile child process lifetime.

Retains PROCESS_QUERY_LIMITED_INFORMATION handles to read actual exit codes
after short-lived PyInstaller helper processes disappear. No game interaction.
"""
import ctypes as C, json, time
from ctypes import wintypes as W
from pathlib import Path

OUT=Path(r"F:\Python\BonkScanner\agent tasks\validator-stabilization-2026-11-17\acceptance\live-game-20261117-observertrace\native_worker_exits.jsonl")
K=C.WinDLL("kernel32",use_last_error=True)
class PROCESSENTRY32W(C.Structure):
    _fields_=[("dwSize",W.DWORD),("cntUsage",W.DWORD),("th32ProcessID",W.DWORD),
              ("th32DefaultHeapID",C.c_void_p),("th32ModuleID",W.DWORD),
              ("cntThreads",W.DWORD),("th32ParentProcessID",W.DWORD),
              ("pcPriClassBase",W.LONG),("dwFlags",W.DWORD),
              ("szExeFile",W.WCHAR*260)]
class FILETIME(C.Structure):
    _fields_=[("low",W.DWORD),("high",W.DWORD)]
K.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD]
K.CreateToolhelp32Snapshot.restype=W.HANDLE
K.Process32FirstW.argtypes=[W.HANDLE,C.POINTER(PROCESSENTRY32W)]
K.Process32FirstW.restype=W.BOOL
K.Process32NextW.argtypes=[W.HANDLE,C.POINTER(PROCESSENTRY32W)]
K.Process32NextW.restype=W.BOOL
K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]
K.OpenProcess.restype=W.HANDLE
K.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
K.GetExitCodeProcess.restype=W.BOOL
K.GetProcessTimes.argtypes=[W.HANDLE]+[C.POINTER(FILETIME)]*4
K.GetProcessTimes.restype=W.BOOL
K.CloseHandle.argtypes=[W.HANDLE]
K.CloseHandle.restype=W.BOOL

def snap():
    h=K.CreateToolhelp32Snapshot(2,0)
    if not h or h==C.c_void_p(-1).value:return None
    rows={}
    try:
        row=PROCESSENTRY32W();row.dwSize=C.sizeof(row)
        valid=K.Process32FirstW(h,C.byref(row))
        while valid:
            if row.szExeFile.casefold().startswith("bonkscanner_validator_"):
                rows[int(row.th32ProcessID)]=(row.szExeFile,int(row.th32ParentProcessID))
            valid=K.Process32NextW(h,C.byref(row))
    finally:K.CloseHandle(h)
    return rows

def main():
    handles={}
    start=time.monotonic()
    OUT.parent.mkdir(exist_ok=True,parents=True)
    with OUT.open("w",encoding="utf-8") as file:
        while time.monotonic()-start<600:
            t=round(time.monotonic()-start,3)
            rows=snap()
            if rows is None:
                file.write(json.dumps({"t":t,"error":"snapshot_failed"})+"\n");file.flush()
                time.sleep(.05);continue
            for pid,(name,ppid) in rows.items():
                if pid not in handles:
                    h=K.OpenProcess(0x1000,False,pid)
                    times=[FILETIME() for _ in range(4)]
                    created=None
                    if h and K.GetProcessTimes(h,*map(C.byref,times)):
                        created=((int(times[0].high)<<32)|int(times[0].low))
                    handles[pid]=(h,t,name,ppid,created)
                    file.write(json.dumps({"t":t,"event":"new","pid":pid,"parentPid":ppid,
                                           "name":name,"createdFiletime":created})+"\n")
                    file.flush()
            for pid,(h,first,name,ppid,created) in list(handles.items()):
                if pid not in rows:
                    status=W.DWORD()
                    code=None
                    if h and K.GetExitCodeProcess(h,C.byref(status)):
                        code=status.value
                    file.write(json.dumps({"t":t,"event":"exited","pid":pid,
                                           "parentPid":ppid,"createdFiletime":created,
                                           "exitCode":code,"lifeSeconds":round(t-first,3)})+"\n")
                    file.flush()
                    if h:K.CloseHandle(h)
                    del handles[pid]
            time.sleep(.05)
        for pid,(h,first,name,ppid,created) in handles.items():
            status=W.DWORD()
            code=int(status.value) if h and K.GetExitCodeProcess(h,C.byref(status)) else None
            file.write(json.dumps({"t":round(time.monotonic()-start,3),"event":"final",
                                   "pid":pid,"parentPid":ppid,"exitCode":code})+"\n")
            if h:K.CloseHandle(h)
    print("Wrote",OUT)
if __name__=="__main__":main()

