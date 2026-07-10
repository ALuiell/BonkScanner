"""Task scheduler for shared runtime refresh work.

The coordinator deliberately has no Qt dependency.  Its owner calls ``tick``
from the existing UI thread, keeping game-memory reads and tracker mutation
single-writer while allowing consumers to declare demand independently.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable


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
    run: Callable[[], bool | None]
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
        ran: list[str] = []
        for task in self._tasks.values():
            if not task.required() or not self._is_due(task, now):
                continue
            task.last_started_at = now
            try:
                succeeded = task.run()
            except Exception as exc:  # Diagnostics must not stop other tasks.
                task.failure_count += 1
                task.last_error = f"{type(exc).__name__}: {exc}"
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
        return tuple(
            RefreshTaskDiagnostics(
                task_id=task.task_id,
                active=bool(task.required()),
                last_started_at=task.last_started_at,
                last_succeeded_at=task.last_succeeded_at,
                last_error=task.last_error,
                failure_count=task.failure_count,
                next_due_at=self._next_due_at(task, now),
            )
            for task in self._tasks.values()
        )

    @staticmethod
    def _is_due(task: RefreshTask, now: float) -> bool:
        return task.last_started_at is None or now - task.last_started_at >= task.interval_ms / 1000.0

    @staticmethod
    def _next_due_at(task: RefreshTask, now: float) -> float | None:
        if task.last_started_at is None:
            return now
        return task.last_started_at + task.interval_ms / 1000.0
