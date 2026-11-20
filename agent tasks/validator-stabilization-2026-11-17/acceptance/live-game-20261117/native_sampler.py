"""Owned native Windows 25-minute Scanner/Validator/MegaBonk resource probe.

Read-only process APIs and GameLab clock snapshots; no input or game mutations.
Writes samples incrementally so operator can inspect partial progress.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

K = C.WinDLL("kernel32", use_last_error=True)
PS = C.WinDLL("psapi", use_last_error=True)
DWORD=W.DWORD
HANDLE=W.HANDLE
MAX_PATH=260
class PROCESSENTRY32W(C.Structure):
    _fields_=[
        ("dwSize",DWORD),("cntUsage",DWORD),("th32ProcessID",DWORD),
        ("th32DefaultHeapID",C.c_void_p),("th32ModuleID",DWORD),
        ("cntThreads",DWORD),("th32ParentProcessID",DWORD),
        ("pcPriClassBase",W.LONG),("dwFlags",DWORD),
        ("szExeFile",W.WCHAR*MAX_PATH)]
class FILETIME(C.Structure):
    _fields_=[("low",DWORD),("high",DWORD)]
class MEMORY(C.Structure):
    _fields_=[("cb",DWORD),("pageFaults",DWORD)]+[
        (name,C.c_size_t) for name in (
            "peakWorkingSet","workingSet","peakPaged","paged",
            "peakNonPaged","nonPaged","pagefile","peakPagefile","privateBytes")]
K.CreateToolhelp32Snapshot.argtypes=(DWORD,DWORD)
K.CreateToolhelp32Snapshot.restype=HANDLE
K.Process32FirstW.argtypes=(HANDLE,C.POINTER(PROCESSENTRY32W))
K.Process32FirstW.restype=W.BOOL
K.Process32NextW.argtypes=(HANDLE,C.POINTER(PROCESSENTRY32W))
K.Process32NextW.restype=W.BOOL
K.CloseHandle.argtypes=(HANDLE,)
K.CloseHandle.restype=W.BOOL
K.OpenProcess.argtypes=(DWORD,W.BOOL,DWORD)
K.OpenProcess.restype=HANDLE
K.GetProcessTimes.argtypes=(HANDLE,C.POINTER(FILETIME),C.POINTER(FILETIME),
                             C.POINTER(FILETIME),C.POINTER(FILETIME))
K.GetProcessTimes.restype=W.BOOL
K.GetProcessHandleCount.argtypes=(HANDLE,C.POINTER(DWORD))
K.GetProcessHandleCount.restype=W.BOOL
PS.GetProcessMemoryInfo.argtypes=(HANDLE,C.POINTER(MEMORY),DWORD)
PS.GetProcessMemoryInfo.restype=W.BOOL
NAMES={"bonkscanner_validator_secondpass.exe","bonkscanner_validator_secondpass.exe",
       "bonkscanner_validator_secondpass.exe","megabonk.exe"}
# Win32 process names may be truncated by reporting clients; match known basename prefix.
def included(name):
    return name.casefold()=="megabonk.exe" or name.casefold().startswith("bonkscanner_validator_secondpass")

def ticks(x):
    return (int(x.high)<<32)+int(x.low)

def snapshot():
    h=K.CreateToolhelp32Snapshot(2,0)
    if h in (None,C.c_void_p(-1).value): return [],"CreateToolhelp32Snapshot"
    result=[]
    try:
        row=PROCESSENTRY32W()
        row.dwSize=C.sizeof(row)
        ok=K.Process32FirstW(h,C.byref(row))
        while ok:
            if included(row.szExeFile):
                item={"pid":int(row.th32ProcessID),"ppid":int(row.th32ParentProcessID),
                      "name":row.szExeFile,"threads":int(row.cntThreads),
                      "createdFiletime":None,"cpuSeconds":None,
                      "handles":None,"privateBytes":None,"workingSetBytes":None}
                proc=K.OpenProcess(0x1000,False,row.th32ProcessID)
                if proc:
                    try:
                        ft=[FILETIME() for _ in range(4)]
                        if K.GetProcessTimes(proc,*map(C.byref,ft)):
                            item["createdFiletime"]=ticks(ft[0])
                            item["cpuSeconds"]=(ticks(ft[2])+ticks(ft[3]))/10_000_000
                        count=DWORD()
                        if K.GetProcessHandleCount(proc,C.byref(count)):item["handles"]=int(count.value)
                        mem=MEMORY();mem.cb=C.sizeof(mem)
                        if PS.GetProcessMemoryInfo(proc,C.byref(mem),mem.cb):
                            item["privateBytes"]=int(mem.privateBytes)
                            item["workingSetBytes"]=int(mem.workingSet)
                    finally: K.CloseHandle(proc)
                result.append(item)
            ok=K.Process32NextW(h,C.byref(row))
    finally: K.CloseHandle(h)
    return result,None

def safe_clock():
    try:
        cp=subprocess.run(
          ["py","-3.12","lab.py","game","time","get"],
          cwd=r"F:\Python\BonkScanner_experiments",
          capture_output=True,text=True,encoding="utf-8",
          errors="replace",timeout=12)
        if cp.returncode!=0:return {"error":"gamelab_failed","returncode":cp.returncode}
        obj=json.loads(cp.stdout)
        if not obj.get("ok"):return {"error":"gamelab_unavailable"}
        data=obj["result"]
        return {key:data.get(key) for key in (
          "stage","run","swarm","difficulty","simulation_time","paused")}
    except Exception as exc:return {"error":type(exc).__name__}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--duration",type=int,default=1500)
    parser.add_argument("--interval",type=float,default=5.)
    parser.add_argument("--clock-interval",type=float,default=60.)
    parser.add_argument("--dir",type=Path,required=True)
    args=parser.parse_args()
    args.dir.mkdir(parents=True,exist_ok=True)
    dest=args.dir/"resources_25m.jsonl"
    started=time.monotonic()
    previous={}
    last_clock_at=None
    count=0
    with dest.open("a",encoding="utf-8") as stream:
        while True:
            t=time.monotonic()
            if t-started>args.duration and count>0:break
            current,error=snapshot()
            for item in current:
                key=(item["pid"],item["createdFiletime"])
                old=previous.get(key)
                if old and item["cpuSeconds"] is not None and old["cpuSeconds"] is not None:
                    dt=max(.001,t-old["time"])
                    item["cpuPercentOneCore"]=round(
                       100*max(0.,item["cpuSeconds"]-old["cpuSeconds"])/dt,2)
                else:item["cpuPercentOneCore"]=None
                if item["cpuSeconds"] is not None:
                    previous[key]={"cpuSeconds":item["cpuSeconds"],"time":t}
            content={"elapsedSeconds":round(t-started,3),
                     "utc":datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                     "perfCounter":time.perf_counter(),"processes":current,
                     "snapshotError":error}
            if last_clock_at is None or t-last_clock_at>=args.clock_interval:
                content["gameClock"]=safe_clock()
                last_clock_at=t
            lines={}
            for path in args.dir.glob("*.jsonl"):
                if path.name==dest.name:continue
                stat=path.stat()
                lines[path.name]={"bytes":stat.st_size,
                                  "lastModifiedAgeSeconds":round(time.time()-stat.st_mtime,2)}
            content["traces"]=lines
            stream.write(json.dumps(content,separators=(",",":"),ensure_ascii=True)+"\n")
            stream.flush()
            count+=1
            until=started+count*args.interval
            wait=max(0,until-time.monotonic())
            if wait:time.sleep(wait)
    print(json.dumps({"status":"complete","samples":count,
                      "durationSeconds":round(time.monotonic()-started,3),
                      "path":str(dest)},ensure_ascii=False))

if __name__=="__main__":
    main()

