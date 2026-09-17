"""In-memory publication of the recording currently being captured.

The feed deliberately knows nothing about Qt or JSONL.  Capture publishes the
same immutable snapshot objects that were appended to the live buffer, and UI
consumers decide when (and on which scheduler) to prepare a new revision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import threading
from typing import Any, Callable

from infra.vod_storage import LoadedVod, VodMetadata, VodSnapshot


RECORDING = "recording"
FINALIZED = "finalized"
DISCARDED = "discarded"
FINALIZE_FAILED = "finalize_failed"


@dataclass(frozen=True)
class ActiveRecordingState:
    path: Path
    metadata: VodMetadata
    snapshots: tuple[VodSnapshot, ...]
    revision: int
    status: str
    detail: str | None = None

    @property
    def loaded_vod(self) -> LoadedVod:
        return LoadedVod(metadata=self.metadata, snapshots=self.snapshots)


class ActiveRecordingFeed:
    """Thread-safe, scheduler-neutral latest state for the active recording."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[Path, ActiveRecordingState] = {}
        self._active_path: Path | None = None
        self._revision = 0
        self._next_token = 0
        self._subscribers: dict[
            int, tuple[Callable[[ActiveRecordingState], None], Callable[[Callable[[], None]], Any]]
        ] = {}

    @staticmethod
    def _key(path: Path | str) -> Path:
        return Path(path).resolve()

    @property
    def active_state(self) -> ActiveRecordingState | None:
        with self._lock:
            if self._active_path is None:
                return None
            return self._states.get(self._active_path)

    def state_for(self, path: Path | str) -> ActiveRecordingState | None:
        with self._lock:
            return self._states.get(self._key(path))

    def subscribe(
        self,
        callback: Callable[[ActiveRecordingState], None],
        schedule: Callable[[Callable[[], None]], Any],
    ) -> int:
        with self._lock:
            self._next_token += 1
            token = self._next_token
            self._subscribers[token] = (callback, schedule)
            state = self.active_state
        if state is not None:
            self._deliver(callback, schedule, state)
        return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(int(token), None)

    def start(self, metadata: VodMetadata) -> ActiveRecordingState:
        key = self._key(metadata.path)
        with self._lock:
            # A completed run may still be open in a tab, but the tab owns its
            # prepared immutable package.  Do not retain every completed run's
            # full snapshot tuple for the lifetime of the application.  A
            # failed finalization is the exception: memory is the reliable
            # copy and must remain available for recovery/viewing.
            self._states = {
                path: state
                for path, state in self._states.items()
                if state.status == FINALIZE_FAILED
            }
            self._revision += 1
            state = ActiveRecordingState(
                path=key,
                metadata=replace(metadata, path=key),
                snapshots=(),
                revision=self._revision,
                status=RECORDING,
            )
            self._states[key] = state
            self._active_path = key
        self._publish(state)
        return state

    def append(
        self, metadata: VodMetadata, snapshot: VodSnapshot
    ) -> ActiveRecordingState:
        key = self._key(metadata.path)
        with self._lock:
            current = self._states.get(key)
            if current is None or current.status != RECORDING:
                raise RuntimeError(f"No active recording for {key}")
            self._revision += 1
            state = ActiveRecordingState(
                path=key,
                metadata=replace(metadata, path=key),
                snapshots=current.snapshots + (snapshot,),
                revision=self._revision,
                status=RECORDING,
            )
            self._states[key] = state
            self._active_path = key
        self._publish(state)
        return state

    def finalize(self, metadata: VodMetadata) -> ActiveRecordingState:
        return self._finish(metadata, FINALIZED)

    def discard(self, reason: str) -> ActiveRecordingState | None:
        with self._lock:
            current = self.active_state
            if current is None:
                return None
            self._revision += 1
            state = replace(
                current,
                revision=self._revision,
                status=DISCARDED,
                detail=str(reason),
            )
            self._states[current.path] = state
            self._active_path = None
        self._publish(state)
        return state

    def fail_finalize(self, error: BaseException | str) -> ActiveRecordingState | None:
        with self._lock:
            current = self.active_state
            if current is None:
                return None
            self._revision += 1
            state = replace(
                current,
                revision=self._revision,
                status=FINALIZE_FAILED,
                detail=str(error),
            )
            self._states[current.path] = state
            self._active_path = None
        self._publish(state)
        return state

    def _finish(self, metadata: VodMetadata, status: str) -> ActiveRecordingState:
        key = self._key(metadata.path)
        with self._lock:
            current = self._states.get(key)
            if current is None:
                raise RuntimeError(f"No active recording for {key}")
            self._revision += 1
            state = replace(
                current,
                metadata=replace(metadata, path=key),
                revision=self._revision,
                status=status,
                detail=None,
            )
            self._states[key] = state
            if self._active_path == key:
                self._active_path = None
        self._publish(state)
        return state

    def _publish(self, state: ActiveRecordingState) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.values())
        for callback, schedule in subscribers:
            self._deliver(callback, schedule, state)

    @staticmethod
    def _deliver(callback, schedule, state) -> None:
        try:
            schedule(lambda state=state, callback=callback: callback(state))
        except Exception:
            # A closing window is not allowed to break capture.
            pass
