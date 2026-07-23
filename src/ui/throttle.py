"""Rate limiting for slider-driven UI work.

A ``QSlider`` emits ``valueChanged`` once per pixel of mouse travel -- hundreds
of events a second during a drag. The Compare Runs and Recordings timelines
answered every one of them with the full render: a nearest-snapshot search per
side, up to seven diff formatters, and a few dozen ``QLabel``/``QTextEdit``
writes, all synchronously on the UI thread. The drag is then bounded by how
fast the heaviest frame renders, not by how fast the user moves.

Two primitives, both deliberately small:

``UiUpdateThrottle``
    Coalesces repeated requests down to one run per interval. The *first*
    request in a quiet period runs immediately -- a single arrow-key step on the
    slider must not be delayed by a frame -- and everything arriving inside the
    window collapses into one trailing run of the **latest** callback. That is
    the throttle-with-trailing-edge shape, not a pure debounce: a long drag
    keeps repainting at the interval rather than showing nothing until the user
    stops.

``batched_updates``
    Holds Qt repaints for the duration of a multi-widget update so the layout
    engine does one pass instead of one per widget.

No-event-loop fallback, and its limit
=====================================

``QTimer.singleShot`` needs a running event loop to ever deliver its timeout.
The suite builds these components through their real constructors and does not
run one, so a deferred callback would be scheduled and then silently dropped --
a throttle that loses the final frame of a drag is a correctness bug, and one
that would only show up outside the tests meant to cover it. When there is no
``QApplication`` instance at all the scheduler therefore runs the callback
inline: with nothing to deliver the timeout, there is nothing to throttle *for*.

That guard is deliberately narrow, and the limit matters for whoever writes the
next test here. Some suite files *do* construct a ``QApplication`` without ever
exec'ing it, and any file running after one of those sees an instance -- so the
default scheduler takes the ``QTimer`` branch and the queued frame never
arrives. **A test that asserts on coalescing must inject its own throttle** over
a fake clock and scheduler; every component that owns one takes it as a
constructor argument for exactly this reason.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Callable


#: Default coalescing window. ~30 FPS: fast enough that a drag looks
#: continuous, slow enough that the heavy diff path runs a bounded number of
#: times per second regardless of mouse sampling rate.
DEFAULT_UI_THROTTLE_MS = 33.0


def qt_schedule(delay_ms: float, callback: Callable[[], None]) -> None:
    """Run ``callback`` after ``delay_ms``, or now if nothing can deliver it.

    Imported lazily so this module stays importable (and testable) without Qt.
    """
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover -- Qt is a hard dependency in the app
        callback()
        return

    if QApplication.instance() is None:
        # See the module header: no event loop, so a queued timeout would never
        # fire and the trailing frame would be lost.
        callback()
        return
    QTimer.singleShot(max(int(delay_ms), 0), callback)


class UiUpdateThrottle:
    """Coalesce repeated render requests to at most one per interval."""

    def __init__(
        self,
        interval_ms: float = DEFAULT_UI_THROTTLE_MS,
        *,
        clock: Callable[[], float] | None = None,
        schedule: Callable[[float, Callable[[], None]], None] | None = None,
    ) -> None:
        self._interval = max(float(interval_ms), 0.0) / 1000.0
        self._clock = clock or time.monotonic
        self._schedule = schedule or qt_schedule
        self._last_run: float | None = None
        self._pending: Callable[[], None] | None = None
        self._timer_armed = False

    @property
    def has_pending(self) -> bool:
        return self._pending is not None

    def request(self, callback: Callable[[], None]) -> bool:
        """Run ``callback`` now, or queue it as the interval's trailing run.

        Returns ``True`` when it ran synchronously. A queued callback replaces
        any previous one: mid-drag frames the user has already scrolled past
        are work nobody will ever see.
        """
        now = self._clock()
        if self._last_run is None or (now - self._last_run) >= self._interval:
            self._pending = None
            self._run(callback)
            return True

        self._pending = callback
        if not self._timer_armed:
            self._timer_armed = True
            remaining = self._interval - (now - self._last_run)
            self._schedule(max(remaining * 1000.0, 1.0), self._on_timeout)
        return False

    def flush(self) -> bool:
        """Run any queued callback immediately. Returns whether one ran."""
        pending, self._pending = self._pending, None
        if pending is None:
            return False
        self._run(pending)
        return True

    def cancel(self) -> None:
        """Drop any queued callback without running it.

        For the case where the queued frame has been made meaningless -- a new
        recording loaded, the selection cleared -- rather than merely stale.
        """
        self._pending = None

    def _on_timeout(self) -> None:
        self._timer_armed = False
        self.flush()

    def _run(self, callback: Callable[[], None]) -> None:
        self._last_run = self._clock()
        callback()


@contextmanager
def batched_updates(widget):
    """Suspend ``widget``'s repaints for the body, then repaint once.

    A no-op for ``None`` and for the fake widgets the suite builds, so callers
    do not need to know whether the tab has been built yet.
    """
    setter = getattr(widget, "setUpdatesEnabled", None)
    if not callable(setter):
        yield
        return

    was_enabled = True
    reader = getattr(widget, "updatesEnabled", None)
    if callable(reader):
        was_enabled = bool(reader())
    if not was_enabled:
        # Already inside an outer batch; that one owns the repaint.
        yield
        return

    setter(False)
    try:
        yield
    finally:
        setter(True)
