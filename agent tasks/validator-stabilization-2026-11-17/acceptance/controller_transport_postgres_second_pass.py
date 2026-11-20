
"""One synthetic Controller -> Transport -> local Django/PostgreSQL acceptance run.

Never logs enrollment tokens, private raw audit rows, or HTTP Authorization.
"""
from pathlib import Path
import copy
import json
import time
import urllib.request
import uuid

from bonkscanner_validator.controller import ValidatorController
from bonkscanner_validator.run_diagnostics import audit_summary
from bonkscanner_validator.security_audit import report
from bonkscanner_validator.transport import TransportManager

ROOT = Path(r"F:\Python\BonkScanner_validator_server\contract\v3\examples")
OUT = Path(r"F:\Python\BonkScanner\agent tasks\validator-stabilization-2026-11-17\acceptance")
BASE = "http://127.0.0.1:8043"

def example(name):
    return json.loads((ROOT / (name+".json")).read_text(encoding="utf-8"))

def get(path):
    try:
        with urllib.request.urlopen(BASE+path, timeout=5) as response:
            return response.status, response.read()
    except Exception as exc:
        return 0, repr(exc).encode()

transport = TransportManager(BASE, allow_loopback=True, protocol_version="3")
controller = ValidatorController()
controller._transport = transport
controller._protocol_version = "3"
started = {}
try:
    for suffix in ("old", "new"):
        b = copy.deepcopy(example("create_request")["binding"])
        rid = str(uuid.uuid4())
        b["localRunId"] = rid
        controller._event({"kind":"run_start", "binding":b})
        started[suffix]=rid
    for suffix, rid in started.items():
        controller._event({"kind": "payload", "localRunId": rid,
                           "payload": copy.deepcopy(example("normal_batch")["payload"])})
    base=example("normal_finish")
    summary = audit_summary(
        report("partial", ["policy_changed"], "preserved_external_change"),
        audit_armed=True,
    )
    for suffix in ("old", "new"):
        rid = started[suffix]
        p = copy.deepcopy(base["payload"])
        controller._event({"kind":"run_end", "localRunId":rid, "reason":"run_ended",
            "payload":p, "confirmedRunEndMs":p["capturedThroughMs"],
            "directOpenCompletion":base["directOpenCompletion"],
            "diagnosticSummaries":{"security4663":summary}})
    done = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        transport.tick()
        snap = transport.snapshot()
        states = [snap["runs"][rid] for rid in started.values()]
        if all(s["finish_acknowledged"] for s in states):
            done=True; break
        time.sleep(.025)
    final = transport.snapshot()
    rows = []
    for suffix, rid in started.items():
        state = final["runs"][rid]
        sid = state["session_id"]
        status, body = get("/v3/sessions/"+sid) if sid else (None,b"")
        data = json.loads(body) if status==200 else None
        rows.append({
            "run":suffix, "localRunId":rid, "sessionId":sid,
            "finishAcknowledged":state["finish_acknowledged"],
            "status":state["status"], "diagnosticSummariesDropped":state["diagnostic_summaries_dropped"],
            "apiStatus":status, "apiSessionState":data["summary"]["sessionState"] if data else None,
            "apiAssessment":data["summary"]["assessment"]["status"] if data else None,
        })
    evidence = {"source":"source-level controller; synthetic worker events; real local Django/PostgreSQL HTTP",
                "successful":done,"rows":rows}
    OUT.joinpath("controller_transport_postgres_second_pass.json").write_text(
        json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(evidence,indent=2))
    if not done or len({x["sessionId"] for x in rows})!=2 or any(x["diagnosticSummariesDropped"] for x in rows):
        raise SystemExit("Controller/Postgres acceptance failed")
finally:
    transport.close(timeout=1)

