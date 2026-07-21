"""Pure-service tests for `PlayerStatsMemory`, built through its real
constructor via `tests/support/player_stats_memory.py` -- no `object.__new__`
double, no borrowed MRO.

The reconnect streak policy is also covered exhaustively by
`tools/step20_memory_trace.py` and its mutation harness; these are the
suite-visible half, and they exist to exercise the *constructed* service the
way production builds it, so a broken constructor fails a test rather than only
a local trace.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app.snapshot_store import LiveSnapshotStore
from infra.memory.reader import MemoryReadError
from tests.support.player_stats_memory import build_player_stats_memory


class _CountingClient:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class PlayerStatsMemoryTests(unittest.TestCase):
    def test_memory_failure_streak_reconnects_at_threshold(self) -> None:
        client = _CountingClient()
        service, world = build_player_stats_memory(stats_client=client)

        service.record_memory_failure(MemoryReadError("1"))
        service.record_memory_failure(MemoryReadError("2"))
        self.assertEqual(client.closed, 0)
        self.assertIsNotNone(world.stats_client)

        service.record_memory_failure(MemoryReadError("3"))
        self.assertEqual(client.closed, 1)
        self.assertIsNone(world.stats_client)
        self.assertEqual(service._player_stats_memory_error_streak, 0)

    def test_game_data_failure_streak_reconnects_at_threshold(self) -> None:
        client = _CountingClient()
        service, world = build_player_stats_memory(game_data_client=client)

        for _ in range(3):
            service.record_game_data_failure(MemoryReadError("boom"))

        self.assertEqual(client.closed, 1)
        self.assertIsNone(world.game_data_client)
        self.assertEqual(service._player_stats_game_data_memory_error_streak, 0)

    def test_success_resets_the_streak_mid_climb(self) -> None:
        service, _ = build_player_stats_memory(stats_client=_CountingClient())
        service.record_memory_failure(MemoryReadError("1"))
        service.record_memory_failure(MemoryReadError("2"))
        service.record_memory_success()
        service.record_memory_failure(MemoryReadError("3"))
        self.assertEqual(service._player_stats_memory_error_streak, 1)

    def test_non_memory_error_is_ignored(self) -> None:
        client = _CountingClient()
        service, world = build_player_stats_memory(game_data_client=client)
        for _ in range(5):
            service.record_game_data_failure(ValueError("nonsense"))
        self.assertEqual(client.closed, 0)
        self.assertIsNotNone(world.game_data_client)
        self.assertEqual(service._player_stats_game_data_memory_error_streak, 0)

    def test_close_stats_client_resets_match_metadata_but_keeps_last_items(self) -> None:
        store = LiveSnapshotStore()
        store.last_seed = 4242
        store.last_run_timer = 91.5
        store.last_known_items = ("Key x1",)
        service, world = build_player_stats_memory(
            stats_client=_CountingClient(), snapshot_store=store
        )
        service._player_stats_memory_error_streak = 2

        service.close_player_stats_client()

        self.assertIsNone(world.stats_client)
        self.assertEqual(service._player_stats_memory_error_streak, 0)
        self.assertIsNone(store.last_seed)
        self.assertIsNone(store.last_run_timer)
        # reset_match_metadata is not reset_for_new_match: last-known items survive.
        self.assertEqual(store.last_known_items, ("Key x1",))

    def test_close_swallows_a_raising_client(self) -> None:
        raising = SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("gone")))
        service, world = build_player_stats_memory(game_data_client=raising)
        # Must not propagate; the client reference is still dropped.
        service.close_player_stats_game_data_client()
        self.assertIsNone(world.game_data_client)


if __name__ == "__main__":
    unittest.main()
