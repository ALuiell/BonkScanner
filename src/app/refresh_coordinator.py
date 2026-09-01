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
        """Resolve ``key`` at most once per pass, recording ``SourceReadMetadata``
        for the physical attempt that resolved it.

        There is exactly **one** resolution path. An earlier revision had a
        separate ``get_or_create_with_metadata``, which meant a key first
        resolved through the plain method carried no metadata for the rest of
        the pass -- and ``metadata_for(key)`` then returned ``None`` silently,
        so a group-span computation over that key would either crash or skip a
        member without saying so. Metadata is not an opt-in decoration of a
        read; it is a property of the read. Recording it here makes the two
        methods impossible to mix, because there is only one.

        A second call for a key already resolved in this pass (value or cached
        error) is a pure cache hit: ``factory`` is not called again and the
        existing metadata is left untouched.
        """
        if key in self._values:
            return self._values[key]
        if key in self._errors:
            raise self._errors[key]
        started_at = self._clock()
        try:
            value = factory()
        except Exception as exc:
            self._errors[key] = exc
            self._metadata[key] = SourceReadMetadata(
                pass_id=self._pass_id,
                started_at=started_at,
                finished_at=self._clock(),
                succeeded=False,
            )
            raise
        self._values[key] = value
        self._metadata[key] = SourceReadMetadata(
            pass_id=self._pass_id,
            started_at=started_at,
            finished_at=self._clock(),
            succeeded=True,
        )
        return value

    # Retained as a name only: 28a introduced it as the metadata-recording
    # variant, and 28b's call sites spell it. It is now the same method, so no
    # site can pick the wrong one.
    get_or_create_with_metadata = get_or_create

    def metadata_for(self, key: str) -> SourceReadMetadata | None:
        return self._metadata.get(key)

    def resolved_keys(self) -> frozenset[str]:
        """Every key resolved in this pass, successfully or not.

        Equal to the metadata key set by construction, because there is one
        resolution path and it always records metadata.
        """
        return frozenset(self._metadata)


@dataclass(frozen=True)
class RefreshTaskDiagnostics:
    task_id: str
    active: bool
    last_started_at: float | None
    last_succeeded_at: float | None
    last_error: str | None
    failure_count: int
    next_due_at: float | None
    last_duration_ms: float | None
    state_changed_at: float | None


@dataclass(frozen=True)
class RefreshHealthEvent:
    task_id: str
    state: str
    occurred_at: float
    error: str | None


@dataclass
class RefreshTask:
    task_id: str
    interval_ms: int
    required: Callable[[], bool]
    run: Callable[[RefreshTickContext], bool | None]
    phase: int = 0
    after: tuple[str, ...] = ()
    failure_retry_ms: int | None = None
    last_started_at: float | None = None
    last_succeeded_at: float | None = None
    last_error: str | None = None
    failure_count: int = 0
    last_duration_ms: float | None = None
    state_changed_at: float | None = None
    last_health_event_at: float | None = None
    last_health_error: str | None = None


class RefreshCoordinator:
    """Runs each demanded task at most once per configured interval."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        health_event: Callable[[RefreshHealthEvent], None] | None = None,
    ) -> None:
        # Resolved per call rather than captured here: binding ``time.monotonic``
        # as a default argument would freeze the real clock at import time, so a
        # test patching ``time.monotonic`` would move its own clock while the
        # coordinator kept scheduling against the real one. Tasks would then
        # silently never come due again. Callers wanting a deterministic clock
        # still pass one explicitly.
        self._clock = clock
        self._health_event = health_event or self._journal_health_event
        self._tasks: dict[str, RefreshTask] = {}
        self._execution_order: tuple[RefreshTask, ...] | None = None
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
        if task.failure_retry_ms is not None and task.failure_retry_ms < 1:
            raise ValueError("Refresh task failure retry interval must be positive")
        if task.task_id in self._tasks:
            raise ValueError(f"Refresh task already registered: {task.task_id}")
        if not isinstance(task.phase, int):
            raise ValueError("Refresh task phase must be an integer")
        task.after = tuple(task.after)
        self._tasks[task.task_id] = task
        self._execution_order = None

    def tick(self) -> tuple[str, ...]:
        now = self._now()
        self._pass_id += 1
        context = RefreshTickContext(pass_id=self._pass_id, started_at=now, clock=self._now)
        ran: list[str] = []
        for task in self._ordered_tasks():
            try:
                required = bool(task.required())
            except Exception as exc:
                self._record_failure(task, exc, now=now, prefix="required check failed")
                continue
            if not required or not self._is_due(task, now):
                continue
            task.last_started_at = now
            task_run_started_at = self._now()
            try:
                succeeded = task.run(context)
            except Exception as exc:  # Diagnostics must not stop other tasks.
                self._record_failure(task, exc, now=self._now())
            else:
                if succeeded is False:
                    self._record_failure(
                        task,
                        RuntimeError("refresh returned failure"),
                        now=self._now(),
                    )
                else:
                    finished_at = self._now()
                    task.last_succeeded_at = finished_at
                    self._record_recovery(task, finished_at)
            finally:
                finished_at = self._now()
                task.last_duration_ms = max(
                    0.0, (finished_at - task_run_started_at) * 1000.0
                )
            ran.append(task.task_id)
        return tuple(ran)

    def diagnostics(self) -> tuple[RefreshTaskDiagnostics, ...]:
        now = self._now()
        result: list[RefreshTaskDiagnostics] = []
        for task in self._ordered_tasks():
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
                    last_duration_ms=task.last_duration_ms,
                    state_changed_at=task.state_changed_at,
                )
            )
        return tuple(result)

    def _record_failure(
        self,
        task: RefreshTask,
        exc: Exception,
        *,
        now: float,
        prefix: str | None = None,
    ) -> None:
        task.failure_count += 1
        try:
            detail = str(exc)
        except Exception:
            detail = "<error message unavailable>"
        message = f"{type(exc).__name__}: {detail}"
        error = f"{prefix}: {message}" if prefix else message
        previous_error = task.last_error
        task.last_error = error
        if previous_error is None:
            task.state_changed_at = now
        repeated_same = previous_error == error
        should_emit = (
            not repeated_same
            or task.last_health_event_at is None
            or now - task.last_health_event_at >= 60.0
        )
        if should_emit:
            self._emit_health(task, "failure", now, error)

    def _record_recovery(self, task: RefreshTask, now: float) -> None:
        if task.last_error is not None:
            task.state_changed_at = now
            task.last_error = None
            self._emit_health(task, "recovery", now, None)
        else:
            task.last_error = None

    def _emit_health(
        self,
        task: RefreshTask,
        state: str,
        now: float,
        error: str | None,
    ) -> None:
        event = RefreshHealthEvent(
            task_id=task.task_id,
            state=state,
            occurred_at=now,
            error=error,
        )
        task.last_health_event_at = now
        task.last_health_error = error
        try:
            self._health_event(event)
        except Exception:
            pass

    @staticmethod
    def _journal_health_event(event: RefreshHealthEvent) -> None:
        from infra.crash_journal import log_runtime_event

        log_runtime_event(
            "refresh.health",
            task_id=event.task_id,
            state=event.state,
            error=event.error,
            occurred_at=event.occurred_at,
        )

    def _ordered_tasks(self) -> tuple[RefreshTask, ...]:
        cached = self._execution_order
        if cached is not None:
            return cached
        tasks = self._tasks
        unknown = sorted(
            {dependency for task in tasks.values() for dependency in task.after if dependency not in tasks}
        )
        if unknown:
            raise ValueError(f"Unknown refresh task dependencies: {', '.join(unknown)}")
        registration = {task_id: index for index, task_id in enumerate(tasks)}
        outgoing = {task_id: [] for task_id in tasks}
        indegree = {task_id: 0 for task_id in tasks}
        for task in tasks.values():
            for dependency in task.after:
                outgoing[dependency].append(task.task_id)
                indegree[task.task_id] += 1
        ready = [task_id for task_id, count in indegree.items() if count == 0]
        result: list[RefreshTask] = []
        while ready:
            ready.sort(key=lambda task_id: (tasks[task_id].phase, registration[task_id]))
            task_id = ready.pop(0)
            result.append(tasks[task_id])
            for dependent in outgoing[task_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if len(result) != len(tasks):
            cycle = sorted(task_id for task_id, count in indegree.items() if count > 0)
            raise ValueError(f"Refresh task dependency cycle: {', '.join(cycle)}")
        self._execution_order = tuple(result)
        return self._execution_order

    @staticmethod
    def _is_due(task: RefreshTask, now: float) -> bool:
        interval_ms = (
            task.failure_retry_ms
            if task.last_error is not None and task.failure_retry_ms is not None
            else task.interval_ms
        )
        return task.last_started_at is None or now - task.last_started_at >= interval_ms / 1000.0

    @staticmethod
    def _next_due_at(task: RefreshTask, now: float) -> float | None:
        if task.last_started_at is None:
            return now
        interval_ms = (
            task.failure_retry_ms
            if task.last_error is not None and task.failure_retry_ms is not None
            else task.interval_ms
        )
        return task.last_started_at + interval_ms / 1000.0
