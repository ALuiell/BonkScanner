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
from app.player_stats_source import FullPlayerSample
from infra.memory.reader import MemoryReadError
from tests.support.player_stats_memory import build_player_stats_memory


class _CountingClient:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class PlayerStatsMemoryTests(unittest.TestCase):
    def test_full_sample_preserves_the_legacy_tuple_field_order(self) -> None:
        values = (
            {"Damage": 1},
            ("Wrench x1",),
            True,
            (),
            False,
            (),
            True,
            ("Clover",),
            True,
            (),
            False,
            12.5,
            3.0,
            60.0,
            42,
            7,
            1234,
            0x3000,
            2,
            ("Forbidden",),
            True,
            False,
        )

        sample = FullPlayerSample(*values)

        self.assertEqual(sample.as_legacy_tuple(), values)
        with self.assertRaises(TypeError):
            sample.stats["Damage"] = 2

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

    def test_a_non_memory_error_still_recycles_the_game_data_client(self) -> None:
        """It used to be ignored, and that made this path's failures permanent.

        An unrecognised exception returned early, the streak never reached the
        threshold, and the client was never recycled -- so a stale game-data
        client kept answering until the app was restarted. Observed live on
        2026-07-23: `get_map_activity_values` came back empty, `refresh_now`
        skipped the powerup map-context publish, the context expired, and every
        powerup lost its start/end while the rest of the app looked healthy.
        """
        client = _CountingClient()
        service, world = build_player_stats_memory(game_data_client=client)

        for _ in range(3):
            service.record_game_data_failure(ValueError("nonsense"))

        self.assertEqual(client.closed, 1)
        self.assertIsNone(world.game_data_client)
        self.assertEqual(service._player_stats_game_data_memory_error_streak, 0)

    def test_a_per_source_streak_survives_a_sibling_read_succeeding(self) -> None:
        """This is why the shared streak could never recycle anything.

        Several game-data reads run per tick and every one of them zeroes the
        shared streak on success, so one persistently failing read climbs to 1
        and is knocked straight back to 0 by its neighbours. That is the reason
        the stale client observed live on 2026-07-23 survived until the app was
        restarted -- widening the exception filter alone would not have helped.
        """
        client = _CountingClient()
        service, world = build_player_stats_memory(game_data_client=client)

        for _ in range(3):
            # The tick's other game-data reads succeed, as they did live.
            service.record_game_data_success()
            service.record_game_data_source_failure("map_activity", MemoryReadError("empty"))

        self.assertEqual(client.closed, 1)
        self.assertIsNone(world.game_data_client)

    def test_a_per_source_streak_is_reset_by_its_own_success(self) -> None:
        client = _CountingClient()
        service, _ = build_player_stats_memory(game_data_client=client)

        service.record_game_data_source_failure("map_activity", MemoryReadError("1"))
        service.record_game_data_source_failure("map_activity", MemoryReadError("2"))
        service.record_game_data_source_success("map_activity")
        service.record_game_data_source_failure("map_activity", MemoryReadError("3"))

        self.assertEqual(client.closed, 0)
        self.assertEqual(service._game_data_source_error_streaks["map_activity"], 1)

    def test_two_sources_do_not_share_a_streak(self) -> None:
        client = _CountingClient()
        service, _ = build_player_stats_memory(game_data_client=client)

        for _ in range(2):
            service.record_game_data_source_failure("map_activity", MemoryReadError("a"))
            service.record_game_data_source_failure("runtime_state", MemoryReadError("b"))

        self.assertEqual(client.closed, 0)
        self.assertEqual(service._game_data_source_error_streaks["map_activity"], 2)
        self.assertEqual(service._game_data_source_error_streaks["runtime_state"], 2)

    def test_the_stats_client_still_ignores_a_non_memory_error(self) -> None:
        """The sibling filter is deliberately kept.

        That path carries `InvalidItemStackCountError` -- a `ValueError` raised
        by a torn item read, which is expected to happen occasionally and is
        not a reason to drop the client. The game-data path has no equivalent
        transient, which is why only it was widened.
        """
        client = _CountingClient()
        service, world = build_player_stats_memory(stats_client=client)

        for _ in range(5):
            service.record_memory_failure(ValueError("nonsense"))

        self.assertEqual(client.closed, 0)
        self.assertIsNotNone(world.stats_client)
        self.assertEqual(service._player_stats_memory_error_streak, 0)

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
