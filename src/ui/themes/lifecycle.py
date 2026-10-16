"""Small, explicit resource ownership for appearance instances (GUI thread only)."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QWidget
import shiboken6

log = logging.getLogger(__name__)


class ThemeResources:
    """LIFO cleanup shared by failed preparation and normal disposal.

    Register a resource immediately after acquisition. A constructor that raises
    before returning still has to protect its own partial Qt allocation. Leaving
    the context normally retains the resources; leaving with an error closes it.
    Closing is idempotent and a failing callback cannot skip the remaining ones.
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[[], None]] = []
        self.closed = False

    def _ensure_open(self) -> None:
        if self.closed:
            raise RuntimeError("Appearance resources are already closed")

    def callback(self, function, /, *args, **kwargs) -> None:
        self._ensure_open()
        self._callbacks.append(lambda: function(*args, **kwargs))

    def own(self, resource, *, dispose=None):
        """Own a disposable component, or hide/stop and delete a Qt object."""
        self._ensure_open()
        cleanup = dispose or getattr(resource, "dispose", None)
        if callable(cleanup):
            self.callback(cleanup)
        elif isinstance(resource, QObject):
            self.callback(self._delete_qt, resource)
        else:
            raise TypeError("Appearance resource needs a dispose callback")
        return resource

    @staticmethod
    def _delete_qt(resource: QObject) -> None:
        if not shiboken6.isValid(resource):
            return
        if isinstance(resource, QTimer):
            resource.stop()
        if isinstance(resource, QWidget):
            resource.hide()
        resource.deleteLater()

    def connect(self, signal, slot) -> None:
        self._ensure_open()
        signal.connect(slot)
        self.callback(signal.disconnect, slot)

    def event_filter(self, watched: QObject, observer: QObject) -> None:
        self._ensure_open()
        watched.installEventFilter(observer)
        self.callback(watched.removeEventFilter, observer)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        callbacks, self._callbacks = self._callbacks, []
        for callback in reversed(callbacks):
            try:
                callback()
            except Exception:
                log.exception("Cannot release an appearance resource")

    def __enter__(self):
        if self.closed:
            raise RuntimeError("Appearance resources are already closed")
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.close()
        return False
