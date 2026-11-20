"""Worker lifecycle fixtures never request UAC or touch a game process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import uuid

from bonkscanner_validator.ipc import FrameCodec, MAX_FRAME_BYTES, Pipe
from bonkscanner_validator.launcher import Process, verify_peer
from bonkscanner_validator.worker import EVIDENCE_QUEUE_BYTES, WorkerClient, _CreditSlot, _parse

SOURCE = str(Path(__file__).resolve().parents[1] / 'src')
FIXTURE = r'''
import sys
sys.path.insert(0,sys.argv[1])
import bonkscanner_validator.worker as w
w.privilege_state=lambda:{'elevated':True,'debugPrivilege':False,'debugPrivilegeError':'fixture'}
class Engine:
    def __init__(self,process_name):
        assert process_name=='MegaBonk.exe'
        self.once=False
        self.acked=False
        import threading
        self.owner=threading.get_ident()
    def poll(self):
        if self.once:return []
        self.once=True
        return [{'kind':'state','state':'waiting_for_game'}]
    def finish(self,reason='observer_stopped'):
        return [{'kind':'run_end','localRunId':'fixture-run','reason':reason,
                 'payload':{'positive':'collected-before-flush'}}]
    def acknowledge(self,event):
        import threading
        assert threading.get_ident()==self.owner
        self.acked=True
    def close(self):pass
options=w._parse(sys.argv[2:])
raise SystemExit(w.serve(options,engine_factory=Engine))
'''


def executable():
    current = Process.open(os.getpid())
    try:
        return current.identity.executable
    finally:
        current.close()


class ValidatorWorkerLogicalTests(unittest.TestCase):
    def test_client_sends_protocol_selection_only_in_v3_authenticated_hello(self):
        from types import SimpleNamespace
        for version in ('2', '3'):
            with self.subTest(version=version):
                parent = unittest.mock.Mock(identity=SimpleNamespace(pid=10, created='100'))
                child = unittest.mock.Mock(identity=SimpleNamespace(pid=20, created='200'))
                pipe = unittest.mock.Mock()
                pipe.receive.return_value = {'kind': 'ready', 'data': {
                    'pid': 20, 'created': '200', 'elevated': True, 'debugPrivilege': True}}
                with patch('bonkscanner_validator.worker.Process.open', return_value=parent), \
                     patch('bonkscanner_validator.worker.Pipe.create', return_value=pipe), \
                     patch('bonkscanner_validator.worker.launch_worker', return_value=child), \
                     patch('bonkscanner_validator.worker.verify_peer', return_value=child):
                    client = WorkerClient(protocol_version=version)
                    self.assertTrue(client.start())
                    hello = {'pid': 10, 'created': '100'}
                    if version == '3':
                        hello['protocolVersion'] = '3'
                    self.assertEqual(pipe.send.call_args_list[0].args[1:], ('hello', hello))
                    self.assertEqual(pipe.send.call_args_list[1].args[1:], ('start',))
        with self.assertRaises(ValueError):
            WorkerClient(protocol_version='4')

    def test_queue_preserves_lifecycle_burst_with_finite_bytes(self):
        slot = _CreditSlot()
        events = [{"kind": "run_start", "binding": {}}, {"kind": "state", "state": "observing"},
                  {"kind": "payload", "localRunId": "x", "payload": {}}]
        for event in events:
            self.assertTrue(slot.offer(event))
        self.assertEqual([value[0] for value in slot.events], events)
        self.assertLess(slot.bytes, MAX_FRAME_BYTES)

    def test_ack_bridge_retains_byte_reservation_until_engine_owner_retires(self):
        import threading
        slot = _CreditSlot()
        event = {"kind": "payload", "localRunId": "x", "payload": {"positive": "x" * 1000}}
        self.assertTrue(slot.offer(event))
        reserved = slot.bytes
        def handoff():
            with slot.lock:
                slot.acknowledge_head()
        thread = threading.Thread(target=handoff)
        thread.start()
        thread.join()
        self.assertEqual(slot.bytes, reserved)
        self.assertEqual(len(slot.acks), 1)
        engine = unittest.mock.Mock()
        engine.acknowledge.side_effect = lambda value: self.assertEqual(threading.get_ident(), owner)
        owner = threading.get_ident()
        slot.retire_acks(engine)
        engine.acknowledge.assert_called_once_with(event)
        self.assertEqual(slot.bytes, 0)
        self.assertFalse(slot.acks)

    def test_overflow_is_terminal_loss_not_discontinuous_payload(self):
        for kind in ("payload", "run_start", "run_end"):
            with self.subTest(kind=kind):
                slot = _CreditSlot()
                for index in range(3):
                    self.assertTrue(slot.offer({"kind": "payload", "payload": {"id": index, "x": "a" * 210000}}))
                self.assertFalse(slot.offer({"kind": kind, "localRunId": "run", "x": "a" * 180000}))
                self.assertEqual(slot.loss, {"kind": "loss", "reason": "queue_loss",
                                            "terminal": True, "localRunId": "run", "lostCount": 1})
                self.assertFalse(slot.offer({"kind": "payload", "payload": {}}))
                self.assertLess(slot.bytes, EVIDENCE_QUEUE_BYTES)

    def test_per_frame_limit_applies_even_when_queue_has_room(self):
        slot = _CreditSlot()
        self.assertFalse(slot.offer({"kind": "payload", "payload": {"x": "a" * MAX_FRAME_BYTES}}))
        self.assertTrue(slot.loss["terminal"])
        self.assertEqual(slot.bytes, 0)

    def test_poll_drains_without_idle_delay_while_events_are_available(self):
        client = WorkerClient()
        client.pipe = unittest.mock.Mock()
        client.process = unittest.mock.Mock(alive=True)
        client._stop_requested = unittest.mock.Mock()
        client._stop_requested.is_set.return_value = False
        client._stop_requested.wait.return_value = False
        event = {"kind": "state", "state": "observing"}
        client.pipe.receive.side_effect = [
            {"kind": "event", "seq": 1, "data": event},
            {"kind": "ready", "data": {}},
            {"kind": "ready", "data": {}},
        ]
        self.assertEqual(client.poll(timeout=.1), [event])
        self.assertEqual(client.poll(timeout=.1), [])
        self.assertEqual(client.poll(timeout=.1), [])
        self.assertEqual(client._stop_requested.wait.call_args_list,
                         [unittest.mock.call(.1), unittest.mock.call(0.0), unittest.mock.call(.1)])

    def test_uac_cancellation_is_disabled_without_restart(self):
        pipe = unittest.mock.Mock()
        process = unittest.mock.Mock()
        with patch("bonkscanner_validator.worker.Process.open", return_value=process), \
             patch("bonkscanner_validator.worker.Pipe.create", return_value=pipe), \
             patch("bonkscanner_validator.worker.launch_worker", return_value=None) as launch:
            client = WorkerClient()
            self.assertFalse(client.start())
            self.assertEqual(client.status, "disabled")
            self.assertFalse(client.alive)
            launch.assert_called_once()
            pipe.close.assert_called_once()
            process.close.assert_called_once()

    def test_start_external_cancellation_does_not_launch(self):
        import threading
        cancelled = threading.Event()
        cancelled.set()
        with patch("bonkscanner_validator.worker.launch_worker") as launch:
            client = WorkerClient()
            self.assertFalse(client.start(cancel_event=cancelled))
            self.assertEqual(client.status, "disabled")
            launch.assert_not_called()

    def test_bootstrap_accepts_no_operation_address_path_or_game_override(self):
        base = ["--pipe", str(uuid.uuid4()), "--instance", str(uuid.uuid4()),
                "--parent-pid", "1", "--parent-created", "1"]
        for addition in (["--operation", "read"], ["--address", "123"], ["--path", "evil"],
                         ["--process-name", "other.exe"], ["--parent-created", "nan"]):
            with self.subTest(addition=addition), self.assertRaises(SystemExit):
                _parse([*base, *addition])

    def test_bootstrap_bounds_host_version(self):
        base = ["--pipe", str(uuid.uuid4()), "--instance", str(uuid.uuid4()),
                "--parent-pid", "1", "--parent-created", "1"]
        self.assertEqual(_parse([*base, '--scanner-version', '3.1.4']).scanner_version, '3.1.4')
        for value in ('', 'x' * 65, 'bad\nversion'):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                _parse([*base, '--scanner-version', value])



@unittest.skipUnless(os.name == "nt", "Windows owned-process fixtures")
class ValidatorWorkerProcessTests(unittest.TestCase):
    def start_fixture(self, fixture=FIXTURE, protocol_version='2'):
        parent = Process.open(os.getpid())
        self.addCleanup(parent.close)
        pipe_id, worker_id = str(uuid.uuid4()), str(uuid.uuid4())
        pipe = Pipe.create(pipe_id)
        self.addCleanup(pipe.close)
        child = subprocess.Popen([executable(), "-I", "-c", fixture, SOURCE,
            "--pipe", pipe_id, "--instance", worker_id,
            "--parent-pid", str(parent.identity.pid), "--parent-created", parent.identity.created],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        pipe.accept(5)
        peer = verify_peer(pipe.peer_pid())
        self.addCleanup(peer.close)
        self.assertEqual(peer.identity.pid, child.pid)
        codec = FrameCodec(worker_id)
        hello = {"pid": parent.identity.pid, "created": parent.identity.created}
        if protocol_version == '3':
            hello['protocolVersion'] = '3'
        pipe.send(codec, "hello", hello)
        self.assertEqual(pipe.receive(codec)["kind"], "ready")
        pipe.send(codec, "start")
        return pipe, codec, child

    def test_v3_hello_selects_v3_for_default_engine_factory(self):
        fixture = FIXTURE.replace(
            'def __init__(self,process_name):',
            "def __init__(self,process_name,scanner_version,audit_cancel,protocol_version,trace_processes=None):\n        assert protocol_version=='3'")
        fixture = fixture.replace(
            'raise SystemExit(w.serve(options,engine_factory=Engine))',
            'import bonkscanner_validator.engine as e\ne.ObservationEngine=Engine\nraise SystemExit(w.serve(options))')
        pipe, codec, child = self.start_fixture(fixture, protocol_version='3')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            pipe.send(codec, 'ping')
            frame = pipe.receive(codec)
            if frame['kind'] == 'event':
                self.assertEqual(frame['data']['kind'], 'state')
                pipe.send(codec, 'ack', {'seq': frame['seq']})
                return
            time.sleep(.05)
        self.fail(f'worker did not emit an event: {child.poll()}')

    def test_stop_and_single_frame_ack(self):
        fixture = FIXTURE.replace("def finish(self,reason='observer_stopped'):",
            "def finish(self,reason='observer_stopped'):\n        assert self.acked")
        pipe, codec, child = self.start_fixture(fixture)
        event = None
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            pipe.send(codec, "ping")
            frame = pipe.receive(codec)
            if frame["kind"] == "event":
                event = frame
                break
            time.sleep(.05)
        self.assertIsNotNone(event)
        pipe.send(codec, "ack", {"seq": event["seq"]})
        client = WorkerClient()
        client.pipe, client.codec = pipe, codec
        client.process = Process.open(child.pid)
        client.status = "active"
        client.request_stop()  # Must preserve the connected pipe for tail drain.
        tail = client.stop(timeout=2)
        self.assertEqual(tail[-1]["kind"], "run_end")
        self.assertEqual(tail[-1]["payload"]["positive"], "collected-before-flush")
        self.assertEqual(child.wait(3), 0, child.stderr.read().decode())

    def test_parent_pipe_loss_stops_owned_worker(self):
        pipe, _, child = self.start_fixture()
        pipe.close()
        self.assertEqual(child.wait(3), 0, child.stderr.read().decode())

    def test_shutdown_reports_skipped_final_local_diagnostics_across_launches(self):
        fixture = FIXTURE.replace(
            "return [{'kind':'run_end','localRunId':'fixture-run','reason':reason,",
            """def access(generation, size):
            return {'kind':'process_access','report':{'attachmentGeneration':generation,'padding':'x'*size}}
        return [access(1, 12000), access(2, 12000), access(3, 24000),
                {'kind':'run_end','localRunId':'fixture-run','reason':reason,""")
        pipe, codec, child = self.start_fixture(fixture)
        client = WorkerClient()
        client.pipe, client.codec = pipe, codec
        client.process, client.status = Process.open(child.pid), "active"
        tail = client.stop(timeout=2)
        self.assertEqual([event["kind"] for event in tail if event["kind"] != "state"],
                         ["process_access", "process_access", "run_end", "process_access_loss"])
        self.assertEqual(tail[-1]["skippedIpcUpdates"], 1)
        self.assertEqual(child.wait(3), 0, child.stderr.read().decode())

    def test_missing_heartbeat_stops_worker(self):
        from bonkscanner_validator.worker import HEARTBEAT_TIMEOUT
        _, _, child = self.start_fixture()
        # Idle timeout is intentionally longer than the 4-second real-game
        # Scanner scheduling gap that previously killed an otherwise healthy
        # elevated observer. A permanently silent parent still closes.
        self.assertEqual(child.wait(HEARTBEAT_TIMEOUT + 3),
                         0, child.stderr.read().decode())

    def test_overflow_delivers_queued_prefix_then_one_terminal_loss(self):
        fixture = FIXTURE.replace(
            "return [{'kind':'state','state':'waiting_for_game'}]",
            "return [{'kind':'payload','localRunId':'run','payload':{'part':n,'x':'a'*210000}} for n in range(4)]")
        pipe, codec, child = self.start_fixture(fixture)
        losses = []
        delivered = []
        for _ in range(12):
            time.sleep(.05)
            pipe.send(codec, "ping")
            frame = pipe.receive(codec)
            if frame["kind"] == "event":
                pipe.send(codec, "ack", {"seq": frame["seq"]})
                if frame["data"]["kind"] == "loss":
                    losses.append(frame["data"])
                    break
                delivered.append(frame["data"]["payload"]["part"])
        self.assertEqual(delivered, [0, 1, 2])
        self.assertEqual(len(losses), 1)
        self.assertEqual(losses[0]["reason"], "queue_loss")
        self.assertEqual(losses[0]["lostCount"], 1)
        self.assertEqual(child.wait(3), 0, child.stderr.read().decode())

    def test_dedicated_watchdog_bounds_stuck_collector_cleanup(self):
        fixture = FIXTURE.replace("def close(self):pass",
            "def close(self):\n        import threading\n        threading.Event().wait(60)")
        fixture = fixture.replace("engine_factory=Engine)", "engine_factory=Engine,enforce_exit=True)")
        pipe, codec, child = self.start_fixture(fixture)
        client = WorkerClient()
        client.pipe, client.codec = pipe, codec
        client.process, client.status = Process.open(child.pid), "active"
        before = time.monotonic()
        tail = client.stop(timeout=2)
        self.assertTrue(any(event["kind"] == "run_end" for event in tail))
        self.assertEqual(child.wait(2), 4, child.stderr.read().decode())
        self.assertLess(time.monotonic() - before, 3.5)

    def test_unpermitted_command_fails_closed(self):
        pipe, codec, child = self.start_fixture()
        pipe.send(codec, "ping", {"operation": "write"})
        self.assertEqual(child.wait(3), 0, child.stderr.read().decode())

    def test_actual_parent_death_stops_worker(self):
        helper = r'''
import os,sys,subprocess,uuid
sys.path.insert(0,sys.argv[1])
from bonkscanner_validator.ipc import Pipe,FrameCodec
from bonkscanner_validator.launcher import Process
p=Process.open(os.getpid());pipe_id=str(uuid.uuid4());worker_id=str(uuid.uuid4());pipe=Pipe.create(pipe_id)
child=subprocess.Popen([p.identity.executable,'-I','-c',sys.argv[2],sys.argv[1],
'--pipe',pipe_id,'--instance',worker_id,'--parent-pid',str(p.identity.pid),'--parent-created',p.identity.created],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
pipe.accept(5);c=FrameCodec(worker_id);pipe.send(c,'hello',{'pid':p.identity.pid,'created':p.identity.created});pipe.receive(c);pipe.send(c,'start')
print(child.pid,flush=True)
os._exit(0)
'''
        result = subprocess.run([executable(), "-I", "-c", helper, SOURCE, FIXTURE],
                                capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        pid = int(result.stdout.strip())
        import pywintypes
        import win32api
        import win32event
        try:
            handle = win32api.OpenProcess(0x100000, False, pid)
        except pywintypes.error as exc:
            self.assertEqual(exc.winerror, 87)
        else:
            try:
                self.assertEqual(win32event.WaitForSingleObject(handle, 5000), 0)
            finally:
                handle.Close()


if __name__ == "__main__":
    unittest.main()
