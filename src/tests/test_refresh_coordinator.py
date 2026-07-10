from __future__ import annotations

import unittest

from refresh_coordinator import RefreshCoordinator, RefreshTask


class RefreshCoordinatorTests(unittest.TestCase):
    def test_runs_demanded_task_once_per_interval(self) -> None:
        now = [10.0]
        calls: list[str] = []
        coordinator = RefreshCoordinator(clock=lambda: now[0])
        coordinator.register(
            RefreshTask("combat", 500, lambda: True, lambda _context: calls.append("combat"))
        )

        self.assertEqual(coordinator.tick(), ("combat",))
        self.assertEqual(coordinator.tick(), ())
        now[0] += 0.5
        self.assertEqual(coordinator.tick(), ("combat",))
        self.assertEqual(calls, ["combat", "combat"])

    def test_demanded_false_does_not_consume_interval(self) -> None:
        now = [10.0]
        active = [False]
        calls: list[str] = []
        coordinator = RefreshCoordinator(clock=lambda: now[0])
        coordinator.register(
            RefreshTask("chests", 10_000, lambda: active[0], lambda _context: calls.append("chests"))
        )

        self.assertEqual(coordinator.tick(), ())
        active[0] = True
        self.assertEqual(coordinator.tick(), ("chests",))
        self.assertEqual(calls, ["chests"])

    def test_failure_is_reported_without_blocking_other_tasks(self) -> None:
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        coordinator.register(RefreshTask("bad", 500, lambda: True, lambda _context: False))
        coordinator.register(RefreshTask("good", 500, lambda: True, lambda _context: True))

        self.assertEqual(coordinator.tick(), ("bad", "good"))
        diagnostics = {entry.task_id: entry for entry in coordinator.diagnostics()}
        self.assertEqual(diagnostics["bad"].failure_count, 1)
        self.assertEqual(diagnostics["good"].failure_count, 0)

    def test_tasks_share_a_tick_context(self) -> None:
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        factory_calls: list[str] = []
        values: list[int] = []

        def read_owner(context):
            values.append(context.get_or_create("owner", lambda: factory_calls.append("owner") or 42))

        coordinator.register(RefreshTask("powerups", 500, lambda: True, read_owner))
        coordinator.register(RefreshTask("chaos", 500, lambda: True, read_owner))

        self.assertEqual(coordinator.tick(), ("powerups", "chaos"))
        self.assertEqual(factory_calls, ["owner"])
        self.assertEqual(values, [42, 42])
