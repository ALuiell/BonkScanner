
"""Elevated owned-target test: frozen recovery helper independent of game.
No user gameplay, no desktop input, no changes beyond temporary own target SACL.
"""
from pathlib import Path
import ctypes, json, os, subprocess, sys, time
sys.path.insert(0,r"F:\Python\BonkScanner_validator\src")
from bonkscanner_validator.launcher import Process
from bonkscanner_validator.audit_settings import AuditSettings, security_privilege
from bonkscanner_validator.security_audit import _log_state
from bonkscanner_validator.audit_recovery import _NativeStream
import msvcrt
import win32pipe

OUT=Path(r"F:\Python\BonkScanner\agent tasks\validator-stabilization-2026-11-17\acceptance\live-game-20261117-fixed\frozen_recovery_owned_diagnostic.json")
EXE=r"F:\Python\BonkScanner\scratch\validator-livefix-dist\BonkScanner_Validator_LiveFix.exe"
SCRIPT=r"F:\Python\BonkScanner_validator\scripts\security_audit_acceptance.py"
CREATE_NO_WINDOW=0x08000000

def messages(process,deadline_sec):
    end=time.monotonic()+deadline_sec;raw=b"";states=[]
    while time.monotonic()<end and b"\n" not in raw:
        available=0
        try:_,available,_=win32pipe.PeekNamedPipe(msvcrt.get_osfhandle(process.stdout.fileno()),0)
        except Exception as exc:
            states.append({"error":type(exc).__name__});break
        if available:
            raw+=process.stdout.read(min(available,4096))
        elif process.poll() is not None:
            states.append({"exited":process.returncode})
            break
        else:time.sleep(.025)
    return raw,states

def main():
    current=Process.open(os.getpid())
    try:
        if not current.elevated():raise PermissionError("run this owned stand elevated through normal UAC")
        parent=current.identity
        target=subprocess.Popen([sys.executable,"-I","-B",SCRIPT,"target"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,creationflags=CREATE_NO_WINDOW)
        try:
            address=target.stdout.readline().strip()
            if not address:raise RuntimeError("owned target never started")
            tp=Process.open(target.pid)
            try:
                identity=tp.identity
                with security_privilege():
                    settings=AuditSettings(target.pid, identity.created,process_name=Path(sys.executable).name)
                    try:before=(settings.policy().flags,settings.sacl())
                    finally:settings.close()
                command=[EXE,"--validator-audit-recovery",str(parent.pid),str(parent.created),
                         str(identity.pid),str(identity.created)]
                environment={**os.environ,"PYINSTALLER_RESET_ENVIRONMENT":"1"}
                t0=time.monotonic()
                p=subprocess.Popen(command,cwd=str(Path(EXE).parent),env=environment,
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,
                                   creationflags=CREATE_NO_WINDOW)
                try:
                    first,debug=messages(p,18)
                    elapsed=round(time.monotonic()-t0,3)
                    status={"elapsedToReplyOrExitSec":elapsed,"helperPid":p.pid,
                            "exitedBeforeResponse":p.poll(),
                            "readyLine":first[:200].decode("ascii",errors="replace").strip(),
                            "diagnostic":debug}
                    if b'"armed":true' in first:
                        p.stdin.write(b"X");p.stdin.flush()
                        second,debug2=messages(p,6)
                        status["restorationReply"]=second[:200].decode("ascii",errors="replace").strip()
                        status["postStopDiagnostics"]=debug2
                    else:
                        status["status"]="FAIL_NO_ARMED"
                    p.stdin.close()
                    try:p.wait(6)
                    except subprocess.TimeoutExpired:
                        status["status"]="FAIL_TIMEOUT"
                    status["finalExit"]=p.poll()
                finally:
                    if p.poll() is None:p.terminate()
                    try:p.wait(3)
                    except subprocess.TimeoutExpired:p.kill()
                    p.stdout.close();p.stderr.close()
                with security_privilege():
                    settings=AuditSettings(target.pid,identity.created,process_name=Path(sys.executable).name)
                    try:after=(settings.policy().flags,settings.sacl())
                    finally:settings.close()
                status["baselineRestored"]=before==after
                status["status"]=("PASS" if status.get("status") is None and status["baselineRestored"] and
                                        '"restoration":"verified"' in status.get("restorationReply","") else status.get("status","FAIL_RESTORATION"))
                OUT.write_text(json.dumps(status,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
                print(json.dumps(status,indent=2,ensure_ascii=False))
            finally:tp.close()
        finally:
            if not target.stdin.closed:
                target.stdin.close()
            try:target.wait(5)
            except subprocess.TimeoutExpired:target.kill()
            target.stdout.close();target.stderr.close()
    finally:current.close()
if __name__=="__main__":
    main()

