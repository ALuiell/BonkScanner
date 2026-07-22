"""Task scheduler for shared runtime refresh work.

The coordinator deliberately has no Qt dependency.  Its owner calls ``tick``
from the existing UI thread, keeping game-memory reads and tracker mutation
single-writer while allowing consumers to declare demand independently.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable


@dataclass(frozen=True)
class SourceReadMetadata:
    """Timing/identity of one source's first physical read in a pass.

    Recorded once, on the cache miss that actually calls the factory (see
    ``RefreshTickContext.get_or_create_with_metadata``). A cache hit -- value
    or cached exception -- never rewrites it. ``pass_id`` proves two
    observations share one pass (step 28 plan section 12.3); it is not a
    cross-pass adjacency rule.
    """

    pass_id: int
    started_at: float
    finished_at: float
    succeeded: bool


class RefreshTickContext:
    """Per-tick lazy cache shared by all due refresh tasks.

    ``pass_id`` and ``started_at`` identify the pass this context *is* --
    stamped once by ``RefreshCoordinator.tick()`` and never mutated after
    construction, so nothing downstream can accidentally reassign them mid-tick.
    """

    def __init__(
        self,
        pass_id: int,
        started_at: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._pass_id = pass_id
        self._started_at = started_at
        # Injected so a source's start/finish timestamps are scriptable in
        # tests (step 28 plan section 12.4) without patching `time.monotonic`
        # globally. Defaults to the real clock for callers that construct a
        # context directly (e.g. existing tests predating this field).
        self._clock = clock if clock is not None else time.monotonic
        self._values: dict[str, Any] = {}
        self._errors: dict[str, Exception] = {}
        self._metadata: dict[str, SourceReadMetadata] = {}

    @property
    def pass_id(self) -> int:
        return self._pass_id

    @property
    def started_at(self) -> float:
        return self._started_at

    def get_or_create(self, key: str, factory: Callable[[], Any]) -> Any:
        if key in self._values:
            return self._values[key]
        if key in self._errors:
            raise self._errors[key]
        try:
            value = factory()
        except Exception as exc:
            self._errors[key] = exc
            raise
        self._values[key] = value
        return value

    def get_or_create_with_metadata(self, key: str, factory: Callable[[], Any]) -> Any:
        """Like ``get_or_create``, but also records ``SourceReadMetadata`` for
        the physical attempt that resolves ``key``.

        A second use of this method for a key already resolved in this pass
        (value or cached error) is a pure cache hit: ``factory`` is not called
        again and the existing metadata is left untouched. This is what makes
        ``get_or_create``'s existing per-source failure isolation double as
        "one factory call per pass" for metadata purposes too -- no separate
        bookkeeping was needed to get that property, only to observe it.
        """
        if key in self._values or key in self._errors:
            return self.get_or_create(key, factory)
        started_at = self._clock()
        try:
            value = self.get_or_create(key, factory)
        except Exception:
            self._metadata[key] = SourceReadMetadata(
                pass_id=self._pass_id,
                started_at=started_at,
                finished_at=self._clock(),
                succeeded=False,
            )
            raise
        self._metadata[key] = SourceReadMetadata(
            pass_id=self._pass_id,
            started_at=started_at,
            finished_at=self._clock(),
            succeeded=True,
        )
        return value

    def metadata_for(self, key: str) -> SourceReadMetadata | None:
        return self._metadata.get(key)


@dataclass(frozen=True)
class RefreshTaskDiagnostics:
    task_id: str
    active: bool
    last_started_at: float | None
    last_succeeded_at: float | None
    last_error: str | None
    failure_count: int
    next_due_at: float | None


@dataclass
class RefreshTask:
    task_id: str
    interval_ms: int
    required: Callable[[], bool]
    run: Callable[[RefreshTickContext], bool | None]
    last_started_at: float | None = None
    last_succeeded_at: float | None = None
    last_error: str | None = None
    failure_count: int = 0


class RefreshCoordinator:
    """Runs each demanded task at most once per configured interval."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        # Resolved per call rather than captured here: binding ``time.monotonic``
        # as a default argument would freeze the real clock at import time, so a
        # test patching ``time.monotonic`` would move its own clock while the
        # coordinator kept scheduling against the real one. Tasks would then
        # silently never come due again. Callers wanting a deterministic clock
        # still pass one explicitly.
        self._clock = clock
        self._tasks: dict[str, RefreshTask] = {}
        # The pass counter. Owned by the coordinator, not the context (step 28
        # plan section 12.3/28a): a context that numbered itself would hand
        # every pass the same id, which is the one property `pass_id` exists to
        # provide. Starts at 0 and is pre-incremented in `tick()`, so the first
        # pass is id 1 -- 0 is never issued and is free to use as an "unset"
        # sentinel if a caller ever needs one. Not persisted: it has no meaning
        # across a process restart or a coordinator rebuild, and two contexts
        # from *this* coordinator are guaranteed distinct and monotonically
        # increasing, nothing more.
        self._pass_id = 0

    def _now(self) -> float:
        if self._clock is not None:
            return self._clock()
        return time.monotonic()

    def register(self, task: RefreshTask) -> None:
        if not task.task_id:
            raise ValueError("Refresh task id is required")
        if task.interval_ms < 1:
            raise ValueError("Refresh task interval must be positive")
        if task.task_id in self._tasks:
            raise ValueError(f"Refresh task already registered: {task.task_id}")
        self._tasks[task.task_id] = task

    def tick(self) -> tuple[str, ...]:
        now = self._now()
        self._pass_id += 1
        context = RefreshTickContext(pass_id=self._pass_id, started_at=now, clock=self._now)
        ran: list[str] = []
        for task in self._tasks.values():
            try:
                required = bool(task.required())
            except Exception as exc:
                self._record_failure(task, exc, prefix="required check failed")
                continue
            if not required or not self._is_due(task, now):
                continue
            task.last_started_at = now
            try:
                succeeded = task.run(context)
            except Exception as exc:  # Diagnostics must not stop other tasks.
                self._record_failure(task, exc)
            else:
                if succeeded is False:
                    task.failure_count += 1
                    task.last_error = "refresh returned failure"
                else:
                    task.last_succeeded_at = now
                    task.last_error = None
            ran.append(task.task_id)
        return tuple(ran)

    def diagnostics(self) -> tuple[RefreshTaskDiagnostics, ...]:
        now = self._now()
        result: list[RefreshTaskDiagnostics] = []
        for task in self._tasks.values():
            try:
                active = bool(task.required())
            except Exception:
                active = False
            result.append(
                RefreshTaskDiagnostics(
                    task_id=task.task_id,
                    active=active,
                    last_started_at=task.last_started_at,
                    last_succeeded_at=task.last_succeeded_at,
                    last_error=task.last_error,
                    failure_count=task.failure_count,
                    next_due_at=self._next_due_at(task, now),
                )
            )
        return tuple(result)

    @staticmethod
    def _record_failure(
        task: RefreshTask,
        exc: Exception,
        *,
        prefix: str | None = None,
    ) -> None:
        task.failure_count += 1
        try:
            detail = str(exc)
        except Exception:
            detail = "<error message unavailable>"
        message = f"{type(exc).__name__}: {detail}"
        task.last_error = f"{prefix}: {message}" if prefix else message

    @staticmethod
    def _is_due(task: RefreshTask, now: float) -> bool:
        return task.last_started_at is None or now - task.last_started_at >= task.interval_ms / 1000.0

    @staticmethod
    def _next_due_at(task: RefreshTask, now: float) -> float | None:
        if task.last_started_at is None:
            return now
        return task.last_started_at + task.interval_ms / 1000.0
