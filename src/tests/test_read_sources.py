"""Step 28a: ``read_memory_source``'s health-accounting contract.

See docs/updates/architecture_updates/step_28_plan.md section 12.5 for the
normative rule this file exists to pin down: one physical read attempt
produces at most one success or one failure record, never once per consumer
of a cached outcome. The combat-pair (``RUN_TIMER``/``MOB_KILLS``) tests that
exercise this through ``_refresh_combat_metrics_task`` live in
``test_combat_pair_pass.py`` (step 28b).
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from app.read_sources import RUN_TIMER, read_memory_source
from app.refresh_coordinator import RefreshTickContext
from infra.memory.reader import MemoryReadError
from tests.support.player_stats_memory import build_player_stats_memory


class ReadMemorySourceHealthTests(unittest.TestCase):
    def test_one_success_record_for_one_physical_successful_read(self) -> None:
        successes = []
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        value = read_memory_source(
            context,
            "k",
            lambda: 42,
            on_success=lambda: successes.append(1),
            on_failure=lambda exc: self.fail("must not be called"),
        )

        self.assertEqual(value, 42)
        self.assertEqual(len(successes), 1)

    def test_cache_hit_records_no_further_success(self) -> None:
        successes = []
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        for _ in range(3):
            read_memory_source(
                context,
                "k",
                lambda: 42,
                on_success=lambda: successes.append(1),
                on_failure=lambda exc: self.fail("must not be called"),
            )

        self.assertEqual(len(successes), 1)

    def test_one_failure_record_for_one_physical_failed_read_across_consumers(self) -> None:
        """Two different task-level call sites reading the same key in one
        pass both hit the cached exception; the health failure must still be
        recorded exactly once, not once per consumer."""
        failures = []

        def factory():
            raise MemoryReadError("boom")

        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        for _ in range(2):
            with self.assertRaises(MemoryReadError):
                read_memory_source(
                    context,
                    "k",
                    factory,
                    on_success=lambda: self.fail("must not be called"),
                    on_failure=lambda exc: failures.append(exc),
                )

        self.assertEqual(len(failures), 1)

    def test_replaying_a_cached_exception_does_not_accelerate_the_reconnect_streak(self) -> None:
        """Real ``PlayerStatsMemory``, not a fake counter: the streak policy
        itself is what must not double-count. See step_28_plan.md section
        12.9's explicit requirement."""
        memory, _world = build_player_stats_memory()
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        def factory():
            raise MemoryReadError("boom")

        # Simulate two consumers of the same source in one pass, as the failure
        # -isolation guarantee promises they may be.
        for _ in range(2):
            with self.assertRaises(MemoryReadError):
                read_memory_source(
                    context,
                    RUN_TIMER,
                    factory,
                    on_success=memory.record_memory_success,
                    on_failure=memory.record_memory_failure,
                )

        self.assertEqual(memory._player_stats_memory_error_streak, 1)

    def test_reused_exception_is_counted_again_on_a_new_pass(self) -> None:
        """Health accounting belongs to a physical attempt in one context,
        not to the lifetime of an exception object a factory may reuse."""
        failure = MemoryReadError("reused")
        failures = []

        def factory():
            raise failure

        for pass_id in (1, 2):
            context = RefreshTickContext(
                pass_id=pass_id,
                started_at=float(pass_id),
                clock=lambda: 0.0,
            )
            with self.assertRaises(MemoryReadError):
                read_memory_source(
                    context,
                    "k",
                    factory,
                    on_failure=lambda exc: failures.append(exc),
                )

        self.assertEqual(failures, [failure, failure])


if __name__ == "__main__":
    unittest.main()
