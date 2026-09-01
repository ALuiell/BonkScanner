"""Bounded latest-wins background loading lane."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
from typing import Any, Callable


@dataclass(frozen=True)
class _Request:
    generation: int
    value: Any
    load: Callable[[Any], Any]
    complete: Callable[[Any, Exception | None], None]


class LatestWinsLoader:
    """Run one request and retain at most the newest pending request."""

    def __init__(
        self,
        *,
        schedule: Callable[[Callable[[], None]], Any],
        thread_name: str = "latest-wins-loader",
    ) -> None:
        self._schedule = schedule
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name)
        self._lock = threading.Lock()
        self._active = False
        self._pending: _Request | None = None
        self._generation = 0
        self._disposed = False

    def submit(
        self,
        value: Any,
        *,
        load: Callable[[Any], Any],
        complete: Callable[[Any, Exception | None], None],
    ) -> int:
        with self._lock:
            if self._disposed:
                return self._generation
            self._generation += 1
            request = _Request(self._generation, value, load, complete)
            if self._active:
                self._pending = request
                return request.generation
            self._active = True
        self._launch(request)
        return request.generation

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            self._generation += 1
            self._pending = None
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _launch(self, request: _Request) -> None:
        try:
            self._executor.submit(self._run, request)
        except Exception as exc:
            self._finish(request, None, exc)

    def _run(self, request: _Request) -> None:
        try:
            result = request.load(request.value)
            error = None
        except Exception as exc:
            result = None
            error = exc
        self._finish(request, result, error)

    def _finish(self, request: _Request, result: Any, error: Exception | None) -> None:
        next_request = None
        with self._lock:
            if self._disposed:
                self._active = False
                return
            next_request, self._pending = self._pending, None
            self._active = next_request is not None

        def deliver() -> None:
            with self._lock:
                if self._disposed or request.generation != self._generation:
                    return
            request.complete(result, error)

        try:
            self._schedule(deliver)
        except Exception:
            pass
        if next_request is not None:
            self._launch(next_request)
