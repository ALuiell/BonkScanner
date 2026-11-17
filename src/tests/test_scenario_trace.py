"""The temporary trace is opt-in and isolates filesystem failures."""
import json
import os
import subprocess
import sys
from pathlib import Path

SOURCE = str(Path(__file__).resolve().parents[1])


def _run(code, env):
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)


def test_trace_disabled_without_both_variables(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = SOURCE
    env["BONK_TRACE_DIR"] = str(tmp_path)
    env.pop("BONK_TRACE_SCENARIO_FILE", None)
    _run('from infra.scenario_trace import trace; trace("event")', env)
    assert list(tmp_path.iterdir()) == []


def test_trace_records_scenario_and_survives_io_failure(tmp_path):
    scenario = tmp_path / "scenario.txt"
    scenario.write_text("run-1", encoding="utf-8")
    output = tmp_path / "out"
    env = os.environ.copy()
    env.update(PYTHONPATH=SOURCE, BONK_TRACE_DIR=str(output), BONK_TRACE_SCENARIO_FILE=str(scenario))
    _run('from infra import scenario_trace as t; t.trace("event", value=3); t._queue.join()', env)
    rows = [json.loads(line) for line in next(output.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    row = rows[0]
    assert row["event"] == "event" and row["scenario_id"] == "run-1"
    assert row["value"] == 3 and row["pid"] > 0 and row["perf_counter_ns"] > 0
    env["BONK_TRACE_DIR"] = str(scenario / "invalid")
    _run('from infra import scenario_trace as t; t.trace("event"); t._queue.join()', env)


def test_scenario_is_captured_before_queued_write(tmp_path):
    scenario = tmp_path / "scenario.txt"
    scenario.write_text("first", encoding="utf-8")
    output = tmp_path / "out"
    env = os.environ.copy()
    env.update(PYTHONPATH=SOURCE, BONK_TRACE_DIR=str(output), BONK_TRACE_SCENARIO_FILE=str(scenario))
    code = r"""
from infra import scenario_trace as t
from pathlib import Path
import os, queue
writer_queue = t._queue
holding_queue = queue.Queue()
t._queue = holding_queue
t.trace("before")
Path(os.environ["BONK_TRACE_SCENARIO_FILE"]).write_text("second", encoding="utf-8")
t.trace("after")
Path(os.environ["BONK_TRACE_SCENARIO_FILE"]).unlink()
t.trace("missing")
t._queue = writer_queue
while not holding_queue.empty():
    writer_queue.put(holding_queue.get())
writer_queue.join()
"""
    _run(code, env)
    rows = [json.loads(line) for line in next(output.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    rows = [row for row in rows if row["event"] != "trace_shutdown"]
    assert [row["scenario_id"] for row in rows] == ["first", "second", None]
    assert rows[2]["scenario_error"] == "FileNotFoundError"


def test_normal_exit_flushes_and_reports_queue_drops_and_write_errors(tmp_path):
    scenario = tmp_path / "scenario.txt"
    scenario.write_text("test", encoding="utf-8")
    output = tmp_path / "out"
    env = os.environ.copy()
    env.update(PYTHONPATH=SOURCE, BONK_TRACE_DIR=str(output), BONK_TRACE_SCENARIO_FILE=str(scenario))
    code = r"""
from infra import scenario_trace as t
from pathlib import Path
import queue
writer_queue = t._queue
t._queue = queue.Queue(maxsize=1)
t._queue.put('occupied')
t.trace('dropped')
t._queue = writer_queue
t._write_row(Path(t._trace_dir) / 'missing' / 'invalid' / 'trace.jsonl', {'event': object()})
t.trace('queued-before-exit')
"""
    _run(code, env)
    rows = [json.loads(line) for line in next(output.glob("scanner-*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["queued-before-exit", "trace_shutdown"]
    assert rows[0]["trace_queue_drops_before"] == 1
    assert rows[0]["trace_write_errors_before"] == 1
    assert rows[1]["trace_queue_drops_before"] == 0


def test_activity_trace_only_samples_actual_probes_and_preserves_unknown(monkeypatch):
    from app import run_lifecycle
    from core.game_state import RuntimeGameMode, RuntimeGameState

    events = []
    monkeypatch.setattr(run_lifecycle, "trace", lambda event, **fields: events.append((event, fields)))
    now = [0.0]
    reads = iter([RuntimeGameState(mode=RuntimeGameMode.IN_GAME, is_playing=True), None,
                  RuntimeGameState(mode=RuntimeGameMode.GAME_OVER, is_playing=True)])
    lifecycle = run_lifecycle.RunLifecycle(read_activity_state=lambda _ctx: next(reads),
        read_game_state=lambda _ctx: None, live_run_tracker=lambda: object(), clock=lambda: now[0])
    lifecycle.refresh()
    lifecycle.refresh()  # cache hit, no new probe or sample
    now[0] = 1.0
    lifecycle.refresh()
    now[0] = 2.0
    lifecycle.refresh()
    assert [event for event, _ in events] == ["scanner_activity_sample", "scanner_run_detected",
        "scanner_activity_sample", "scanner_activity_sample", "scanner_run_game_over"]
    assert events[0][1]["is_playing"] is True
    assert events[2][1]["is_playing"] is None
    assert events[0][1]["run_timer"] is None


def test_activity_trace_reports_known_exit_but_not_unknown(monkeypatch):
    from app import run_lifecycle
    from core.game_state import RuntimeGameMode, RuntimeGameState

    events = []
    monkeypatch.setattr(run_lifecycle, "trace", lambda event, **fields: events.append(event))
    now = [0.0]
    modes = iter([RuntimeGameMode.IN_GAME, RuntimeGameMode.MAIN_MENU])
    lifecycle = run_lifecycle.RunLifecycle(
        read_activity_state=lambda _ctx: RuntimeGameState(mode=next(modes)),
        read_game_state=lambda _ctx: None, live_run_tracker=lambda: object(), clock=lambda: now[0])
    lifecycle.refresh()
    now[0] = 1.0
    lifecycle.refresh()
    assert events.count("scanner_run_left_active") == 1
