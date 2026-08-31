"""Builder for the refresh-task service.

The same contract as `tests/support/player_stats_memory.py`,
`tests/support/vod_capture.py` and `tests/support/run_lifecycle.py`: call
`RefreshTasks`'s **real** constructor with explicit fakes, rather than borrowing
`MegabonkApp`'s MRO through `object.__new__`. Adding a dependency to
`RefreshTasks` breaks every call site here loudly, where `object.__new__`
absorbs it silently and surfaces it as an `AttributeError` at the first read, in
whichever test happens to reach it first.

Every argument is a callable because every dependency of `RefreshTasks` is: a
mixin method read `self` late, a constructor argument reads it once, and step 20
shipped that difference as a bug twice in one commit.

**The memory service is real, not a fake.** Four of the tasks drive the reconnect
streak through `record_memory_success`/`record_memory_failure`, and a stubbed
recorder would assert against a fiction -- the streak policy is exactly what
those tests are about. So this builds a genuine `PlayerStatsMemory` through
`build_player_stats_memory` and shares one `world` with it, which is why
`world.stats_client` is the handle for both layers.

`world` holds the mutable state the service and its memory reach through their
read/write callables: `world.stats_client`, `world.game_data_client`,
`world.tracker`, `world.view`, `world.snapshot_store`, `world.memory`,
`world.overlay_syncs` (appended to on every `update_overlay_state_from_tracker`)
and `world.in_game_kps_syncs` (the same, for the in-game overlay's KPS repaint).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from app.refresh_tasks import RefreshTasks
from tests.support.player_stats_memory import build_player_stats_memory


def build_refresh_tasks(
    *,
    stats_client: Any = None,
    game_data_client: Any = None,
    snapshot_store: Any = None,
    tracker: Any = None,
    view: Any = None,
    lifecycle: Any = None,
    capture: Any = None,
    vod_recorder: Any = None,
    tab_active: bool | Callable[[], bool] = False,
    twitch_active: bool | Callable[[], bool] = False,
    pinned: bool | Callable[[], bool] = False,
    widget_refresh_active: bool | Callable[[str], bool] = False,
    refresh_required: bool | Callable[[], bool] = False,
    memory: Any = None,
    world: Any = None,
    permanent_source_recovery_job_factory: Callable[..., Any] | None = None,
) -> tuple[RefreshTasks, Any]:
    """A real `RefreshTasks` with its thirteen collaborators faked."""
    if world is None:
        world = SimpleNamespace()

    if memory is None:
        memory, world = build_player_stats_memory(
            stats_client=stats_client,
            game_data_client=game_data_client,
            snapshot_store=snapshot_store,
            world=world,
        )
    world.memory = memory

    if tracker is None:
        # Every attribute the six tasks reach for, each a no-op. A task that
        # needs to observe one overrides it on `world.tracker`.
        tracker = SimpleNamespace(
            update_powerups=lambda _snapshot: True,
            track_expected_key_procs=lambda _bought, _keys: None,
            track_kills=lambda _timer, _kills: None,
            update_fast_run_timer=lambda _timer: None,
            update_chaos_tome=lambda **_kwargs: None,
            update_charge_shrines=lambda _reading, **_kwargs: None,
            update_fast_stage_timer=lambda **_kwargs: None,
            update_items=lambda _items: True,
            current_ui_kps=lambda: None,
            current_minute_avg_kps=lambda: None,
            current_five_minute_avg_kps=lambda: None,
            chaos_tome_snapshot=lambda: None,
            character_passive_snapshot=lambda: None,
            charge_shrine_snapshot=lambda: None,
            feature_status_snapshot=lambda: {},
            stage_summary_rows=lambda: [],
            mark_feature_available=lambda _feature: None,
            mark_feature_failed=lambda _feature, _error: None,
        )
    world.tracker = tracker

    if view is None:
        view = SimpleNamespace(
            refresh_powerups_card=lambda: None,
            set_mob_kills_text=lambda _text: None,
            set_in_game_time_text=lambda _text: None,
            set_kps_averages_text=lambda _text: None,
            set_chaos_tome_card=lambda _chaos_tome: None,
            set_charge_shrine_card=lambda _shrines: None,
            set_stage_summary_rows=lambda _rows: None,
            set_items=lambda _items: None,
        )
    world.view = view

    if lifecycle is None:
        lifecycle = SimpleNamespace(
            completed_run=False,
            is_active_run=lambda: False,
            refresh=lambda _context=None: None,
        )
    world.lifecycle = lifecycle

    if capture is None:
        capture = SimpleNamespace(sync_run_state=lambda _context=None: "running")
    world.capture = capture

    world.vod_recorder = vod_recorder
    world.overlay_syncs: list = []
    world.in_game_kps_syncs: list = []
    world.session_tracked_item_refreshes: list = []

    def _predicate(value):
        return value if callable(value) else (lambda: value)

    widget_active = (
        widget_refresh_active
        if callable(widget_refresh_active)
        else (lambda _widget_id: widget_refresh_active)
    )

    service = RefreshTasks(
        memory=lambda: world.memory,
        lifecycle=lambda: world.lifecycle,
        view=lambda: world.view,
        capture=lambda: world.capture,
        tracker=lambda: world.tracker,
        vod_recorder=lambda: world.vod_recorder,
        tab_active=_predicate(tab_active),
        twitch_active=_predicate(twitch_active),
        pinned=_predicate(pinned),
        widget_refresh_active=widget_active,
        sync_overlay_state=lambda: world.overlay_syncs.append(1),
        sync_in_game_kps=lambda: world.in_game_kps_syncs.append(1),
        refresh_session_tracked_items=lambda: world.session_tracked_item_refreshes.append(1),
        refresh_required=_predicate(refresh_required),
        permanent_source_recovery_job_factory=permanent_source_recovery_job_factory,
    )
    return service, world
