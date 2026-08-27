"""Behaviour of the slider-drag rate limiter.

Every case drives `UiUpdateThrottle` over an injected clock and an injected
scheduler, so the coalescing is asserted directly rather than inferred from a
Qt event loop the suite does not run. The Qt-backed default is covered by its
own fallback case below -- the one that matters, because a scheduler that
silently drops the trailing callback would lose the last frame of every drag
and no timing-free test would notice.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from ui.throttle import UiUpdateThrottle, batched_updates, qt_schedule


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeScheduler:
    """Records queued timeouts instead of delivering them."""

    def __init__(self) -> None:
        self.queued: list[tuple[float, object]] = []

    def __call__(self, delay_ms, callback) -> None:
        self.queued.append((delay_ms, callback))

    def fire(self) -> None:
        delay_ms, callback = self.queued.pop(0)
        callback()


def build_throttle(interval_ms: float = 100.0):
    clock = FakeClock()
    scheduler = FakeScheduler()
    throttle = UiUpdateThrottle(interval_ms, clock=clock, schedule=scheduler)
    return throttle, clock, scheduler


class UiUpdateThrottleTests(unittest.TestCase):
    def test_first_request_runs_immediately(self) -> None:
        """A single arrow-key step must not wait for a frame."""
        throttle, _clock, scheduler = build_throttle()
        runs = []

        self.assertTrue(throttle.request(lambda: runs.append("a")))

        self.assertEqual(["a"], runs)
        self.assertEqual([], scheduler.queued)

    def test_request_inside_the_window_is_queued_not_run(self) -> None:
        throttle, _clock, scheduler = build_throttle()
        runs = []
        throttle.request(lambda: runs.append("a"))

        self.assertFalse(throttle.request(lambda: runs.append("b")))

        self.assertEqual(["a"], runs)
        self.assertTrue(throttle.has_pending)
        self.assertEqual(1, len(scheduler.queued))

    def test_queued_callback_is_the_latest_one_and_arms_one_timer(self) -> None:
        """Frames the user has already scrubbed past are never rendered."""
        throttle, _clock, scheduler = build_throttle()
        runs = []
        throttle.request(lambda: runs.append("a"))
        for label in ("b", "c", "d"):
            throttle.request(lambda label=label: runs.append(label))

        self.assertEqual(1, len(scheduler.queued), "one timer for the whole burst")
        scheduler.fire()

        self.assertEqual(["a", "d"], runs)
        self.assertFalse(throttle.has_pending)

    def test_timer_delay_covers_only_the_remainder_of_the_window(self) -> None:
        throttle, clock, scheduler = build_throttle(interval_ms=100.0)
        throttle.request(lambda: None)
        clock.advance(0.030)
        throttle.request(lambda: None)

        delay_ms, _callback = scheduler.queued[0]
        self.assertAlmostEqual(70.0, delay_ms, places=6)

    def test_request_after_the_window_runs_immediately_again(self) -> None:
        throttle, clock, scheduler = build_throttle(interval_ms=100.0)
        runs = []
        throttle.request(lambda: runs.append("a"))
        clock.advance(0.150)

        self.assertTrue(throttle.request(lambda: runs.append("b")))

        self.assertEqual(["a", "b"], runs)
        self.assertEqual([], scheduler.queued)

    def test_flush_runs_the_queued_callback_now(self) -> None:
        throttle, _clock, _scheduler = build_throttle()
        runs = []
        throttle.request(lambda: runs.append("a"))
        throttle.request(lambda: runs.append("b"))

        self.assertTrue(throttle.flush())

        self.assertEqual(["a", "b"], runs)
        self.assertFalse(throttle.flush(), "nothing left to flush")

    def test_cancel_drops_the_queued_callback(self) -> None:
        """For frames made meaningless, not merely stale -- see the tab callers."""
        throttle, _clock, scheduler = build_throttle()
        runs = []
        throttle.request(lambda: runs.append("a"))
        throttle.request(lambda: runs.append("b"))

        throttle.cancel()
        scheduler.fire()

        self.assertEqual(["a"], runs)
        self.assertFalse(throttle.has_pending)

    def test_timeout_with_nothing_queued_is_harmless(self) -> None:
        throttle, _clock, scheduler = build_throttle()
        throttle.request(lambda: None)
        throttle.request(lambda: None)
        throttle.cancel()

        scheduler.fire()  # must not raise

        self.assertFalse(throttle.has_pending)


class QtScheduleFallbackTests(unittest.TestCase):
    """Both branches of the default scheduler.

    Patched rather than observed, because whether a `QApplication` exists
    during a suite run depends on which other test files ran first -- exactly
    the kind of ambient state this scheduler must not be sensitive to.
    """

    def test_without_a_qapplication_the_callback_runs_inline(self) -> None:
        """A queued timeout would never be delivered, so the frame would be lost."""
        from PySide6.QtWidgets import QApplication

        runs = []
        with patch.object(QApplication, "instance", staticmethod(lambda: None)):
            qt_schedule(5000.0, lambda: runs.append("ran"))

        self.assertEqual(["ran"], runs)

    def test_with_a_qapplication_the_callback_is_deferred_to_a_timer(self) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        runs = []
        single_shot = MagicMock()
        with patch.object(QApplication, "instance", staticmethod(lambda: object())):
            with patch.object(QTimer, "singleShot", single_shot):
                qt_schedule(33.0, lambda: runs.append("ran"))

        self.assertEqual([], runs, "deferred, not run")
        single_shot.assert_called_once()
        self.assertEqual(33, single_shot.call_args.args[0])

    def test_qobject_context_is_passed_to_the_timer(self) -> None:
        """Qt cancels the callback if its owning widget is destroyed."""
        from PySide6.QtCore import QObject, QTimer
        from PySide6.QtWidgets import QApplication

        context = QObject()
        callback = lambda: None
        single_shot = MagicMock()
        with patch.object(QApplication, "instance", staticmethod(lambda: object())):
            with patch.object(QTimer, "singleShot", single_shot):
                qt_schedule(33.0, callback, context=context)

        single_shot.assert_called_once_with(33, context, callback)

    def test_throttle_uses_its_qobject_context_for_default_scheduling(self) -> None:
        from PySide6.QtCore import QObject

        context = QObject()
        clock = FakeClock()
        with patch("ui.throttle.qt_schedule") as schedule:
            throttle = UiUpdateThrottle(100.0, clock=clock, qt_context=context)
            throttle.request(lambda: None)
            throttle.request(lambda: None)

        self.assertEqual(schedule.call_count, 1)
        self.assertIs(schedule.call_args.kwargs["context"], context)

    def test_destroyed_context_releases_the_pending_widget_callback(self) -> None:
        from PySide6.QtCore import QObject

        context = QObject()
        clock = FakeClock()
        scheduler = FakeScheduler()
        throttle = UiUpdateThrottle(
            100.0,
            clock=clock,
            schedule=scheduler,
            qt_context=context,
        )
        throttle.request(lambda: None)
        throttle.request(context.objectName)
        self.assertTrue(throttle.has_pending)

        context.destroyed.emit()

        self.assertFalse(throttle.has_pending)
        scheduler.fire()


class FakeBatchWidget:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.calls: list[bool] = []

    def updatesEnabled(self) -> bool:
        return self.enabled

    def setUpdatesEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.calls.append(bool(enabled))


class BatchedUpdatesTests(unittest.TestCase):
    def test_repaints_are_held_for_the_body_and_restored_after(self) -> None:
        widget = FakeBatchWidget()

        with batched_updates(widget):
            self.assertFalse(widget.enabled)

        self.assertEqual([False, True], widget.calls)
        self.assertTrue(widget.enabled)

    def test_repaints_are_restored_even_when_the_body_raises(self) -> None:
        widget = FakeBatchWidget()

        with self.assertRaises(ValueError):
            with batched_updates(widget):
                raise ValueError("render failed")

        self.assertEqual([False, True], widget.calls)

    def test_nested_batches_leave_the_repaint_to_the_outer_one(self) -> None:
        widget = FakeBatchWidget()

        with batched_updates(widget):
            with batched_updates(widget):
                pass
            self.assertFalse(widget.enabled, "inner batch must not re-enable")

        self.assertEqual([False, True], widget.calls)

    def test_unbuilt_tab_is_a_no_op(self) -> None:
        with batched_updates(None):
            pass


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
