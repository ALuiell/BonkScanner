"""Temporary, opt-in, best-effort cross-process scenario trace."""
from __future__ import annotations

import json
import atexit
import os
import queue
import threading
import time
from pathlib import Path

_trace_dir = os.environ.get("BONK_TRACE_DIR")
_scenario_file = os.environ.get("BONK_TRACE_SCENARIO_FILE")
_queue = queue.Queue(maxsize=2048) if _trace_dir and _scenario_file else None
_loss_lock = threading.Lock()
_queue_drops = 0
_write_errors = 0
_finished = threading.Event()
_stop = object()


def _write_row(path, row):
    global _queue_drops, _write_errors
    with _loss_lock:
        drops, errors = _queue_drops, _write_errors
    row = {**row, "trace_queue_drops_before": drops,
           "trace_write_errors_before": errors}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
    except Exception:
        with _loss_lock:
            _write_errors += 1
    else:
        with _loss_lock:
            _queue_drops -= drops
            _write_errors -= errors


def _writer():
    path = Path(_trace_dir) / f"scanner-{os.getpid()}.jsonl"
    while True:
        row = _queue.get()
        try:
            if row is _stop:
                _write_row(path, {"event": "trace_shutdown", "pid": os.getpid(),
                                  "perf_counter_ns": time.perf_counter_ns()})
                _finished.set()
                return
            _write_row(path, row)
        finally:
            _queue.task_done()


def trace(event, **fields):
    global _queue_drops
    if _queue is None:
        return
    try:
        timestamp = time.perf_counter_ns()
        try:
            with open(_scenario_file, "r", encoding="utf-8") as stream:
                scenario_id = stream.read(4097)
            if len(scenario_id) > 4096:
                raise ValueError("scenario ID exceeds 4096 characters")
            scenario_id = scenario_id.strip()
            scenario_error = None
        except (OSError, UnicodeError, ValueError) as exc:
            scenario_id = None
            scenario_error = type(exc).__name__
        _queue.put_nowait({"event": event, "perf_counter_ns": timestamp,
                           "pid": os.getpid(), "scenario_id": scenario_id,
                           "scenario_error": scenario_error, **fields})
    except queue.Full:
        with _loss_lock:
            _queue_drops += 1
    except Exception:
        pass


def _shutdown():
    """Best effort only: never wait indefinitely for a slow or failed disk."""
    if _queue is None:
        return
    try:
        _queue.put(_stop, timeout=0.1)
        _finished.wait(timeout=0.4)
    except Exception:
        pass


if _queue is not None:
    try:
        threading.Thread(target=_writer, name="scenario-trace", daemon=True).start()
        atexit.register(_shutdown)
    except Exception:
        _queue = None
