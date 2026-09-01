from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from app.refresh_coordinator import RefreshCoordinator, RefreshTask, RefreshTickContext


class RefreshCoordinatorTests(unittest.TestCase):
    def test_dependencies_override_phase_and_preserve_stable_registration_order(self) -> None:
        calls = []
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        coordinator.register(RefreshTask("second", 1, lambda: True, lambda _ctx: calls.append("second"), phase=0, after=("first",)))
        coordinator.register(RefreshTask("peer", 1, lambda: True, lambda _ctx: calls.append("peer"), phase=0))
        coordinator.register(RefreshTask("first", 1, lambda: False, lambda _ctx: self.fail("inactive predecessor must not run"), phase=10))

        self.assertEqual(coordinator.tick(), ("peer", "second"))
        self.assertEqual(calls, ["peer", "second"])

    def test_unknown_dependency_is_rejected_before_any_task_runs(self) -> None:
        calls = []
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        coordinator.register(RefreshTask("task", 1, lambda: True, lambda _ctx: calls.append(1), after=("missing",)))
        with self.assertRaisesRegex(ValueError, "Unknown refresh task dependencies"):
            coordinator.tick()
        self.assertEqual(calls, [])

    def test_dependency_cycle_is_rejected_before_any_task_runs(self) -> None:
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        coordinator.register(RefreshTask("a", 1, lambda: True, lambda _ctx: None, after=("b",)))
        coordinator.register(RefreshTask("b", 1, lambda: True, lambda _ctx: None, after=("a",)))
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            coordinator.tick()

    def test_failure_events_are_throttled_and_recovery_is_always_emitted(self) -> None:
        now = [10.0]
        events = []
        outcomes = [False, False, False, True]
        coordinator = RefreshCoordinator(clock=lambda: now[0], health_event=events.append)
        coordinator.register(RefreshTask("health", 1, lambda: True, lambda _ctx: outcomes.pop(0)))

        coordinator.tick()
        now[0] += 1.0
        coordinator.tick()
        now[0] += 60.0
        coordinator.tick()
        now[0] += 1.0
        coordinator.tick()

        self.assertEqual([event.state for event in events], ["failure", "failure", "recovery"])
        diagnostics = coordinator.diagnostics()[0]
        self.assertIsNotNone(diagnostics.last_duration_ms)
        self.assertEqual(diagnostics.state_changed_at, now[0])

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

    def test_failed_task_uses_short_retry_then_returns_to_normal_interval(self) -> None:
        now = [10.0]
        outcomes = iter((False, True, True))
        coordinator = RefreshCoordinator(clock=lambda: now[0])
        coordinator.register(
            RefreshTask(
                "snapshot",
                10_000,
                lambda: True,
                lambda _context: next(outcomes),
                failure_retry_ms=1_000,
            )
        )

        self.assertEqual(coordinator.tick(), ("snapshot",))
        now[0] += 0.999
        self.assertEqual(coordinator.tick(), ())
        now[0] += 0.001
        self.assertEqual(coordinator.tick(), ("snapshot",))

        # Success clears the retry state; the ordinary ten-second cadence owns
        # the next due time again.
        now[0] += 1.0
        self.assertEqual(coordinator.tick(), ())
        now[0] += 9.0
        self.assertEqual(coordinator.tick(), ("snapshot",))

    def test_required_failure_does_not_block_other_tasks(self) -> None:
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        coordinator.register(
            RefreshTask(
                "bad_required",
                500,
                lambda: (_ for _ in ()).throw(RuntimeError("demand failed")),
                lambda _context: self.fail("task with failed demand must not run"),
            )
        )
        coordinator.register(RefreshTask("good", 500, lambda: True, lambda _context: True))

        self.assertEqual(coordinator.tick(), ("good",))
        diagnostics = {entry.task_id: entry for entry in coordinator.diagnostics()}
        self.assertFalse(diagnostics["bad_required"].active)
        self.assertEqual(diagnostics["bad_required"].failure_count, 1)
        self.assertIn("required check failed", diagnostics["bad_required"].last_error or "")
        self.assertTrue(diagnostics["good"].active)

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


class PassIdentityTests(unittest.TestCase):
    """Step 28a: the coordinator owns the pass counter, not the context."""

    def test_pass_id_increments_once_per_tick_not_once_per_task(self) -> None:
        seen_pass_ids: list[int] = []
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        coordinator.register(
            RefreshTask("a", 500, lambda: True, lambda ctx: seen_pass_ids.append(ctx.pass_id))
        )
        coordinator.register(
            RefreshTask("b", 500, lambda: True, lambda ctx: seen_pass_ids.append(ctx.pass_id))
        )

        coordinator.tick()

        # Two tasks in one tick share one context and therefore one pass_id --
        # the counter must not have incremented per task.
        self.assertEqual(seen_pass_ids, [1, 1])

    def test_two_contexts_from_one_coordinator_never_share_a_pass_id(self) -> None:
        now = [10.0]
        pass_ids: list[int] = []
        coordinator = RefreshCoordinator(clock=lambda: now[0])
        coordinator.register(RefreshTask("a", 500, lambda: True, lambda ctx: pass_ids.append(ctx.pass_id)))

        coordinator.tick()
        now[0] += 0.5
        coordinator.tick()
        now[0] += 0.5
        coordinator.tick()

        self.assertEqual(pass_ids, [1, 2, 3])
        self.assertEqual(len(set(pass_ids)), len(pass_ids))

    def test_started_at_is_monotonic_across_ticks(self) -> None:
        now = [10.0]
        started_ats: list[float] = []
        coordinator = RefreshCoordinator(clock=lambda: now[0])
        coordinator.register(
            RefreshTask("a", 500, lambda: True, lambda ctx: started_ats.append(ctx.started_at))
        )

        coordinator.tick()
        now[0] += 0.5
        coordinator.tick()

        self.assertEqual(started_ats, [10.0, 10.5])

    def test_rebuilding_the_coordinator_does_not_continue_the_old_numbering(self) -> None:
        """Ids are meaningless across a coordinator rebuild (section 12.3): a
        fresh coordinator is free to reuse ids a previous, discarded one used --
        there is nothing to compare them against.
        """
        pass_ids: list[int] = []
        now = [10.0]

        def make_coordinator() -> RefreshCoordinator:
            coordinator = RefreshCoordinator(clock=lambda: now[0])
            coordinator.register(
                RefreshTask("a", 500, lambda: True, lambda ctx: pass_ids.append(ctx.pass_id))
            )
            return coordinator

        first = make_coordinator()
        first.tick()
        now[0] += 0.5
        first.tick()
        second = make_coordinator()  # a rebuild mid-run
        second.tick()

        self.assertEqual(pass_ids, [1, 2, 1])


class SourceReadMetadataTests(unittest.TestCase):
    """Step 28a: per-source pass/timing metadata on ``RefreshTickContext``."""

    def test_one_factory_execution_per_pass_regardless_of_consumer_count(self) -> None:
        calls: list[str] = []
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        def factory():
            calls.append("read")
            return 42

        first = context.get_or_create_with_metadata("k", factory)
        second = context.get_or_create_with_metadata("k", factory)

        self.assertEqual(calls, ["read"])
        self.assertEqual((first, second), (42, 42))

    def test_two_consumers_see_the_same_value_and_pass_id(self) -> None:
        coordinator = RefreshCoordinator(clock=lambda: 10.0)
        observed_values: list[int] = []
        observed_pass_ids: list[int] = []

        def consume(ctx):
            value = ctx.get_or_create_with_metadata("k", lambda: 7)
            observed_values.append(value)
            observed_pass_ids.append(ctx.metadata_for("k").pass_id)

        coordinator.register(RefreshTask("a", 500, lambda: True, consume))
        coordinator.register(RefreshTask("b", 500, lambda: True, consume))

        coordinator.tick()

        self.assertEqual(observed_values, [7, 7])
        self.assertEqual(observed_pass_ids, [1, 1])

    def test_metadata_is_not_rewritten_on_a_cache_hit(self) -> None:
        clock_values = iter([1.0, 2.0, 100.0, 200.0])
        context = RefreshTickContext(
            pass_id=5, started_at=0.0, clock=lambda: next(clock_values)
        )

        context.get_or_create_with_metadata("k", lambda: 1)
        first_metadata = context.metadata_for("k")
        context.get_or_create_with_metadata("k", lambda: 1)
        second_metadata = context.metadata_for("k")

        self.assertEqual(first_metadata, second_metadata)
        self.assertEqual(first_metadata.started_at, 1.0)
        self.assertEqual(first_metadata.finished_at, 2.0)
        self.assertTrue(first_metadata.succeeded)
        self.assertEqual(first_metadata.pass_id, 5)

    def test_metadata_is_not_rewritten_on_a_cached_failure(self) -> None:
        clock_values = iter([1.0, 2.0, 100.0, 200.0])
        context = RefreshTickContext(
            pass_id=3, started_at=0.0, clock=lambda: next(clock_values)
        )

        def failing():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            context.get_or_create_with_metadata("k", failing)
        first_metadata = context.metadata_for("k")

        with self.assertRaises(RuntimeError):
            context.get_or_create_with_metadata("k", failing)
        second_metadata = context.metadata_for("k")

        self.assertEqual(first_metadata, second_metadata)
        self.assertFalse(first_metadata.succeeded)
        self.assertEqual(first_metadata.started_at, 1.0)
        self.assertEqual(first_metadata.finished_at, 2.0)

    def test_measured_span_covers_both_factory_executions(self) -> None:
        clock_values = iter([10.0, 10.1, 10.2, 10.4])
        context = RefreshTickContext(
            pass_id=1, started_at=10.0, clock=lambda: next(clock_values)
        )

        context.get_or_create_with_metadata("run_timer", lambda: 1.0)
        context.get_or_create_with_metadata("mob_kills", lambda: 0)

        run_timer_meta = context.metadata_for("run_timer")
        mob_kills_meta = context.metadata_for("mob_kills")
        span = max(run_timer_meta.finished_at, mob_kills_meta.finished_at) - min(
            run_timer_meta.started_at, mob_kills_meta.started_at
        )

        self.assertEqual(run_timer_meta.pass_id, mob_kills_meta.pass_id)
        self.assertAlmostEqual(span, 0.4)
