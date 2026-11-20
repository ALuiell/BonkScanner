
"""Integrator-only bounded source fixtures; native UAC/Windows requires separate acceptance."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from bonkscanner_validator.controller import ValidatorController
from bonkscanner_validator.engine import (
    ObservationEngine, _audit_offset_discontinuity, AUDIT_CLOCK_BRACKET_NS,
)
from bonkscanner_validator.protocol import validate
from bonkscanner_validator.run_diagnostics import audit_summary
from bonkscanner_validator.security_audit import report
from bonkscanner_validator.transport import TransportManager


def pair(qpc, offset=1_000_000_000_000, width=1_000):
    return {"utc_ns": qpc + offset, "qpc_ns": qpc,
            "width_ns": width, "offset_low_ns": offset - width // 2,
            "offset_high_ns": offset + width // 2}


def make_engine():
    engine = ObservationEngine(collectors=SimpleNamespace(Census=lambda: None))
    anchor = pair(10_000_000_000)
    engine.run = {"id": "original-run", "audit": {
        "start": anchor["utc_ns"], "clock": anchor["utc_ns"] - anchor["qpc_ns"],
        "clock_pair": anchor, "spans": [], "open": False, "last_fresh_at": None, "issues": [],
    }}
    return engine


def test_coherent_brackets_detect_real_steps_but_not_jitter():
    base = pair(0)
    for jitter in (0, 50_000, 1_000_000, 2_000_000):
        assert not _audit_offset_discontinuity(base, pair(100_000_000, offset=1_000_000_000_000+jitter))
    assert _audit_offset_discontinuity(base, pair(1_000_000_000, offset=1_002_318_000_000))
    assert _audit_offset_discontinuity(base, pair(1_000_000_000, offset=997_682_000_000))


def test_security_audit_gap_499_vs_501_ms_keeps_two_spans_not_one(monkeypatch):
    engine = make_engine()
    values = iter([pair(10_000_000_000), pair(10_499_000_000),
                   pair(11_000_000_000)])
    monkeypatch.setattr("bonkscanner_validator.engine._audit_clock_pair", lambda: next(values))
    try:
        engine._sample_audit(True, sampled_at=1.)
        engine._sample_audit(True, sampled_at=1.499)
        spans = engine.run["audit"]["spans"]
        assert len(spans) == 1 and spans[0][1] > spans[0][0]
        engine._sample_audit(True, sampled_at=2.)
        assert len(spans) == 2 and spans[0][1] < spans[1][0]
        assert "run_boundary_unknown" in engine.run["audit"]["issues"]
    finally:
        engine.close()


def test_time_step_invalidates_attribution_not_claiming_a_fresh_span(monkeypatch):
    engine = make_engine()
    values = iter([pair(10_000_000_000), pair(10_100_000_000, offset=1_002_318_000_000)])
    monkeypatch.setattr("bonkscanner_validator.engine._audit_clock_pair", lambda: next(values))
    try:
        engine._sample_audit(True, sampled_at=1)
        engine._sample_audit(True, sampled_at=1.1)
        info = engine.run["audit"]
        assert info["spans"] == []
        assert "clock_changed" in info["issues"] and info["open"] is False
    finally:
        engine.close()


def test_wide_bracket_does_not_claim_clock_changed(monkeypatch):
    engine = make_engine()
    wide = pair(10_100_000_000, width=AUDIT_CLOCK_BRACKET_NS + 100_000_000)
    monkeypatch.setattr("bonkscanner_validator.engine._audit_clock_pair", lambda: wide)
    try:
        engine._sample_audit(True, sampled_at=1)
        assert "clock_changed" not in engine.run["audit"]["issues"]
        assert "run_boundary_unknown" in engine.run["audit"]["issues"]
        assert engine.run["audit"]["spans"] == []
    finally:
        engine.close()


def test_frozen_finish_pair_does_not_consult_new_perf_clock(monkeypatch):
    engine = make_engine()
    class Audit:
        def __init__(self):
            self.args = None

        def finish(self, start, end, spans, issues, *, collect, cancel=None):
            self.args = (start, end, list(spans), list(issues), collect)
            return report("partial", issues, restoration="verified")

    audit = Audit()
    engine._audit_setup = report("armed", restoration="pending")
    engine._audit = audit
    info = engine.run["audit"]
    info["spans"] = [[info["start"], info["start"] + 100_000_000]]
    end = pair(10_200_000_000)
    try:
        # Independent *coherent* later pairs are allowed and required for
        # clock-change checks during the deferred query; the old frozen UTC
        # must never be mixed with a new unpaired performance counter.
        with patch("bonkscanner_validator.engine._audit_clock_pair",
                   side_effect=(pair(12_000_000_000), pair(12_250_000_000))) as later:
            with patch("bonkscanner_validator.engine.time.perf_counter_ns",
                       side_effect=AssertionError("unpaired deferred QPC used")):
                output = []
                result = engine._finish_audit_impl(output, "run_ended", end)
        assert later.call_count == 2
        assert audit.args[1] == end["utc_ns"]
        assert "clock_changed" not in result["issues"]
        assert result["restoration"] == "verified"
        assert output[-1]["report"]["localRunId"] == "original-run"
    finally:
        engine.close()


def test_unsafe_frozen_clock_pair_blocks_full_security():
    engine = make_engine()
    class Audit:
        def finish(self, start, end, spans, issues, *, collect, cancel=None):
            return report("partial", issues, restoration="verified")
    engine._audit_setup = report("armed", restoration="pending")
    engine._audit = Audit()
    try:
        result = engine._finish_audit_impl([], "run_ended",
                                           pair(10_200_000_000, offset=1_002_318_000_000))
        assert "clock_changed" in result["issues"]
        assert result["status"] == "partial"
    finally:
        engine.close()


def test_gui_cannot_show_off_until_sender_is_finished():
    release = threading.Event()
    running = threading.Event()

    def task():
        running.set()
        release.wait(2)

    sender = threading.Thread(target=task)
    sender.start()
    assert running.wait(1)
    controller = ValidatorController()
    controller._stop.set()
    controller._state = "stopping"
    controller._sender = sender
    try:
        pending = controller.snapshot()
        assert pending["state"] == "stopping" and pending["busy"]
        release.set()
        sender.join(2)
        done = controller.snapshot()
        assert done["state"] == "disabled" and not done["busy"]
    finally:
        release.set()
        sender.join(2)


def test_preserved_external_change_remains_in_v3_diagnostic_without_loss():
    summary = audit_summary(report("partial", ["policy_changed"], "preserved_external_change"),
                            audit_armed=True)
    assert summary["restoration"] == "preserved_external_change"
    diagnostics = {"security4663": summary}
    validate("DiagnosticSummaries", diagnostics)
    m = TransportManager("", protocol_version="3")
    from tests.test_validator_transport import binding
    run_id = m.start_run(binding())
    try:
        assert m.finish_run(run_id, "run_ended", diagnostic_summaries=diagnostics)
        session = m._sessions[run_id]
        assert not session.diagnostics_dropped
        assert session.diagnostics is not None
        assert b"preserved_external_change" in session.diagnostics
    finally:
        m.close(timeout=0)



def test_audit_24_rows_keep_early_late_foreign_and_full_counts():
    from bonkscanner_validator.security_audit import _record, _event_ns
    from tests.test_security_audit_limits import event, PATH
    start = _event_ns("2026-11-13T00:00:00Z")
    group = report("collected")
    args = dict(paths={PATH.casefold()}, lower=5, start=start,
                end=start + 1_000_000_000, spans=[(start, start+1_000_000_000)],
                owner=(999, 0x72), seen=set())
    for rid in range(6, 106):
        # Retained own-reader 4663 and later foreign rights must both be visible.
        pid = "0x3e7" if rid < 40 else "0x234"
        _record(event(rid, pid=pid, mask="0x30"), group, **args)
    rows = group["ambiguous"]["rows"] + group["confirmed"]["rows"]
    assert len(group["confirmed"]["rows"]) == 24
    assert group["confirmed"]["rowsOmitted"] == 10
    assert len(group["ambiguous"]["rows"]) == 24
    assert group["ambiguous"]["rowsOmitted"] == 42
    assert group["confirmed"]["rows"][0]["recordId"] == 6
    assert [r["recordId"] for r in group["ambiguous"]["rows"][-8:]] == list(range(98, 106))
    assert 105 in {r["recordId"] for r in rows}
    assert any(row["sourcePid"] == 0x234 for row in group["ambiguous"]["rows"])
    assert group["confirmed"]["readRecords"] == group["confirmed"]["writeRecords"] == 34
    assert group["ambiguous"]["readRecords"] == group["ambiguous"]["writeRecords"] == 66
    assert "result_limit" in group["issues"]


def test_audit_span_limit_never_invents_33rd_span(monkeypatch):
    engine = make_engine()
    number = [0]
    def next_pair():
        number[0] += 1
        return pair(10_000_000_000 + number[0]*100_000_000)
    monkeypatch.setattr("bonkscanner_validator.engine._audit_clock_pair", next_pair)
    try:
        for i in range(36):
            engine._sample_audit(True, sampled_at=i*0.1)
            engine._sample_audit(False, sampled_at=i*0.1+0.05)
        info = engine.run["audit"]
        assert len(info["spans"]) == 32
        assert "run_boundary_unknown" in info["issues"]
        assert info["open"] is False
    finally:
        engine.close()


def test_native_journal_iterator_distinguishes_exhausted_and_scan_cap(monkeypatch):
    import sys
    from bonkscanner_validator import security_audit as a

    class Handle:
        def Close(self): pass
    data = [Handle(), Handle(), Handle()]
    query = Handle()
    class FakeEvt:
        EvtQueryChannelPath=1
        EvtQueryForwardDirection=2
        EvtRenderEventXml=3
        def EvtQuery(self, *args): return query
        def EvtNext(self, *args):
            n = min(args[1], len(data))
            batch = data[:n]
            del data[:n]
            return batch
        def EvtRender(self, *args): return "<Event/>"

    monkeypatch.setitem(sys.modules, "win32evtlog", FakeEvt())
    monkeypatch.setattr(a, "SCAN_LIMIT", 2)
    stats = {"readStopReason": "not_started", "retrieved": 0}
    with pytest.raises(a.QueryBudgetExceeded) as exc:
        list(a._query(1, 0, 100000000000, clock=lambda: 0, stats=stats))
    assert exc.value.stop_reason == "scan_budget"
    assert stats == {"readStopReason": "scan_budget", "retrieved": 2}

    monkeypatch.setattr(a, "SCAN_LIMIT", 10)
    stats = {"readStopReason": "not_started", "retrieved": 0}
    assert list(a._query(1, 0, 100000000000, clock=lambda: 0, stats=stats)) == ["<Event/>"]
    assert stats["readStopReason"] == "exhausted" and stats["retrieved"] == 1




def test_twelve_deferred_finals_remain_bounded_and_thirteenth_fails_closed():
    from concurrent.futures import Future

    class FakePool:
        def submit(self, *args, **kwargs):
            return Future()  # An old Security cleanup has not completed.

        def shutdown(self, **kwargs): pass

    engine = ObservationEngine(collectors=SimpleNamespace(Census=lambda: None))
    # No native ETW sessions: only exercise queue ownership/capacity paths.
    engine._finalizer_pool.shutdown(wait=True)
    engine._finalizer_pool = FakePool()
    try:
        for index in range(12):
            old_id = f"run-{index}"
            engine.run = {"id": old_id}
            engine._access = SimpleNamespace()
            assert engine._finish(float(index), "context_lost", [],
                                  resume_access=False) is None
            assert engine.run is None
            assert engine._pending_finalizations[index][0] == old_id
        engine.run = {"id": "run-12"}
        engine._access = SimpleNamespace()
        with pytest.raises(RuntimeError, match="bounded validator finalization queue exhausted"):
            engine._finish(12., "context_lost", [], resume_access=False)
        assert len(engine._pending_finalizations) == 12
        assert engine.run["id"] == "run-12"  # not relabeled as completed
    finally:
        engine.run = None
        engine._access = None
        engine._pending_finalizations.clear()
        engine.close()



def test_security_clock_pair_precedes_slow_opt_in_diagnostic_write(monkeypatch, tmp_path):
    """A stale sensor sample must not bind the later trace-write stall."""
    from pathlib import Path
    from types import SimpleNamespace
    from bonkscanner_validator.engine import ObservationEngine
    calls = []
    api = SimpleNamespace(Census=lambda: None, file_metadata=lambda *_: {},
                          environment=lambda *_: {"facts": [], "unresolved": 0},
                          file_hashes=lambda *_: [])
    engine = ObservationEngine(collectors=api)
    engine.reader = SimpleNamespace(check=lambda: None, pid=123, handle=7,
                                    created="2026-11-17T09:00:00Z",
                                    path=Path("MegaBonk.exe"), close=lambda: None)
    engine.profile = SimpleNamespace(sha256="fixture", name="fixture", build="fixture")
    engine.sensor = SimpleNamespace(sample=lambda: (calls.append("physical_read"), {
        "mode": "unknown", "active": False, "gap_reason": "read_failed",
    })[1])
    engine.run = {
        "id": "old", "origin": time.monotonic(), "last_from": 0,
        "last_sample": {"mode": "run", "run_config": 1, "stage_index": 0,
                        "run_timer": 10., "sensor_ok": True},
        "last_bound_at": time.monotonic(), "unknown_since": None,
        "audit": {"start": pair(10_000_000_000)["utc_ns"],
                  "clock": 1_000_000_000_000, "clock_pair": pair(10_000_000_000),
                  "spans": [], "open": False, "last_fresh_at": None, "issues": []},
    }
    engine._startup_trace.path = tmp_path / "enabled"
    chosen = pair(10_050_000_000)
    def clock_read():
        calls.append("paired_utc_qpc")
        return chosen
    def emit(name, **_fields):
        calls.append(name)
        if name == "sensor_poll_end":
            # Simulates synchronous JSONL I/O after a completed physical read.
            time.sleep(0.06)
    engine._startup_emit = emit
    engine._sample_audit = lambda *_args, **kw: calls.append(
        ("audit_applied", kw.get("pair") is chosen))
    monkeypatch.setattr("bonkscanner_validator.engine._audit_clock_pair", clock_read)
    try:
        engine.poll()
        assert calls.index("physical_read") < calls.index("paired_utc_qpc")
        assert calls.index("paired_utc_qpc") < calls.index("sensor_poll_begin")
        assert calls.index("paired_utc_qpc") < calls.index("sensor_poll_end")
        assert ("audit_applied", True) in calls
        assert calls.count("paired_utc_qpc") == 1
    finally:
        engine.run = None
        engine.close()


def test_declined_uac_start_never_shows_off_before_cleanup():
    from bonkscanner_validator.controller import ValidatorController
    stop_entered = threading.Event()
    release_stop = threading.Event()
    closed = threading.Event()

    class Worker:
        status = "starting"
        def start(self, cancel_event=None):
            self.status = "disabled"
            return False

        def request_stop(self):
            pass

        def stop(self, timeout=2):
            stop_entered.set()
            assert release_stop.wait(2)
            return []

    class Transport:
        def __init__(self, *args, **kw): pass
        def tick(self): pass
        def close(self, timeout=3): closed.set()
        def snapshot(self, blocking=True): return {}

    controller = ValidatorController(worker_factory=Worker, transport_factory=Transport)
    try:
        assert controller.enable("")
        assert stop_entered.wait(1)
        current = controller.snapshot()
        assert current["state"] == "stopping"
        assert current["error"] == "observer_not_started"
        assert current["busy"] and not current["enabled"]
        release_stop.set()
        assert closed.wait(2)
        deadline = time.monotonic() + 2
        while controller.snapshot()["busy"] and time.monotonic() < deadline:
            time.sleep(.005)
        assert controller.snapshot()["state"] == "disabled"
    finally:
        release_stop.set()
        controller.close()


def test_new_generation_does_not_cancel_stale_worker_on_early_stop():
    from unittest.mock import Mock
    from bonkscanner_validator.controller import ValidatorController
    constructing = threading.Event()
    release = threading.Event()

    class Worker:
        def start(self, cancel_event=None): return False
        def stop(self, timeout=2): return []

    class Transport:
        def __init__(self, *args, **kw): pass
        def tick(self): pass
        def close(self, timeout=3): pass
        def snapshot(self, blocking=True): return {}

    def factory():
        constructing.set()
        release.wait(2)
        return Worker()

    c = ValidatorController(worker_factory=factory, transport_factory=Transport)
    stale = Mock(status="starting")
    c._worker = stale
    try:
        assert c.enable("")
        assert constructing.wait(1)
        assert c._worker is None
        c.disable(timeout=0)
        stale.request_stop.assert_not_called()
    finally:
        release.set()
        c.close()



def test_clock_step_during_security_grace_demotes_every_exact_claim():
    from bonkscanner_validator.run_diagnostics import audit_summary
    engine=make_engine()
    engine._audit_setup=report("armed",restoration="pending")
    old_start=engine.run["audit"]["start"]

    class Audit:
        def finish(self, start, end, spans, issues, *, collect, cancel=None):
            output=report("collected", issues, restoration="verified")
            output["confirmed"].update(readRecords=1,writeRecords=1,rows=[
                {"recordId":17,"sourcePid":100,"handle":20,"rightsMask":0x30,
                 "offsetMs":30,"utcNs":old_start+30_000_000,
                 "attribution":"validator_reader"}])
            output["ambiguous"].update(readRecords=1,writeRecords=0,rows=[
                {"recordId":18,"sourcePid":101,"handle":21,"rightsMask":0x10,
                 "offsetMs":40,"utcNs":old_start+40_000_000,
                 "attribution":"handle_lifetime_unverified"}])
            return output

    engine._audit=Audit()
    end=pair(10_200_000_000)
    with patch("bonkscanner_validator.engine._audit_clock_pair",
               side_effect=[pair(10_250_000_000),
                            pair(11_500_000_000,offset=1_002_318_000_000)]):
        try:
            result=engine._finish_audit_impl([], "run_ended", end)
            assert result["status"]=="partial"
            assert result["timeDomainUntrusted"] is True
            assert "clock_changed" in result["issues"]
            assert "run_boundary_unknown" in result["issues"]
            assert result["confirmed"]["readRecords"]==0
            assert result["confirmed"]["writeRecords"]==0
            assert result["confirmed"]["rows"]==[]
            assert result["ambiguous"]["readRecords"]==2
            assert result["ambiguous"]["writeRecords"]==1
            assert len(result["ambiguous"]["rows"])==2
            assert all(r["attribution"]=="run_boundary_unknown"
                       for r in result["ambiguous"]["rows"])
            assert audit_summary(result,audit_armed=True)["queryCompleted"] is False
        finally:
            engine.close()


def test_uncertain_postquery_bracket_cannot_leave_exact_reader_usage():
    engine=make_engine()
    engine._audit_setup=report("armed",restoration="pending")

    class Audit:
        def finish(self, start, end, spans, issues, *, collect, cancel=None):
            result=report("collected", issues, restoration="verified")
            result["confirmed"]["readRecords"]=1
            result["confirmed"]["rows"]=[{
                "recordId":1,"sourcePid":2,"handle":3,"rightsMask":16,"offsetMs":0,
                "utcNs":start+1,"attribution":"validator_reader"}]
            return result

    engine._audit=Audit()
    with patch("bonkscanner_validator.engine._audit_clock_pair",
               side_effect=[pair(10_250_000_000),
                            pair(11_500_000_000,width=AUDIT_CLOCK_BRACKET_NS+100_000_000)]):
        try:
            result=engine._finish_audit_impl([],"run_ended",pair(10_200_000_000))
            assert "run_boundary_unknown" in result["issues"]
            assert "clock_changed" not in result["issues"]
            assert result["timeDomainUntrusted"]
            assert result["confirmed"]["readRecords"]==0
            assert result["ambiguous"]["readRecords"]==1
        finally:
            engine.close()


def test_many_security_records_do_not_grow_duplicate_issue_array():
    from bonkscanner_validator.security_audit import _record, _event_ns
    from tests.test_security_audit_limits import event, PATH
    start = _event_ns("2026-11-13T00:00:00Z")
    result = report("collected")
    args = dict(paths={PATH.casefold()}, lower=5, start=start,
                end=start+1_000_000_000, spans=[(start,start+1_000_000_000)],
                owner=(999,1), seen=set())
    for rid in range(6,1006):
        _record(event(rid,mask="0x30"),result,**args)
    assert result["ambiguous"]["readRecords"]==1000
    assert result["ambiguous"]["writeRecords"]==1000
    assert result["ambiguous"]["rowsOmitted"]==976
    assert len(result["ambiguous"]["rows"])==24
    assert set(result["issues"])=={"result_limit","handle_lifetime_unverified"}
    assert len(result["issues"])==2



def test_real_run_begin_trace_never_passes_duplicate_run_id(tmp_path):
    """The 2026-11-17 packaged worker failed exactly at known-start audit_clock_pair."""
    import json
    from types import SimpleNamespace
    from bonkscanner_validator.engine import ObservationEngine
    from bonkscanner_validator.security_audit import report

    engine = ObservationEngine(
        collectors=SimpleNamespace(Census=lambda: None),
        protocol_version="3",
        audit_factory=lambda *_: None,
    )
    destination = tmp_path / "production-start-trace.jsonl"
    engine._startup_trace.path = destination
    engine._startup_trace.scenario_file = None
    engine.reader = SimpleNamespace(pid=29100, created="2026-11-17T10:20:00Z", close=lambda: None)
    engine.profile = SimpleNamespace(build="1.0.69", name="pe-test")
    engine._last_actual_sensor = 1.0
    engine._audit = SimpleNamespace(armed_at=0)
    engine._audit_setup = report("armed", restoration="pending")
    sample = {
        "mode": "run", "stage": 0x123400, "stage_index": 0,
        "run_timer": 1.2, "run_config": 0x234000,
        "map_seed": 12345, "player": 0x345000,
    }
    try:
        out=[]
        engine._begin(1.0, out, sample, access_origin=None, attachment="run_start_known")
        assert engine.run is not None
        assert any(x["kind"]=="run_start" for x in out)
        lines=[json.loads(x) for x in destination.read_text(encoding="utf-8").splitlines()]
        assert any(x["event"]=="audit_clock_pair" and x["phase"]=="begin" and
                   x["run_id"]==engine.run["id"] for x in lines)
        assert any(x["event"]=="run_start" for x in lines)
    finally:
        engine._audit_setup = None
        engine._audit = None
        engine.run = None
        engine.close()


def test_freeze_and_rearm_trace_include_run_id_only_once(tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from bonkscanner_validator.engine import ObservationEngine
    from bonkscanner_validator.security_audit import report

    engine = ObservationEngine(
        collectors=SimpleNamespace(Census=lambda: None),
        protocol_version="3",
        audit_factory=lambda *_: None,
    )
    destination=tmp_path/"production-freeze-trace.jsonl"
    engine._startup_trace.path=destination
    engine._startup_trace.scenario_file=None
    engine.run={"id":"run-for-freeze","origin":1., "last_from":0,"last_sample":{},
                "audit":{"start":1,"clock":0,"clock_pair":None,
                         "last_fresh_at":None, "spans":[], "open":False,"issues":[]}}
    engine._audit_setup=report("armed",restoration="pending")
    try:
        engine._freeze_finalization=Mock(return_value=SimpleNamespace())
        engine._finalizer_pool.submit=Mock(return_value=Mock(done=lambda:False))
        engine._finish(2.,"context_lost",[],resume_access=False)
        records=[json.loads(x) for x in destination.read_text(encoding="utf-8").splitlines()]
        assert any(x["event"]=="audit_clock_pair" and x["phase"]=="freeze" and
                   x["run_id"]=="run-for-freeze" for x in records)
    finally:
        engine._pending_finalizations.clear()
        engine._audit_setup=None
        engine._audit=None
        engine.run=None
        engine.close()



def test_frozen_recovery_helper_has_longer_bounded_bootstrap_window(monkeypatch):
    """A 58 MB onefile helper may take >3s to extract before arming 4663."""
    import sys
    from unittest.mock import Mock
    from bonkscanner_validator.audit_recovery import (
        Recovery, SETUP_TIMEOUT, FROZEN_SETUP_TIMEOUT,
    )

    assert SETUP_TIMEOUT == 3.0
    assert 6 <= FROZEN_SETUP_TIMEOUT <= 20
    helper = object.__new__(Recovery)
    helper._receive = Mock(return_value={"armed": True})
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert helper.ready() == {"armed": True}
    helper._receive.assert_called_once_with(FROZEN_SETUP_TIMEOUT)
    helper._receive.reset_mock()
    monkeypatch.delattr(sys, "frozen")
    assert helper.ready() == {"armed": True}
    helper._receive.assert_called_once_with(SETUP_TIMEOUT)



def test_frozen_recovery_error_stages_fail_closed(monkeypatch):
    """No diagnostics print privileged target identities or bypass authentication."""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from bonkscanner_validator import audit_recovery as ar
    arguments=["150","123456789","200","123456789"]
    parent=SimpleNamespace(close=Mock())
    with patch.object(ar,"verify_peer",side_effect=PermissionError):
        assert ar.main(arguments)==4
    with patch.object(ar,"verify_peer",return_value=parent), (
         patch.object(ar,"_ancestry_contains",return_value=False)):
        assert ar.main(arguments)==5
    with patch.object(ar,"verify_peer",return_value=parent), (
         patch.object(ar,"_ancestry_contains",return_value=True)), (
         patch.object(ar,"_NativeStream",side_effect=OSError)):
        assert ar.main(arguments)==6
    with patch.object(ar,"verify_peer",return_value=parent), (
         patch.object(ar,"_ancestry_contains",return_value=True)), (
         patch.object(ar,"_NativeStream",return_value=Mock())), (
         patch.object(ar,"supervise",side_effect=OSError)):
        assert ar.main(arguments)==7



def test_controller_exception_trace_records_only_type_and_stack(monkeypatch, tmp_path):
    import sys
    import types
    from unittest.mock import Mock
    from bonkscanner_validator.controller import _trace_controller_exception

    recorder = Mock()
    parent = types.ModuleType("infra")
    parent.__path__ = []
    submodule = types.ModuleType("infra.scenario_trace")
    submodule.trace = recorder
    monkeypatch.setitem(sys.modules, "infra", parent)
    monkeypatch.setitem(sys.modules, "infra.scenario_trace", submodule)
    monkeypatch.setenv("BONK_TRACE_DIR", str(tmp_path))

    def raise_error():
        raise ValueError("SECRET_USER_TOKEN_MUST_NOT_BE_LOGGED")

    try:
        raise_error()
    except ValueError as exc:
        _trace_controller_exception("observer", exc)
    recorder.assert_called_once()
    args, fields = recorder.call_args
    assert args == ("validator_controller_exception",)
    assert fields["phase"] == "observer"
    assert fields["error_type"] == "ValueError"
    assert any(frame["function"] == "raise_error" for frame in fields["frames"])
    assert "SECRET_USER_TOKEN_MUST_NOT_BE_LOGGED" not in repr(fields)

    recorder.reset_mock()
    monkeypatch.delenv("BONK_TRACE_DIR")
    try:
        raise_error()
    except ValueError as exc:
        _trace_controller_exception("observer", exc)
    recorder.assert_not_called()



def test_worker_exception_trace_remains_local_and_redacted(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from bonkscanner_validator.worker import _trace_worker_exception
    from bonkscanner_validator import startup_trace
    records = Mock()
    class Fixture:
        def emit(self, *args, **kwargs): records(*args, **kwargs)
    monkeypatch.setattr(startup_trace, 'StartupTrace', Fixture)
    monkeypatch.setenv('BONK_TRACE_DIR', str(tmp_path))
    try:
        raise ValueError('NEVER_REPORT_THIS_PRIVATE_VALUE')
    except ValueError as exc:
        _trace_worker_exception('ipc_loop', exc)
    assert records.call_count == 1
    args, kwargs = records.call_args
    assert args == ('worker_runtime_exception',)
    assert kwargs['phase'] == 'ipc_loop'
    assert kwargs['error_type'] == 'ValueError'
    assert 'NEVER_REPORT_THIS_PRIVATE_VALUE' not in repr(kwargs)
    monkeypatch.delenv('BONK_TRACE_DIR')
    records.reset_mock()
    try:
        raise ValueError('NEVER_REPORT_THIS_PRIVATE_VALUE')
    except ValueError as exc:
        _trace_worker_exception('worker_main', exc)
    records.assert_not_called()



def test_worker_idle_heartbeat_survives_real_4_second_gaps_with_bounded_stop():
    from bonkscanner_validator.worker import HEARTBEAT_TIMEOUT, IO_THREAD_JOIN_SECONDS
    # Native 2026-11-17 worker exception: Pipe.receive -> _operation TimeoutError
    # at the previous 4-second bound. The frame decoder must still fail closed
    # on a truncated/malformed frame; only the idle parent heartbeat is relaxed.
    assert 12 <= HEARTBEAT_TIMEOUT <= 20
    assert HEARTBEAT_TIMEOUT > 4
    assert IO_THREAD_JOIN_SECONDS <= 5
