"""Coalesced persistence for rapidly edited, already-applied preferences.

A queued top-level key is merged into the latest committed snapshot under the
repository lock. A synchronous save that superseded a queued value therefore
cannot be overwritten by an older queued value.
"""
from __future__ import annotations

from copy import deepcopy
import threading
import time

from app import config
from infra.crash_journal import log_runtime_event


class DeferredConfigSaves:
    def __init__(self, delay=0.3):
        self._delay = delay
        self._condition = threading.Condition()
        self._pending = {}
        self._thread = None
        self._closing = False
        self._error = ""
        self._due = 0.0

    def request(self, path, value, on_error=None):
        if len(path) != 1:
            raise ValueError("Deferred configuration paths must name a top-level key")
        value = deepcopy(value)
        with self._condition:
            if self._closing:
                raise RuntimeError("Configuration saving is shutting down")
            self._pending[path[0]] = (value, on_error)
            self._due = time.monotonic() + self._delay
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="ConfigSaveWorker", daemon=True)
                self._thread.start()
            self._condition.notify_all()

    def begin_shutdown(self):
        with self._condition:
            self._closing = True
            self._condition.notify_all()

    def complete(self):
        with self._condition:
            return self._thread is None or not self._thread.is_alive()

    def result(self):
        with self._condition:
            return self._error

    def is_closing(self):
        with self._condition:
            return self._closing

    def _run(self):
        while True:
            with self._condition:
                while not self._pending:
                    if self._closing:
                        return
                    self._condition.wait()
                delay = self._due - time.monotonic()
                if delay > 0 and not self._closing:
                    self._condition.wait(delay)
                    continue
                pending, self._pending = self._pending, {}
            try:
                with config.config_lock:
                    repository = config._repository
                    if repository is None:
                        raise RuntimeError("Load the configuration before saving it.")
                    candidate = repository.snapshot()
                    # Foreground edits supersede a queued value, including a
                    # synchronous save which ran before this worker acquired
                    # the lock. Never publish that older value afterward.
                    for key, (value, _on_error) in pending.items():
                        if config.user_config.get(key) == value:
                            candidate[key] = value
                    result = config.save_config(candidate)
                    if not result.success:
                        raise OSError(result.reason)
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                with self._condition:
                    self._error = error
                log_runtime_event("configuration.deferred_save_failed", error=error)
                for _value, on_error in pending.values():
                    if on_error is not None:
                        try:
                            on_error(error)
                        except Exception:
                            pass


_saves = DeferredConfigSaves()


def start_config_saves():
    """Start a new application lifetime after the previous one fully stopped."""
    global _saves
    if _saves.is_closing():
        if not _saves.complete():
            raise RuntimeError("Previous configuration saving has not stopped")
        _saves = DeferredConfigSaves()


def request_config_save(path, value, on_error=None):
    _saves.request(path, value, on_error)


def begin_config_save_shutdown():
    _saves.begin_shutdown()


def config_save_shutdown_complete():
    return _saves.complete()


def config_save_shutdown_result():
    return _saves.result()
