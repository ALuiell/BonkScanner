"""Builder for the player-stats memory service.

The same contract as `tests/support/vod_capture.py` and
`tests/support/run_lifecycle.py`: call `PlayerStatsMemory`'s **real**
constructor with explicit fakes, rather than borrowing `MegabonkApp`'s MRO
through `object.__new__`. Adding a dependency to `PlayerStatsMemory` breaks
every call site here loudly, where `object.__new__` absorbs it silently and
surfaces it as an `AttributeError` at the first read, in whichever test happens
to reach it first.

Every argument is a callable because every dependency of `PlayerStatsMemory`
is: a mixin method read `self` late, a constructor argument reads it once, and
step 20 shipped that difference as a bug twice in one commit.

`world` holds the mutable state the service reaches through its read/write
callables -- the two clients and the disabled-items cache -- so a test can seed
it, let the service mutate it, and assert the result: `world.stats_client`,
`world.game_data_client`, `world.disabled_items_cache`,
`world.disabled_items_refresh_pending`, `world.snapshot_store`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from app.player_stats_memory import PlayerStatsMemory


def build_player_stats_memory(
    *,
    stats_client: Any = None,
    game_data_client: Any = None,
    snapshot_store: Any = None,
    recording_active: bool | Callable[[], bool] = False,
    live_stats_tab_active: bool | Callable[[], bool] = False,
    twitch_bot_active: bool | Callable[[], bool] = False,
    overlay_refresh_wanted: bool | Callable[[], bool] = False,
    disabled_items_cache: Any = None,
    disabled_items_refresh_pending: bool = False,
    world: Any = None,
) -> tuple[PlayerStatsMemory, Any]:
    """A real `PlayerStatsMemory` with its thirteen collaborators faked."""
    if world is None:
        world = SimpleNamespace()
    world.stats_client = stats_client
    world.game_data_client = game_data_client
    world.disabled_items_cache = disabled_items_cache
    world.disabled_items_refresh_pending = disabled_items_refresh_pending

    if snapshot_store is None:
        from app.snapshot_store import LiveSnapshotStore

        snapshot_store = LiveSnapshotStore()
    world.snapshot_store = snapshot_store

    def _predicate(value: bool | Callable[[], bool]) -> Callable[[], bool]:
        return value if callable(value) else (lambda: value)

    service = PlayerStatsMemory(
        read_stats_client=lambda: world.stats_client,
        write_stats_client=lambda value: setattr(world, "stats_client", value),
        read_game_data_client=lambda: world.game_data_client,
        write_game_data_client=lambda value: setattr(world, "game_data_client", value),
        snapshot_store=lambda: world.snapshot_store,
        recording_active=_predicate(recording_active),
        live_stats_tab_active=_predicate(live_stats_tab_active),
        twitch_bot_active=_predicate(twitch_bot_active),
        overlay_refresh_wanted=_predicate(overlay_refresh_wanted),
        read_disabled_items_cache=lambda: world.disabled_items_cache,
        write_disabled_items_cache=lambda value: setattr(world, "disabled_items_cache", value),
        read_disabled_items_refresh_pending=lambda: world.disabled_items_refresh_pending,
        write_disabled_items_refresh_pending=lambda value: setattr(
            world, "disabled_items_refresh_pending", value
        ),
    )
    return service, world
