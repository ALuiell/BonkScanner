
"""Elevated frozen recovery test against the ALREADY RUNNING paused MegaBonk.

No game memory writes, no restart, no clock adjustments, no focus or input.
The only temporary action is the normal Validator audit policy/SACL arming.
"""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
sys.path.insert(0,r"F:\Python\BonkScanner_validator\src")
from bonkscanner_validator.launcher import Process
from bonkscanner_validator.audit_settings import AuditSettings,security_privilege
import msvcrt,win32pipe

OUT=Path(r"F:\Python\BonkScanner\agent tasks\validator-stabilization-2026-11-17\acceptance\live-game-20261117-fixed\frozen_recovery_game_probe_stage.json")
EXE=r"F:\Python\BonkScanner\scratch\validator-recoveryprobe-dist\BonkScanner_Validator_LiveFix.exe"

def receive(p,seconds):
    deadline=time.monotonic()+seconds
    raw=b""
    error=None
    while time.monotonic()<deadline and b"\n" not in raw:
        try:
            _,n,_=win32pipe.PeekNamedPipe(msvcrt.get_osfhandle(p.stdout.fileno()),0)
        except Exception as exc:
            error={"name":type(exc).__name__,"winerror":getattr(exc,"winerror",None),"message":str(exc)[:300]}
            break
        if n: raw+=p.stdout.read(min(n,4096))
        elif p.poll() is not None:break
        else:time.sleep(.02)
    return raw.split(b"\n",1)[0].decode("ascii",errors="replace"),error

def snap(pid,created):
    with security_privilege():
        settings=AuditSettings(pid,created,process_name="Megabonk.exe")
        try:return settings.policy().flags,settings.sacl()
        finally:settings.close()

def main():
    parent=Process.open(os.getpid())
    target=Process.open(29100)
    try:
        assert parent.elevated(),"Elevated UAC required"
        assert Path(target.identity.executable).name.casefold()=="megabonk.exe","Wrong game process"
        initial=snap(target.identity.pid,target.identity.created)
        args=[EXE,"--validator-audit-recovery",str(parent.identity.pid),str(parent.identity.created),
              str(target.identity.pid),str(target.identity.created)]
        begin=time.monotonic()
        helper=subprocess.Popen(args,cwd=str(Path(EXE).parent),
                                env={**os.environ,"PYINSTALLER_RESET_ENVIRONMENT":"1"},
                                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                bufsize=0,creationflags=0x08000000)
        result={"scope":"native packaged recovery bootstrap on existing paused MegaBonk, read-only game + owned audit SACL",
                "helperPid":helper.pid,"gamePid":target.identity.pid}
        try:
            first,err=receive(helper,18)
            result["startupSeconds"]=round(time.monotonic()-begin,3)
            result["firstReply"]=first
            result["startupReadError"]=err
            result["childExitAtFirstReply"]=helper.poll()
            if '"armed":true' in first:
                active=snap(target.identity.pid,target.identity.created)
                result["auditPolicyActive"]=active[0]
                result["activeSaclChanged"]=active[1]!=initial[1]
                helper.stdin.write(b"X");helper.stdin.flush()
                second,err=receive(helper,5)
                result["stopReply"]=second
                result["stopReadError"]=err
            else:
                result["status"]="FAILED_NO_ARMED_REPLY"
            helper.stdin.close()
            try:helper.wait(timeout=4)
            except subprocess.TimeoutExpired:
                result["timeoutDuringClose"]=True
            result["exitCode"]=helper.poll()
        finally:
            if helper.poll() is None:helper.terminate()
            try:helper.wait(timeout=3)
            except subprocess.TimeoutExpired:helper.kill()
            helper.stdout.close();helper.stderr.close()
        restored=snap(target.identity.pid,target.identity.created)
        result["policyBefore"]=initial[0]
        result["policyAfter"]=restored[0]
        result["saclBeforeSha256"]=hashlib.sha256(initial[1]).hexdigest()
        result["saclAfterSha256"]=hashlib.sha256(restored[1]).hexdigest()
        result["restored"]=restored==initial
        if '"armed":true' in result.get("firstReply","") and '"restoration":"verified"' in result.get("stopReply","") and result["restored"]:
            result["status"]="PASS"
        OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print(json.dumps(result,indent=2,ensure_ascii=False))
    finally:
        target.close();parent.close()
if __name__=="__main__":main()

