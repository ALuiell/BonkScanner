
"""User-space Scanner-style Controller -> UAC worker lifecycle smoke.

Does not launch the game, perform desktop input, set clock, or connect to the internet.
"""
from pathlib import Path
import json
import sys
import time

sys.path.insert(0,r"F:\Python\BonkScanner_validator\src")
from bonkscanner_validator.controller import ValidatorController

out_path=Path(r"F:\Python\BonkScanner\agent tasks\validator-stabilization-2026-11-17\acceptance\controller_windows_uac_second_pass.json")
controller=ValidatorController(scanner_version="development")
rows=[]
try:
    for attempt in range(2):
        accepted=controller.enable(base_url="",protocol_version="3")
        if not accepted:
            raise RuntimeError(f"controller enable failed at attempt {attempt+1}")
        started=time.monotonic()
        ready=False
        last=None
        while time.monotonic()-started < 25:
            last=controller.snapshot()
            if last["state"] in ("waiting_game","observing"):
                ready=True
                break
            if last["state"] in ("stopping","stopped","disabled") and last.get("error"):
                break
            time.sleep(.05)
        worker=controller._worker
        pid=(getattr(getattr(worker,"process",None),"identity",None).pid
             if getattr(worker,"process",None) is not None else None)
        stop_started=time.monotonic()
        done_immediately=controller.disable(timeout=0)
        states=[]
        finish=None
        while time.monotonic()-stop_started < 12:
            snap=controller.snapshot()
            row=(snap["state"],snap["busy"],snap["enabled"])
            if not states or states[-1]!=row:
                states.append(row)
            if not snap["busy"]:
                finish=snap
                break
            time.sleep(.05)
        rows.append({
            "attempt":attempt+1, "ready":ready, "initialState":last["state"] if last else None,
            "initialError":last.get("error") if last else None, "workerPid":pid,
            "disableReturnedImmediately":done_immediately,
            "states":[{"state":state,"busy":busy,"enabled":enabled} for state,busy,enabled in states],
            "terminalState":finish["state"] if finish else None,
            "terminalError":finish.get("error") if finish else None,
            "terminalBusy":finish["busy"] if finish else None,
            "stopSeconds":round(time.monotonic()-stop_started,3),
        })
        if not ready or finish is None or finish["state"]!="disabled":
            raise RuntimeError(f"native worker smoke attempt {attempt+1} did not settle cleanly: {rows[-1]}")
finally:
    controller.close(timeout=5)
    evidence={"status":"PASS" if len(rows)==2 and all(x["ready"] and x["terminalState"]=="disabled" for x in rows) else "PARTIAL",
              "environment":"ordinary Python Controller, real Windows RunAs worker; no MegaBonk, no packaged EXE",
              "cycles":rows}
    out_path.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(evidence,indent=2))

