"""Optional source-snapshot consumer. Disk writes never run in the Qt thread."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading

from core.roll_analytics import ROLL_SOURCES, confirmed_roll_counts, stable_roll_scope
from infra.roll_history_store import RollHistoryStore


@dataclass(frozen=True, slots=True)
class RollAnalyticsStatus:
    session_recorded: int
    error: str | None
    writable: bool
    revision: int


class RollAnalyticsService:
    def __init__(self, store=None):
        self.store = store or RollHistoryStore()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="roll-history")
        self._lock = threading.RLock()
        self._active = None
        self._collection_generation = 0
        self._baseline_next = set()
        self._baseline_consumed = {}
        self._closed = False
        self._session_recorded = 0
        self._revision = 0
        self._run_ids = {}
        self._snapshots = {source: self.store.snapshot(source) for source in ROLL_SOURCES}

    def set_collection_active(self, active):
        with self._lock:
            active = bool(active)
            if self._active is not None and active != self._active:
                self._collection_generation += 1
                # Exclude the interval when collection was disabled or Premium
                # expired, even if no reads were demanded during that interval.
                self._baseline_next.update(ROLL_SOURCES)
            if self._active is None and not active:
                self._baseline_next.update(ROLL_SOURCES)
            self._active = active
            return active and not self._closed and self.store.writable

    def observe(self, *, process_identity, owner_stats, passive_ptr, chaos, passive,
                run_id="", run_timer=None):
        scope = stable_roll_scope(process_identity, owner_stats, passive_ptr)
        observations = confirmed_roll_counts(chaos, passive)
        with self._lock:
            if (not scope or not observations or not self._active
                    or self._closed or not self.store.writable):
                return False
            collecting = bool(self._active)
            baselines = frozenset(self._baseline_next.intersection(observations))
            previous_run = self._run_ids.get(scope)
            run_reset = bool(run_id and previous_run and previous_run != run_id)
            if run_id:
                self._run_ids[scope] = run_id
            self._executor.submit(self._write, scope, observations, collecting, baselines,
                                  run_id, run_timer, run_reset, self._collection_generation)
        return True

    def _write(self, scope, observations, collecting, baselines, run_id="", run_timer=None,
               run_reset=False, collection_generation=None):
        try:
            # Several reads can queue before the first baseline reaches disk.
            # Consume it once per source/pause generation in this serial worker,
            # rather than treating every queued snapshot as another baseline.
            with self._lock:
                baselines = frozenset(source for source in baselines
                                      if collection_generation is None or
                                      self._baseline_consumed.get(source) != collection_generation)
            added, changed = self.store.observe(scope, observations, collecting=collecting,
                                               baseline_sources=baselines, run_id=run_id,
                                               run_timer=run_timer, run_reset=run_reset)
            snapshots = {source: self.store.snapshot(source) for source in ROLL_SOURCES}
            with self._lock:
                if changed is not None:
                    for source in baselines:
                        self._baseline_consumed[source] = collection_generation
                if changed is not None and collection_generation == self._collection_generation:
                    self._baseline_next.difference_update(observations)
                self._snapshots = snapshots
                self._session_recorded += added
                if changed:
                    self._revision += 1
        except Exception as exc:
            self.store.error = f"Roll history could not be saved: {exc}"
            self.store.writable = False

    def snapshot(self, source):
        with self._lock:
            return self._snapshots[source]

    def status(self):
        with self._lock:
            return RollAnalyticsStatus(self._session_recorded, self.store.error,
                                       self.store.writable, self._revision)

    def flush(self):
        self._executor.submit(lambda: None).result()

    def export_json(self, destination):
        self.flush()
        self.store.export_json(destination)

    def clear(self):
        self._executor.submit(self.store.clear).result()
        snapshots = {source: self.store.snapshot(source) for source in ROLL_SOURCES}
        with self._lock:
            self._snapshots = snapshots
            self._session_recorded = 0
            self._revision += 1

    def close(self):
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)
        self.store.close()
