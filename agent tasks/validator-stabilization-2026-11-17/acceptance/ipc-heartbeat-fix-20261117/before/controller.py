"""Own a user-enabled observer and its independent, bounded network sender."""
from __future__ import annotations

import copy
import os
import threading
import time
import uuid
from typing import Callable


TRANSPORT_DRAIN_SECONDS = 3.0


def _trace_controller_exception(phase, exc):
    """Opt-in local exception provenance; never log payloads/tokens/paths.

    Installed Validator can run without Scanner's private scenario tracer.
    This must remain best-effort and must not change exception handling.
    """
    if not os.environ.get('BONK_TRACE_DIR'):
        return
    try:
        import traceback
        from pathlib import Path
        from infra.scenario_trace import trace
        frames = traceback.extract_tb(exc.__traceback__)[-8:]
        trace('validator_controller_exception',
              phase=phase, error_type=type(exc).__name__,
              frames=[{'file': Path(frame.filename).name,
                       'line': frame.lineno, 'function': frame.name}
                      for frame in frames])
    except Exception:
        pass


class ValidatorController:
    def __init__(self, *, scanner_version='development', worker_factory=None, transport_factory=None, clock: Callable = time.monotonic):
        self._scanner_version = scanner_version
        self._worker_factory = worker_factory
        self._transport_factory = transport_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._observer_done = threading.Event()
        self._reader = self._sender = None
        self._worker = self._transport = None
        self._state = 'disabled'
        self._error = None
        self._active = None
        # The monitor may enroll the next run while the old Security audit
        # finishes; both local sessions remain independently addressable.
        self._tracked_runs = set()
        self._last_payload = None
        self._last_payload_at = 0.0
        self._coverage = {}
        self._timing = {}
        self._process_access = None
        self._previous_process_access = None
        self._access_ipc_skipped = 0
        self._security_audit = self._last_security_audit = None
        self._security_audit_skipped = 0
        self._stop_reason = 'user_stopped'
        self._protocol_version = '2'
        self._generation = 0

    def enable(self, base_url=None, *, allow_loopback=False, protocol_version='2') -> bool:
        with self._lock:
            if any(t is not None and t.is_alive() for t in (self._reader, self._sender)):
                return False
            if self._worker_factory is None:
                from bonkscanner_validator.worker import WorkerClient
                self._worker_factory = lambda: WorkerClient(scanner_version=self._scanner_version,
                                                            protocol_version=self._protocol_version)
            if self._transport_factory is None:
                from bonkscanner_validator.transport import TransportManager
                self._transport_factory = TransportManager
            try:
                if protocol_version not in ('2', '3'):
                    raise ValueError('unsupported protocol')
                transport_options = {'allow_loopback': allow_loopback}
                if protocol_version == '3':
                    transport_options['protocol_version'] = protocol_version
                self._transport = self._transport_factory(
                    os.environ.get('BONKSCANNER_VALIDATOR_URL', '') if base_url is None else base_url,
                    **transport_options,
                )
            except Exception:
                self._state, self._error = 'disabled', 'invalid_service_url'
                return False
            self._generation += 1
            # The previous generation is fully exited here; do not cancel
            # its stale worker during rapid OFF -> Enable -> Stop cycles.
            self._worker = None
            self._stop = threading.Event()
            self._observer_done = threading.Event()
            self._state, self._error = 'starting', None
            self._protocol_version = protocol_version
            self._active, self._last_payload, self._coverage = None, None, {}
            self._tracked_runs.clear()
            self._timing = {}
            self._process_access = None
            self._previous_process_access = None
            self._access_ipc_skipped = 0
            self._security_audit = self._last_security_audit = None
            self._security_audit_skipped = 0
            self._stop_reason = 'user_stopped'
            self._reader = threading.Thread(target=self._observe, name='validator-observer', daemon=True)
            self._sender = threading.Thread(target=self._send, name='validator-delivery', daemon=True)
            self._reader.start()
            self._sender.start()
            return True

    def _observe(self):
        try:
            worker = self._worker_factory()
            with self._lock:
                self._worker = worker
            if self._stop.is_set():
                return
            result = worker.start(cancel_event=self._stop)
            if result is False:
                with self._lock:
                    if not self._stop.is_set():
                        # UAC cancellation / refused startup still has an
                        # observer finally and a sender drain to complete.
                        # Do not paint Off with live local owners.
                        self._state, self._error = 'stopping', 'observer_not_started'
                        self._stop.set()
                return
            with self._lock:
                if not self._stop.is_set():
                    self._state = 'waiting_game'
            while not self._stop.is_set():
                for event in worker.poll(timeout=0.1) or ():
                    self._event(event)
                if not self._stop.is_set() and not worker.alive:
                    raise RuntimeError('observer_stopped')
        except Exception as exc:
            _trace_controller_exception('observer', exc)
            with self._lock:
                if not self._stop.is_set():
                    self._state, self._error = 'stopped', 'observer_stopped'
                self._lose_audit('worker_stopped')
            self._interrupt('observer_stopped', 'worker_crash')
        finally:
            worker = self._worker
            if worker is not None:
                try:
                    tail = worker.stop(timeout=2)
                    for event in tail or ():
                        self._event(event)
                except Exception as exc:
                    _trace_controller_exception('observer_cleanup', exc)
                    with self._lock:
                        self._error = 'observer_cleanup_failed'
            self._interrupt(self._stop_reason)
            self._stop.set()
            self._observer_done.set()
            with self._lock:
                self._lose_audit('worker_stopped')
                if self._process_access is not None and self._process_access.get('mode') != 'stopped':
                    images = self._process_access.get('imageEvents')
                    if images is not None and images.get('status') == 'active':
                        images['status'] = 'partial'
                # The sender still owns the bounded network drain. State is
                # settled only after BOTH owners have actually exited.
                if self._state != 'stopped':
                    self._state = 'stopping'

    def _lose_audit(self, issue):
        audit = self._security_audit
        if audit is not None:
            self._last_security_audit = {
                **audit, 'status': 'unavailable', 'final': True,
                'issues': [*audit['issues'], issue],
                'restoration': 'unknown' if audit['restoration'] == 'pending' else audit['restoration'],
            }
            self._security_audit = None

    def _event(self, event):
        if not isinstance(event, dict):
            raise ValueError('invalid_worker_event')
        kind = event.get('kind')
        if kind == 'run_start':
            # Do NOT interrupt the previous run: its frozen ETW/Security
            # evidence may still be finalizing under its original localRunId.
            try:
                run_id = self._transport.start_run(event['binding'])
            except BufferError:
                run_id = None
            if run_id is not None and event.get('run_sample') is not None:
                self._transport.note_run_sample(run_id, event['run_sample'])
            with self._lock:
                if run_id is not None:
                    self._tracked_runs.add(run_id)
                self._active = run_id
                self._last_payload = None
                self._coverage = {}
                self._state = 'observing' if run_id else 'partial'
                if not run_id:
                    self._error = 'queue_capacity'
        elif kind in ('payload', 'run_end'):
            run_id = event.get('localRunId')
            if run_id is None or run_id not in self._tracked_runs:
                return
            current = run_id == self._active
            payload = event.get('payload')
            options = {}
            if 'localLoaderOffsetMs' in event:
                options['local_loader_offset_ms'] = event['localLoaderOffsetMs']
            if payload is not None and current:
                # UI tracks the *current* attempt. Old runs still deliver
                # complete immutable payloads to their own server sessions.
                with self._lock:
                    self._last_payload = {
                        'toMs': payload['toMs'], 'coverage': copy.deepcopy(payload['coverage'])}
                    direct = payload.get('directOpen')
                    if direct is not None:
                        self._last_payload['last_etw_health'] = direct['coverage']['lastHealthyOffsetMs']
                    self._last_payload_at = self._clock()
                    self._coverage = copy.deepcopy(payload['coverage'])
            if kind == 'run_end':
                reason = self._stop_reason if self._stop.is_set() else event['reason']
                summaries = event.get('diagnosticSummaries')
                if summaries is not None:
                    options['diagnostic_summaries'] = summaries
                if self._protocol_version == '3':
                    options['confirmed_run_end_ms'] = event.get('confirmedRunEndMs')
                    if 'directOpenCompletion' in event:
                        options['direct_open_completion'] = event['directOpenCompletion']
                self._transport.finish_run(run_id, reason, payload, **options)
                with self._lock:
                    self._tracked_runs.discard(run_id)
                    if current:
                        self._active, self._last_payload, self._state = None, None, 'waiting_game'
            elif payload is not None and not self._transport.accept_payload(run_id, payload, **options):
                with self._lock:
                    if current:
                        self._state, self._error = 'partial', 'queue_capacity'
        elif kind == 'loss':
            self._interrupt('observer_stopped', 'queue_loss')
            with self._lock:
                self._state, self._error = 'stopped', 'ipc_queue_capacity'
            self._stop.set()
        elif kind == 'process_access':
            # Launch-scoped diagnostics stay local. Run-bound direct-open
            # evidence travels separately in the regular payload events.
            report = event.get('report')
            if not isinstance(report, dict):
                raise ValueError('invalid_process_access_report')
            with self._lock:
                generation = report['attachmentGeneration']
                current = self._process_access
                previous = self._previous_process_access
                if current is None or generation >= current['attachmentGeneration']:
                    if current is not None and generation > current['attachmentGeneration']:
                        self._previous_process_access = current
                    self._process_access = report
                elif previous is None or generation >= previous['attachmentGeneration']:
                    self._previous_process_access = report
                self._access_ipc_skipped = max(self._access_ipc_skipped, report['skippedIpcUpdates'])
        elif kind == 'process_access_loss':
            with self._lock:
                self._access_ipc_skipped = max(self._access_ipc_skipped, event['skippedIpcUpdates'])
        elif kind == 'security_audit':
            report = event.get('report')
            if not isinstance(report, dict):
                raise ValueError('invalid_security_audit_report')
            with self._lock:
                if report['final']:
                    self._last_security_audit = report
                    if (self._security_audit is not None and
                            self._security_audit['attachmentGeneration'] == report['attachmentGeneration'] and
                            self._security_audit['localRunId'] == report['localRunId']):
                        self._security_audit = None
                else:
                    self._security_audit = report
        elif kind == 'security_audit_loss':
            with self._lock:
                skipped = event['skippedIpcUpdates']
                if skipped > self._security_audit_skipped:
                    self._security_audit_skipped = skipped
                    self._lose_audit('audit_update_lost')
        elif kind == 'state':
            if self._active is not None and event.get('run_sample') is not None:
                self._transport.note_run_sample(self._active, event['run_sample'])
            timing = event.get('timing')
            if isinstance(timing, dict):
                allowed = {'retainedSamples', 'limit', 'sensorMissedPeriods',
                           'censusMissedPeriods', 'maxDurationMs', 'maxLatenessMs',
                           'lastCensusStart'}
                allowed.update(kind + field for kind in ('sensor', 'census')
                               for field in ('Samples', 'MaxDurationMs', 'MaxLatenessMs'))
                with self._lock:
                    self._timing = {k: v for k, v in timing.items() if k in allowed
                                    and (v is None or type(v) in (int, float))}
            summary = event.get('coverage')
            if isinstance(summary, dict) and set(summary) <= {'processAccess', 'environment', 'fileIntegrity'}:
                with self._lock:
                    self._coverage = {name: {k: value[k] for k in (
                        'status', 'checks', 'failed', 'unresolved', 'lastSuccessOffsetMs') if k in value}
                        for name, value in summary.items() if isinstance(value, dict)}
            state = {
                'waiting_for_game': 'waiting_game', 'waiting_for_run': 'waiting_game',
                'attaching': 'waiting_game', 'ambiguous_game': 'partial',
                'game_unavailable': 'partial', 'context_unknown': 'partial',
                'unsupported_build': 'unsupported', 'sensor_unavailable': 'partial',
            }.get(event.get('state'), event.get('state'))
            if state in ('waiting_game', 'unsupported', 'partial', 'observing'):
                with self._lock:
                    self._state = 'partial' if state == 'observing' and self._error == 'queue_capacity' else state
        else:
            raise ValueError('invalid_worker_event')

    def _interrupt(self, reason, gap_kind='observation_error'):
        with self._lock:
            run_id, last = self._active, self._last_payload
            pending = tuple(self._tracked_runs - {run_id})
            self._tracked_runs.clear()
            self._active = self._last_payload = None
        for pending_id in pending:
            try:
                # Old session has no verified terminal packet. Its missing
                # Security audit makes a favorable v4 assessment impossible.
                self._transport.finish_run(pending_id, reason)
            except Exception:
                with self._lock:
                    self._error = 'finish_unconfirmed'
        if run_id is None:
            return
        start = last['toMs'] if last else 0
        stop = start + max(0, int((self._clock() - self._last_payload_at) * 1000)) if last else start
        coverage = copy.deepcopy(last['coverage']) if last else {
            name: {'status': 'unknown', 'checks': 0, 'failed': 0, 'unresolved': 0,
                   'lastSuccessOffsetMs': None}
            for name in ('processAccess', 'environment', 'fileIntegrity')}
        for channel in coverage.values():
            channel.update(status='unknown', checks=0, failed=0, unresolved=0)
        payload = {
            'fromMs': start, 'toMs': stop, 'capturedThroughMs': stop,
            'metadata': {'processes': [], 'artifacts': []}, 'observations': [],
            'environmentFacts': [], 'coverage': coverage,
            'gaps': [{'id': uuid.uuid4().hex, 'kind': gap_kind, 'channel': 'all',
                      'startOffsetMs': start, 'endOffsetMs': stop, 'lostCount': None,
                      'reason': {'worker_crash': 'worker_stopped', 'queue_loss': 'queue_overflow'}.get(gap_kind, 'unknown')}],
        }
        last_etw_health = last.get('last_etw_health') if last else None
        payload['directOpen'] = {
            'observations': [],
            'gaps': [{'id': uuid.uuid4().hex, 'reason': 'trace_stopped',
                      'startOffsetMs': start, 'endOffsetMs': stop}],
            'coverage': {'status': 'unknown' if last_etw_health is None else 'partial',
                         'lastHealthyOffsetMs': last_etw_health, 'eventsLost': 0, 'buffersLost': 0, 'recordsDropped': 0},
        }
        try:
            self._transport.finish_run(run_id, reason, payload)
        except Exception:
            with self._lock:
                self._error = 'finish_unconfirmed'

    def _send(self):
        try:
            while not self._observer_done.is_set():
                self._transport.tick()
                self._observer_done.wait(0.05)
        except Exception as exc:
            _trace_controller_exception('sender', exc)
            with self._lock:
                self._error = 'delivery_failed'
        finally:
            # No network work on the UI thread. Bound exit even on a dead server.
            try:
                self._transport.close(timeout=TRANSPORT_DRAIN_SECONDS)
            except Exception:
                with self._lock:
                    self._error = 'finish_unconfirmed'

    def snapshot(self):
        return self._snapshot(blocking=True, diagnostics=True)

    def try_snapshot(self, *, diagnostics=True):
        """Let a UI refresh skip a busy observer or sender and try again later."""
        return self._snapshot(blocking=False, diagnostics=diagnostics)

    def _snapshot(self, *, blocking, diagnostics):
        if not self._lock.acquire(blocking=blocking):
            return None
        try:
            reader_alive = self._reader is not None and self._reader.is_alive()
            busy = any(t is not None and t.is_alive() for t in (self._reader, self._sender))
            if self._stop.is_set() and self._state != 'stopped':
                # Reconcile the observer-finally / GUI Stop / sender-close
                # interleaving. Threads cannot publish a terminal state while
                # their own is_alive() is still true.
                self._state = 'stopping' if busy else 'disabled'
            enabled = reader_alive and not self._stop.is_set()
            result = {'state': self._state, 'error': self._error,
                      'enabled': enabled,
                      'active_run_id': self._active if enabled else None,
                      'busy': busy,
                      'coverage': copy.deepcopy(self._coverage)}
            if diagnostics:
                result['timing'] = copy.deepcopy(self._timing)
                result['process_access'] = copy.deepcopy(self._process_access)
                result['previous_process_access'] = copy.deepcopy(self._previous_process_access)
                result['process_access_ipc_skipped'] = self._access_ipc_skipped
                result['security_audit'] = copy.deepcopy(self._security_audit)
                result['last_security_audit'] = copy.deepcopy(self._last_security_audit)
                result['security_audit_ipc_skipped'] = self._security_audit_skipped
            elif self._process_access is not None:
                result['process_access'] = {'mode': self._process_access.get('mode')}
            transport = self._transport
        finally:
            self._lock.release()
        result['delivery'] = None
        if transport is not None:
            result['delivery'] = transport.snapshot() if blocking else transport.snapshot(blocking=False)
            if not blocking and result['delivery'] is None:
                return None
        return result

    def disable(self, *, timeout=5, reason='user_stopped') -> bool:
        with self._lock:
            generation = self._generation
            self._stop_reason = reason
            self._stop.set()
            if self._state != 'stopped':
                self._state = 'stopping'
            worker = self._worker
            reader, sender = self._reader, self._sender
        # UAC cancellation and graceful worker tail happen off the UI thread.
        if worker is not None and getattr(worker, 'status', None) == 'starting':
            worker.request_stop()
        end = self._clock() + min(5.0, max(0.0, timeout))
        for thread in (reader, sender):
            if thread is not None and thread is not threading.current_thread():
                thread.join(max(0, end - self._clock()))
        done = not any(t is not None and t.is_alive() for t in (reader, sender))
        with self._lock:
            if self._generation == generation and self._state != 'stopped':
                self._state = 'disabled' if done else 'stopping'
        return done

    def close(self, timeout=5):
        return self.disable(timeout=timeout, reason='client_stopped')
