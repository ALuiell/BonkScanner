"""Standalone elevated observer and ordinary-process client; no GUI imports.

WorkerClient.start/poll/stop belong on one supervisor thread, never the UI
thread. Poll at least once per second. A crash requires an explicit new start.
"""
from __future__ import annotations

import argparse
from collections import deque
import os
import threading
import time
import uuid

from .ipc import FrameCodec, MAX_FRAME_BYTES, Pipe, ProtocolError, canonical_uuid
from .launcher import Process, launch_worker, privilege_state, verify_peer

def _trace_worker_exception(phase, exc):
    """Best-effort local error provenance; no private payloads or exception text."""
    if not os.environ.get("BONK_TRACE_DIR"):
        return
    try:
        from pathlib import Path
        import traceback
        from .startup_trace import StartupTrace
        frames = traceback.extract_tb(exc.__traceback__)[-8:]
        StartupTrace().emit(
            "worker_runtime_exception", phase=phase, error_type=type(exc).__name__,
            frames=[{"file":Path(f.filename).name, "line":f.lineno, "function":f.name}
                    for f in frames])
    except Exception:
        pass


# The parent Scanner may pause IPC updates during expensive, but bounded
# transport/controller work. A 4-second idle receive timeout repeatedly
# terminated healthy real-game workers (native trace 2026-11-17, 4663 active).
# Keep a finite limit for a genuinely stuck parent. A separate 50-ms lifetime
# watchdog still enforces parent-exit shutdown independently of this window.
HEARTBEAT_TIMEOUT = 15.0
IO_THREAD_JOIN_SECONDS = 4.2  # Avoid extending Stop/cleanup latency.
EVIDENCE_QUEUE_BYTES = 672 * 1024
LOCAL_ACCESS_BYTES = 32 * 1024
LOCAL_AUDIT_BYTES = 24 * 1024
LOCAL_AUDIT_FRAME_BYTES = LOCAL_AUDIT_BYTES // 2


class WorkerClient:
    def __init__(self, *, scanner_version='development', protocol_version='2'):
        if protocol_version not in ('2', '3'):
            raise ValueError('unsupported protocol')
        self.scanner_version = scanner_version
        self.protocol_version = protocol_version
        self.status = "disabled"
        self.pipe = None
        self.process = None
        self.launched = None
        self.codec = None
        self._stop_requested = threading.Event()
        self._reported_audit_skips = 0
        self._draining = False

    @property
    def alive(self):
        return bool(self.process and self.process.alive and not self._stop_requested.is_set())

    def start(self, cancel_event=None) -> bool:
        if self.process or self.pipe:
            raise RuntimeError("worker already started")
        self._stop_requested.clear()
        self._reported_audit_skips = 0
        self._draining = False
        self.status = "starting"
        def cancelled():
            return self._stop_requested.is_set() or bool(cancel_event and cancel_event.is_set())
        parent = Process.open(os.getpid())
        try:
            if cancelled():
                self.status = "disabled"
                return False
            pipe_id, worker_id = str(uuid.uuid4()), str(uuid.uuid4())
            self.codec = FrameCodec(worker_id)
            self.pipe = Pipe.create(pipe_id)
            if cancelled():
                self.status = "disabled"
                self._close()
                return False
            self.launched = launch_worker(pipe_id, worker_id, parent.identity,
                                          scanner_version=self.scanner_version)
            if self.launched is None:
                self.status = "disabled"
                self._close()
                return False
            if cancelled():
                raise InterruptedError("worker startup cancelled")
            self.pipe.accept(20.0, cancel_event=cancelled)
            if cancelled():
                raise InterruptedError("worker startup cancelled")
            self.process = verify_peer(self.pipe.peer_pid(), launched=self.launched, require_elevated=True)
            hello = {"pid": parent.identity.pid, "created": parent.identity.created}
            if self.protocol_version == '3':
                hello['protocolVersion'] = '3'
            self.pipe.send(self.codec, "hello", hello)
            frame = self.pipe.receive(self.codec, timeout=3.0)
            if (frame["kind"] != "ready" or frame["data"].get("pid") != self.process.identity.pid
                    or frame["data"].get("created") != self.process.identity.created
                    or frame["data"].get("elevated") is not True):
                raise ProtocolError("worker handshake mismatch")
            self.status = "active" if frame["data"].get("debugPrivilege") is True else "partial"
            self.pipe.send(self.codec, "start")
            if cancelled():
                self.stop(timeout=2.0)
                return False
            return True
        except BaseException:
            self.status = "failed"
            self._close()
            raise
        finally:
            parent.close()

    def poll(self, timeout=0.1) -> list[dict]:
        if not self.alive:
            if self.status not in {"disabled", "failed"}:
                self.status = "failed"
            return []
        # timeout bounds the idle delay; actual frames have an independent,
        # finite 2s deadline and malformed/partial frames close the connection.
        delay = 0.0 if self._draining else max(0.0, min(float(timeout), 0.5))
        if self._stop_requested.wait(delay):
            return []
        try:
            self.pipe.send(self.codec, "ping")
            frame = self.pipe.receive(self.codec, timeout=2.0)
            if frame["kind"] == "event":
                self.pipe.send(self.codec, "ack", {"seq": frame["seq"]})
                self._draining = True
                return [frame["data"]]
            self._draining = False
            if frame["kind"] == "ready" and set(frame["data"]) == {"securityAuditUpdatesSkipped"}:
                skipped = frame["data"]["securityAuditUpdatesSkipped"]
                if type(skipped) is not int or skipped < self._reported_audit_skips:
                    raise ProtocolError("invalid Security audit loss count")
                if skipped > self._reported_audit_skips:
                    self._reported_audit_skips = skipped
                    return [{"kind": "security_audit_loss", "skippedIpcUpdates": skipped}]
                return []
            if frame["kind"] != "ready" or frame["data"]:
                raise ProtocolError("unexpected worker response")
            return []
        except BaseException:
            self.status = "failed"
            self._close()
            raise

    def request_stop(self):
        """Thread-safe flag. I/O remains owned by the supervisor thread."""
        self._stop_requested.set()
        if self.status == "starting" and self.pipe is not None:
            self.pipe.cancel()

    def stop(self, timeout=2.0):
        self._stop_requested.set()
        events = []
        try:
            if self.pipe and self.process and self.process.alive:
                deadline = time.monotonic() + max(0.0, timeout)
                try:
                    self.pipe.send(self.codec, "stop", timeout=max(0.05, min(timeout, 1.0)))
                    while self.process.alive and time.monotonic() < deadline:
                        remaining = deadline - time.monotonic()
                        frame = self.pipe.receive(self.codec, timeout=remaining)
                        if frame["kind"] == "ready" and frame["data"].get("stopped") is True:
                            skipped = frame["data"].get("processAccessUpdatesSkipped", 0)
                            if type(skipped) is not int or skipped < 0:
                                raise ProtocolError("invalid diagnostic loss count")
                            if skipped:
                                events.append({"kind": "process_access_loss", "skippedIpcUpdates": skipped})
                            if frame["data"].get("securityAuditUpdatesSkipped"):
                                events.append({"kind": "security_audit_loss",
                                               "skippedIpcUpdates": frame["data"]["securityAuditUpdatesSkipped"]})
                            break
                        if frame["kind"] != "event":
                            raise ProtocolError("unexpected shutdown response")
                        events.append(frame["data"])
                        self.pipe.send(self.codec, "ack", {"seq": frame["seq"]},
                                       timeout=max(.01, deadline - time.monotonic()))
                except Exception:
                    pass
                while self.process.alive and time.monotonic() < deadline:
                    time.sleep(0.02)
        finally:
            self._close()
            self.status = "disabled"
        return events

    def _close(self):
        for name in ("pipe", "process", "launched"):
            value = getattr(self, name)
            setattr(self, name, None)
            if value is not None:
                value.close()


class _CreditSlot:
    """Bounded FIFO with one in-flight event, retained until application ACK.

    The FIFO can retain a short burst of valid evidence frames under the
    same per-frame limit. Local ETW and Security audit have separate budgets.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.events = deque()
        self.acks = deque()
        self.bytes = 0
        self.access_bytes = 0
        self.audit_bytes = 0
        self.sent_sequence = None
        self.queue_loss = False
        self.loss = None
        self.sending_loss = False
        self.skipped_access_updates = 0
        self.skipped_audit_updates = 0

    def acknowledge_head(self):
        # Called with lock held by the I/O owner. Transfer ownership without
        # releasing its byte reservation until the engine owner retires it.
        self.acks.append(self.events.popleft())

    def next_event(self):
        # Called under lock. A terminal loss follows all admitted events, so
        # the parent can finish each run using the last delivered watermark.
        self.sending_loss = not self.events and self.loss is not None
        return self.events[0][0] if self.events else self.loss

    def retire_acks(self, engine):
        with self.lock:
            acknowledged = list(self.acks)
            self.acks.clear()
        for event, size in acknowledged:
            engine.acknowledge(event)
            with self.lock:
                self.release(event, size)

    def release(self, event, size):
        if event.get('kind') == 'process_access':
            self.access_bytes -= size
        elif event.get('kind') == 'security_audit':
            self.audit_bytes -= size
        else:
            self.bytes -= size

    def _fail(self, event):
        self.queue_loss = True
        self.loss = {"kind": "loss", "reason": "queue_loss", "terminal": True,
                     "localRunId": event.get("localRunId"), "lostCount": 1}

    def offer(self, event: dict):
        with self.lock:
            if self.loss is not None:
                return False
            kind = event.get('kind')
            local_access = kind in ('process_access', 'security_audit')
            if kind == 'process_access':
                # Each update contains the retained launch history. Replace
                # queued updates, while leaving the possibly credited head
                # and all existing v2 events untouched.
                for index in range(len(self.events) - 1, 0, -1):
                    previous, previous_size = self.events[index]
                    if (previous.get('kind') == 'process_access'
                            and previous['report']['attachmentGeneration']
                            == event['report']['attachmentGeneration']):
                        del self.events[index]
                        self.release(previous, previous_size)
                event = {**event, 'report': {**event['report'],
                                             'skippedIpcUpdates': self.skipped_access_updates}}
            # Use the exact envelope encoder for byte accounting. No pending
            # serialization is retained; only the single credited event lives.
            try:
                size = len(FrameCodec("00000000-0000-0000-0000-000000000000").encode("event", event)) + 128
            except ProtocolError:
                if local_access:
                    self._skip_local(kind)
                    return False
                self._fail(event)
                return False
            if kind == 'security_audit':
                if size > LOCAL_AUDIT_FRAME_BYTES:
                    self._skip_local(kind)
                    return False
                # Retain the acknowledged head and newest diagnostic. Older
                # queued diagnostics may be replaced under backpressure.
                for index in range(len(self.events) - 1, 0, -1):
                    if self.audit_bytes + size <= LOCAL_AUDIT_BYTES:
                        break
                    previous, previous_size = self.events[index]
                    if previous.get('kind') == 'security_audit' and not previous['report'].get('final'):
                        del self.events[index]
                        self.release(previous, previous_size)
                if self.audit_bytes + size > LOCAL_AUDIT_BYTES:
                    self._skip_local(kind)
                    return False
                self.audit_bytes += size
            elif local_access:
                if self.access_bytes + size > LOCAL_ACCESS_BYTES:
                    self._skip_local(kind)
                    return False
                self.access_bytes += size
            elif self.bytes + size > EVIDENCE_QUEUE_BYTES:
                self._fail(event)
                return False
            else:
                self.bytes += size
            self.events.append((event, size))
            return True

    def _skip_local(self, kind):
        if kind == 'security_audit':
            self.skipped_audit_updates += 1
        else:
            self.skipped_access_updates += 1


def _parse(arguments=None):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--pipe", required=True, type=canonical_uuid)
    parser.add_argument("--instance", required=True, type=canonical_uuid)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--parent-created", required=True)
    parser.add_argument("--scanner-version", default="development")
    parser.add_argument("--trace-dir")
    parser.add_argument("--trace-scenario-file")
    parsed = parser.parse_args(arguments)
    for path in (parsed.trace_dir, parsed.trace_scenario_file):
        if path is not None and (not os.path.isabs(path) or len(path) > 32767 or not path.isprintable()):
            parser.error("invalid trace path")
    if parsed.trace_scenario_file and not parsed.trace_dir:
        parser.error("trace scenario file requires trace directory")
    if (not isinstance(parsed.scanner_version, str) or not parsed.scanner_version
            or len(parsed.scanner_version) > 64 or not parsed.scanner_version.isprintable()):
        parser.error("invalid scanner version")
    if (parsed.parent_pid <= 0 or not parsed.parent_created.isascii()
            or not parsed.parent_created.isdigit() or len(parsed.parent_created) > 20
            or not 0 < int(parsed.parent_created) < 2**64):
        parser.error("invalid parent identity")
    return parsed


def serve(options, *, engine_factory=None, enforce_exit=False) -> int:
    parent = pipe = current = engine = None
    stopped = threading.Event()
    started = threading.Event()
    drain_requested = threading.Event()
    tail_ready = threading.Event()
    cleanup_done = threading.Event()
    slot = _CreditSlot()
    io_thread = None
    watchdog = None
    try:
        privileges = privilege_state()
        if not privileges["elevated"]:
            return 3
        parent = verify_peer(options.parent_pid, created=options.parent_created)

        def lifetime_watchdog():
            deadline = None
            while not cleanup_done.wait(.05):
                if stopped.is_set() or drain_requested.is_set() or not parent.alive:
                    if deadline is None:
                        deadline = time.monotonic() + 2.25
                    if time.monotonic() >= deadline:
                        if enforce_exit:
                            # This is exclusively the dedicated worker process,
                            # never the UI or an in-process test fixture.
                            os._exit(4)
                        return

        watchdog = threading.Thread(target=lifetime_watchdog, name="validator-lifetime", daemon=True)
        watchdog.start()
        pipe = Pipe.connect(options.pipe, timeout=10.0)
        if pipe.peer_pid() != parent.identity.pid:
            raise PermissionError("pipe server is not the bootstrapping parent")
        codec = FrameCodec(options.instance)
        hello = pipe.receive(codec, timeout=3.0)
        hello_data = hello["data"]
        parent_identity = {"pid": parent.identity.pid, "created": parent.identity.created}
        if (hello["kind"] != "hello" or hello_data not in (
                parent_identity, {**parent_identity, "protocolVersion": "3"})):
            raise ProtocolError("parent handshake mismatch")
        protocol_version = hello_data.get("protocolVersion", "2")
        # Apply paths only after authenticating both the parent and pipe.
        trace_dir = getattr(options, 'trace_dir', None)
        trace_scenario = getattr(options, 'trace_scenario_file', None)
        if trace_dir:
            os.environ['BONK_TRACE_DIR'] = trace_dir
            if trace_scenario:
                os.environ['BONK_TRACE_SCENARIO_FILE'] = trace_scenario
            else:
                os.environ.pop('BONK_TRACE_SCENARIO_FILE', None)
        current = Process.open(os.getpid())
        pipe.send(codec, "ready", {**privileges, "pid": current.identity.pid,
                                   "created": current.identity.created})

        def io_loop():
            try:
                while not stopped.is_set() and parent.alive:
                    wait_started = time.monotonic()
                    command = pipe.receive(codec, timeout=HEARTBEAT_TIMEOUT)
                    waited = time.monotonic() - wait_started
                    if waited > 2.0 and os.environ.get("BONK_TRACE_DIR"):
                        # Local opt-in diagnostic; no IPC payload, secrets or
                        # parent identity. Generated only on unusual gaps.
                        try:
                            from .startup_trace import StartupTrace
                            StartupTrace().emit("worker_ipc_idle_gap",
                                                waited_ms=round(waited * 1000, 2))
                        except Exception:
                            pass
                    kind, data = command["kind"], command["data"]
                    if kind == "stop" and not data:
                        drain_requested.set()
                        deadline = time.monotonic() + 1.75
                        if not tail_ready.wait(1.0):
                            return
                        while parent.alive and time.monotonic() < deadline:
                            with slot.lock:
                                event = slot.next_event()
                            remaining = deadline - time.monotonic()
                            if event is None:
                                result = {"stopped": True}
                                if slot.skipped_access_updates:
                                    result["processAccessUpdatesSkipped"] = slot.skipped_access_updates
                                if slot.skipped_audit_updates:
                                    result["securityAuditUpdatesSkipped"] = slot.skipped_audit_updates
                                pipe.send(codec, "ready", result, timeout=remaining)
                                return
                            pipe.send(codec, "event", event, timeout=remaining)
                            ack = pipe.receive(codec, timeout=max(.01, deadline - time.monotonic()))
                            if (ack["kind"] != "ack" or ack["data"] != {"seq": codec.sent}
                                    or type(ack["data"].get("seq")) is not int):
                                raise ProtocolError("invalid shutdown ACK")
                            if slot.sending_loss:
                                return
                            with slot.lock:
                                slot.acknowledge_head()
                        return
                    if kind == "start" and not data and not started.is_set():
                        started.set()
                    elif kind == "ping" and not data and started.is_set():
                        with slot.lock:
                            if slot.sent_sequence is not None:
                                raise ProtocolError("event ACK missing")
                            event = slot.next_event()
                            if event is not None:
                                slot.sent_sequence = codec.sent + 1
                            audit_skips = slot.skipped_audit_updates
                        # Never hold the collector queue lock during pipe I/O.
                        if event is None:
                            data = {"securityAuditUpdatesSkipped": audit_skips} if audit_skips else None
                            pipe.send(codec, "ready", data, timeout=1.0)
                        else:
                            pipe.send(codec, "event", event, timeout=1.0)
                    elif kind == "ack" and set(data) == {"seq"}:
                        with slot.lock:
                            if type(data["seq"]) is not int or data["seq"] != slot.sent_sequence:
                                raise ProtocolError("invalid event ACK")
                            if slot.sending_loss:
                                return
                            slot.acknowledge_head()
                            slot.sent_sequence = None
                    else:
                        raise ProtocolError("operation is not permitted")
            except Exception as exc:
                _trace_worker_exception("ipc_loop", exc)
                # Parent loss/protocol failure closes this worker, never clean evidence.
            finally:
                stopped.set()

        io_thread = threading.Thread(target=io_loop, name="validator-local-ipc", daemon=True)
        io_thread.start()
        if engine_factory is None:
            from .engine import ObservationEngine
            engine_factory = lambda **kwargs: ObservationEngine(
                scanner_version=options.scanner_version,
                protocol_version=protocol_version,
                trace_processes={'scanner': {'pid': parent.identity.pid, 'created': parent.identity.created},
                                 'worker': {'pid': current.identity.pid, 'created': current.identity.created}},
                audit_cancel=lambda: (drain_requested.is_set() or stopped.is_set() or not parent.alive),
                **kwargs)
        engine = engine_factory(process_name="MegaBonk.exe")
        finished = False
        while not stopped.is_set() and parent.alive:
            tick = time.monotonic()
            slot.retire_acks(engine)
            if drain_requested.is_set():
                if not finished:
                    finished = True
                    for event in engine.finish(reason="observer_stopped"):
                        slot.offer(event)
                    tail_ready.set()
            elif started.is_set() and slot.loss is None:
                for event in engine.poll():
                    slot.offer(event)
            delay = getattr(engine, 'next_poll_delay', lambda: .1)()
            stopped.wait(max(.001, min(.1, delay)))
        return 0
    finally:
        stopped.set()
        # Closing the connected pipe cancels a peer wait; bounded receive
        # timeout otherwise ensures the daemon cannot outlive the process.
        if pipe is not None:
            pipe.close()
        if io_thread is not None:
            io_thread.join(timeout=IO_THREAD_JOIN_SECONDS)
        if engine is not None:
            slot.retire_acks(engine)
            engine.close()
        for process in (current, parent):
            if process is not None:
                process.close()
        cleanup_done.set()
        if watchdog is not None:
            watchdog.join(timeout=.2)


def main(arguments=None) -> int:
    try:
        result = serve(_parse(arguments), enforce_exit=True)
    except Exception as exc:
        _trace_worker_exception("worker_main", exc)
        result = 4
    # ThreadPoolExecutor joins running native jobs at interpreter shutdown even
    # after shutdown(wait=False). A standalone worker must not become an orphan.
    os._exit(result)
