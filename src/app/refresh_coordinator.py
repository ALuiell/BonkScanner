"""Task scheduler for shared runtime refresh work.

The coordinator deliberately has no Qt dependency.  Its owner calls ``tick``
from the existing UI thread, keeping game-memory reads and tracker mutation
single-writer while allowing consumers to declare demand independently.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable


class RefreshTickContext:
    """Per-tick lazy cache shared by all due refresh tasks."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._errors: dict[str, Exception] = {}

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

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tasks: dict[str, RefreshTask] = {}

    def register(self, task: RefreshTask) -> None:
        if not task.task_id:
            raise ValueError("Refresh task id is required")
        if task.interval_ms < 1:
            raise ValueError("Refresh task interval must be positive")
        if task.task_id in self._tasks:
            raise ValueError(f"Refresh task already registered: {task.task_id}")
        self._tasks[task.task_id] = task

    def tick(self) -> tuple[str, ...]:
        now = self._clock()
        context = RefreshTickContext()
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
        now = self._clock()
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
