"""The player-stats refresh orchestration -- the fast-tick body and
``refresh_live_player_stats_now``, the seam that turns one memory read into a
tracker update and a UI render.

Split out of ``PlayerStatsMixin`` in step 14c, alongside
``app/player_stats_memory.py``; the two moved together because twelve
class-qualified ``_record_player_stats_game_data_memory_*`` call sites spanned
both, and a qualified call left pointing at a class its target has left is a
silent ``AttributeError`` (see the Chaos Tome regression fixed earlier in that
step). **Step 20 retired all twelve**: both recorders are module-level
functions now, so the two modules are no longer welded together by a call
spelling.

**Step 20e moved four demand predicates out of here** and into
``app/refresh_tasks.py``: ``_player_stats_refresh_required``,
``_overlay_requires_player_snapshot``,
``_in_game_overlay_requires_player_stats_refresh`` and the ``@staticmethod``
``_in_game_overlay_widget_enabled``. The first had **zero** callers in this
module and one there; the last had three here and six there and never read
``self`` at all. This module is the top of the app import DAG -- it imports
``refresh_tasks``, ``vod_capture`` and ``run_lifecycle``, and nothing in
``app/`` imports it -- so every one of those names was a read pointing against
the import arrow, and converting either mixin with them still here would have
had to close that loop through a module-level import.

**Step 20g converted ``PlayerStatsRefreshMixin`` into the ``PlayerStatsRefresh``
service below -- the seventh and last of the app-side MRO bases, taking
``MegabonkApp`` to nine and the app-layer hidden-dependency slice to zero.**
Every dependency is an injected zero-argument callable for the reason
``player_stats_memory.py``'s header spells out: a mixin method resolves ``self``
late, on every call, and a constructor argument resolves it once. Step 20
shipped that difference as a bug twice, so nothing here is captured -- only
re-resolved. ``self.live_run_tracker`` in particular was read eleven times in
one method body and ``MegabonkApp`` replaces the tracker per run.

**The two methods stay on ``MegabonkApp`` as thin delegators, and that is the
measurement, not a concession.** ``RefreshTasksMixin``'s six method pairs had
*zero* callers outside their own module, so the service absorbed them outright.
Both of this mixin's methods are the opposite: ``refresh_live_player_stats_now``
is called on the owner from ``gui_layout.py``, ``gui_twitch.py``,
``app/refresh_tasks.py`` and ``app/vod_capture.py``, and
``update_player_stats_timer`` is ``gui_app.py``'s ``tick=``. That is genuine
``MegabonkApp`` surface -- the same finding the ``player_stats_client``
properties got in ``da7fdc6`` -- so ``gui_app.py`` keeps two one-line methods
that resolve this service and forward. The two ``app/`` call sites already
receive the command as an ``owner``-resolved lambda and did not change: an
``import app.player_stats_refresh`` from inside ``app/`` would close the loop
20e and 20f spent two commits opening.

**Known debt, carried not deepened:** ``refresh_now`` still drives seven UI
operations. They are injected view ports now rather than reads off a shared
``self``, but the ordering between them is still this method's, which is the
same Qt leak step 6 carried into ``app/refresh_tasks.py``.

The four module-level ``record_player_stats_*`` adapters in
``app/player_stats_memory.py`` lost their last production caller here: the
service holds the memory service directly and calls
``record_memory_success``/``record_memory_failure`` on it, as ``RefreshTasks``
already did. They are **deliberately not deleted** -- ``tools/step20_memory_
trace.py`` drives the streak through that spelling against both trees and
``step20_player_stats_memory_smoke.py`` asserts on it, so removing them costs
the primary verification apparatus for no production gain. That deletion
belongs with the memory trace's retirement.

``ModuleNotFoundError`` is ``infra.memory.reader``'s, not the builtin. It
shadows it, and the ``except`` clauses depend on that.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app import config
from app.read_sources import CHEST_COUNTERS, read_source
from app.player_stats_memory import player_stats_memory
from app.player_stats_view import (
    overlay_view,
    player_stats_view,
    recordings_list_view,
)
from app.run_lifecycle import run_lifecycle
from app.snapshot_selection import player_stats_snapshot_is_pinned
from app.snapshot_store import live_snapshot_store
from app.vod_capture import vod_capture
from app.refresh_tasks import ensure_refresh_coordinator
from core.game_state import MapStat, RuntimeGameMode
from infra.memory.game_data_client import GameDataClient
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from core.tracker.live_run import LiveRunSnapshot, PowerupMapContext
from projections.vod import build_vod_capture_kwargs
from projections import formatting

# `CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS` moved to `app/run_lifecycle.py`,
# with the probe that applies it. It is deliberately **not** re-exported
# here: nothing imported it from this module, and a re-export with no
# consumer is the kind of compatibility surface step 20 has been deleting.
# `app/refresh_tasks.py` names it in a comment only.


class PlayerStatsRefresh:
    """The refresh tick and the live-stats repaint, constructible without Qt or
    ``MegabonkApp``.

    Seventeen collaborators, all callables. ``_memory_service``/
    ``_lifecycle_service``/``_capture_service``/``_store`` return the sibling
    services; ``_live_stats_view``/``_overlay``/``_recordings_list`` are the
    three view ports step 19 split apart; the rest are the owner's tracker,
    recorder, snapshot buffer, predicates and the two coordinator commands.

    **The private names are checked against the other three services'.**
    ``PlayerStatsMemory``, ``VodCapture`` and ``RefreshTasks`` each spell a
    live-stats-tab predicate and a view handle, and when the memory conversion
    reused ``VodCapture``'s ``_is_live_stats_tab_active`` the cluster scanner
    reported two services' private callables as one piece of unowned state.
    ``_tab_is_active``/``_live_tracker``/``_live_stats_view`` and friends are
    distinct from every name already taken.

    This service owns **no** state. Every field the old mixin touched has a
    named owner elsewhere: the snapshot buffer and the selected index are
    app-owned (``gui_layout`` and the two Player Stats tabs read them), the two
    clients are the ``AppCoordinator``'s, and the reconnect streaks are
    ``PlayerStatsMemory``'s. There was nothing left to pull in, which is why
    this is the one conversion that adds no fields.
    """

    def __init__(
        self,
        *,
        shutdown_requested: Callable[[], bool],
        lifecycle_service: Callable[[], Any],
        coordinator_tick: Callable[[], None],
        memory_service: Callable[[], Any],
        store: Callable[[], Any],
        live_stats_view: Callable[[], Any],
        overlay: Callable[[], Any],
        recordings_list: Callable[[], Any],
        capture_service: Callable[[], Any],
        live_tracker: Callable[[], Any],
        recorder_handle: Callable[[], Any],
        tab_is_active: Callable[[], bool],
        snapshot_is_pinned: Callable[[], bool],
        snapshot_buffer: Callable[[], Any],
        select_snapshot: Callable[[Any], None],
        game_data_client: Callable[[], Any],
        set_game_data_client: Callable[[Any], None],
    ) -> None:
        self._shutdown_requested = shutdown_requested
        self._lifecycle_service = lifecycle_service
        self._coordinator_tick = coordinator_tick
        self._memory_service = memory_service
        self._store = store
        self._live_stats_view = live_stats_view
        self._overlay = overlay
        self._recordings_list = recordings_list
        self._capture_service = capture_service
        self._live_tracker = live_tracker
        self._recorder_handle = recorder_handle
        self._tab_is_active = tab_is_active
        self._snapshot_is_pinned = snapshot_is_pinned
        self._snapshot_buffer = snapshot_buffer
        self._select_snapshot = select_snapshot
        self._game_data_client = game_data_client
        self._set_game_data_client = set_game_data_client

    def tick(self) -> None:
        """The per-tick body of the fast refresh loop.

        The loop itself -- the interval, the is-active gate, and the ``after``
        thread hop that reschedules it -- is owned by
        ``AppCoordinator.start_refresh_loop`` (step 12a). This method is only the
        work done on each tick. Every cadence still lives in a registered task's
        ``interval_ms``, not here: this only ticks. Recording lifecycle work that
        used to sit in a second 10 s timer is the ``recording_lifecycle`` task.

        ``MegabonkApp.update_player_stats_timer`` is the one-line delegator
        ``gui_app.py`` passes to ``start_refresh_loop`` as ``tick=``.
        """
        if self._shutdown_requested():
            return
        self._lifecycle_service().refresh()
        self._coordinator_tick()

    def refresh_now(
        self,
        *,
        status_text: str = "Live player stats",
        waiting_status_text: str = "Waiting for game/player stats...",
        unavailable_status_prefix: str = "Player stats unavailable",
        context=None,
    ) -> bool:
        """``context`` is the current ``RefreshTickContext`` when this runs from
        the ``full_player_snapshot`` task, and ``None`` for every manual and
        off-tick caller (``gui_layout``/``gui_twitch`` reach this through
        ``MegabonkApp.refresh_live_player_stats_now``).

        Threaded through so the run timer this path reads resolves through the
        pass rather than taking a third physical read of the same four bytes
        (step_28_plan.md section 12.8, 28c commit 2). ``None`` preserves the
        off-tick behaviour exactly; no second pass is invented for it, which
        stop condition 4 forbids.
        """
        try:
            (
                stats,
                items,
                items_available,
                weapons,
                weapons_available,
                tomes,
                tomes_available,
                banishes,
                banishes_available,
                damage_sources,
                damage_sources_available,
                run_timer_seconds,
                stage_timer_seconds,
                stage_duration_seconds,
                mob_kills,
                player_level,
                map_seed,
                stage_ptr,
                stage_index,
                disabled_items,
                disabled_items_available,
            ) = self._memory_service()._read_live_player_stats_data(context)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self._memory_service().record_memory_failure(exc)
            try:
                self._overlay().mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False
        except Exception as exc:
            self._memory_service().record_memory_failure(exc)
            try:
                self._overlay().mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False

        self._memory_service().record_memory_success()

        chests_per_minute = formatting.calculate_player_chests_per_minute(stats)
        items_text = None if items_available else "Items unavailable"
        snapshot_store = self._store()

        merged_items = snapshot_store.merge_items(items, items_available)
        effective_items = merged_items.effective
        items_available = merged_items.available

        merged_weapons = snapshot_store.merge_weapons(weapons, weapons_available)
        effective_weapons = merged_weapons.effective
        weapons_available = merged_weapons.available
        effective_weapons_available = merged_weapons.effective_available

        merged_tomes = snapshot_store.merge_tomes(tomes, tomes_available)
        effective_tomes = merged_tomes.effective
        tomes_available = merged_tomes.available
        effective_tomes_available = merged_tomes.effective_available

        merged_damage_sources = snapshot_store.merge_damage_sources(damage_sources, damage_sources_available)
        effective_damage_sources = merged_damage_sources.effective
        damage_sources_available = merged_damage_sources.available
        effective_damage_sources_available = merged_damage_sources.effective_available

        merged_banishes = snapshot_store.merge_banishes(
            banishes,
            banishes_available,
            merge_fn=formatting.merge_banish_appearance_order,
        )
        banishes = merged_banishes.banishes
        banishes_available = merged_banishes.available

        is_live_tab_active = self._tab_is_active()
        map_stats = {}
        map_chests_total = None
        map_pots_total = None
        map_activity_max = {}
        try:
            if self._game_data_client() is None:
                self._set_game_data_client(GameDataClient(config.PROCESS_NAME))
            map_activity_values = (
                self._game_data_client().get_map_activity_values() or {}
            )
            self._memory_service().record_game_data_success()
            map_activity_max = {
                label: int(value.max)
                for label, value in map_activity_values.items()
            }
            map_stats = {
                stat: value
                for label, value in map_activity_values.items()
                if (stat := GameDataClient.LABEL_TO_STAT.get(label)) is not None
            }
            chest_stat = map_stats.get(MapStat.CHESTS)
            if chest_stat is not None:
                map_chests_total = chest_stat.max
            pots_stat = map_stats.get(MapStat.POTS)
            if pots_stat is not None:
                map_pots_total = pots_stat.max
        except Exception as exc:
            self._memory_service().record_game_data_failure(exc)
            map_stats = {}
            map_activity_max = {}
        if map_activity_max and hasattr(
            self._live_tracker(),
            "update_powerup_map_context",
        ):
            self._live_tracker().update_powerup_map_context(
                PowerupMapContext.from_activity_max(
                    map_activity_max,
                    captured_at=time.monotonic(),
                )
            )
        live_snapshot = LiveRunSnapshot(
            captured_at=time.monotonic(),
            stats=stats,
            items=effective_items,
            items_available=items_available,
            weapons=effective_weapons,
            weapons_available=weapons_available,
            tomes=effective_tomes,
            tomes_available=tomes_available,
            banishes=banishes,
            disabled_items=disabled_items if disabled_items_available else (),
            disabled_items_available=disabled_items_available,
            damage_sources=effective_damage_sources,
            damage_sources_available=damage_sources_available,
            chests_per_minute=chests_per_minute,
            game_time_seconds=run_timer_seconds,
            stage_timer_seconds=stage_timer_seconds,
            stage_time_seconds=stage_timer_seconds,
            stage_duration_seconds=stage_duration_seconds,
            mob_kills=mob_kills,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
            stage_index=stage_index,
            chests_total=map_chests_total,
            pots_total=map_pots_total,
        )
        self._live_tracker().update(live_snapshot)

        # Update chests and keys without replacing valid data after a transient read failure.
        previous_chests = (0, 46, 0, 0, {}, {})
        get_chests_and_keys = getattr(self._live_tracker(), "get_chests_and_keys", None)
        if callable(get_chests_and_keys):
            previous_chests = get_chests_and_keys()
        chests_opened, chests_total, keys_count = previous_chests[:3]
        should_update_chests_and_keys = False

        if items_available:
            keys_count = 0
            for item_str in effective_items:
                if item_str == "Key":
                    keys_count = 1
                    break
                elif item_str.startswith("Key x"):
                    try:
                        keys_count = int(item_str.split(" x")[-1])
                    except ValueError:
                        keys_count = 0
                    break
            should_update_chests_and_keys = True

        chest_stat = map_stats.get(MapStat.CHESTS) if map_stats else None
        if chest_stat is not None:
            chests_opened = chest_stat.current
            chests_total = chest_stat.max
            should_update_chests_and_keys = True
        if should_update_chests_and_keys:
            self._live_tracker().update_chests_and_keys(chests_opened, chests_total, keys_count)

        try:
            client = self._memory_service()._get_player_stats_client()
            chests_bought, chests_purchased = read_source(
                context, CHEST_COUNTERS, client.get_chest_counters
            )
            self._live_tracker().update_chest_counters(
                chests_bought,
                chests_purchased,
            )
        except Exception:
            pass

        view = self._live_stats_view()
        overlay = self._overlay()
        if hasattr(overlay, "refresh_session_tracked_item_stats_ui"):
            overlay.refresh_session_tracked_item_stats_ui()
        chaos_snapshot_reader = getattr(self._live_tracker(), "chaos_tome_snapshot", None)
        chaos_tome_snapshot = chaos_snapshot_reader() if callable(chaos_snapshot_reader) else None
        overlay.update_overlay_state_from_tracker()
        live_stage_summary_rows = self._live_tracker().stage_summary_rows()
        runtime_state = self._lifecycle_service().state_for_refresh()
        if runtime_state.mode is RuntimeGameMode.IN_GAME:
            self._capture_service().maybe_auto_start(
                stats=stats,
                run_timer_seconds=run_timer_seconds,
                player_level=player_level,
                map_seed=map_seed,
                stage_ptr=stage_ptr,
                stage_index=runtime_state.current_stage_index,
            )
        else:
            self._capture_service().note_run_not_in_game()

        can_capture_recording = (
            self._recorder_handle().is_recording
            and runtime_state.mode is RuntimeGameMode.IN_GAME
        )
        if can_capture_recording and self._recorder_handle().should_capture():
            capture_kwargs = build_vod_capture_kwargs(
                self._live_tracker().runtime_snapshot(),
                chaos_tome=chaos_tome_snapshot,
            )
            snapshot = self._recorder_handle().capture(**capture_kwargs)
            pinned = self._snapshot_is_pinned()
            self._snapshot_buffer().append(snapshot)
            if not pinned:
                self._select_snapshot(len(self._snapshot_buffer()) - 1)
            view.refresh_player_stats_timeline_ui()
            self._recordings_list()._refresh_vods_list_if_visible()
            if is_live_tab_active and not pinned:
                view.display_player_stats_snapshot(snapshot, items_text=items_text)
            return True

        if is_live_tab_active:
            current_ui_kps_reader = getattr(self._live_tracker(), "current_ui_kps", None)
            current_minute_kps_reader = getattr(self._live_tracker(), "current_minute_avg_kps", None)
            current_five_minute_kps_reader = getattr(self._live_tracker(), "current_five_minute_avg_kps", None)
            if self._recorder_handle().is_recording:
                if runtime_state is not None and runtime_state.mode is RuntimeGameMode.PAUSED_IN_GAME:
                    status_text_val = "Live player stats (recording paused)"
                else:
                    status_text_val = "Live player stats (recording)"
            elif self._capture_service().is_recording_armed():
                status_text_val = "Live player stats (recording armed)"
            else:
                status_text_val = status_text
            if self._snapshot_is_pinned():
                # The user scrubbed the timeline to a specific snapshot. Leave
                # their reading on screen instead of repainting live values over
                # it one tick later. Unpinning is `_select_snapshot` returning to
                # the newest snapshot, or the recording stopping.
                return True
            self._select_snapshot(None)
            view.display_player_stats(
                stats,
                effective_items,
                weapons=effective_weapons,
                tomes=effective_tomes,
                chaos_tome=chaos_tome_snapshot,
                banishes=banishes,
                damage_sources=effective_damage_sources,
                weapons_available=effective_weapons_available,
                tomes_available=effective_tomes_available,
                damage_sources_available=effective_damage_sources_available,
                status_text=status_text_val,
                chests_per_minute=chests_per_minute,
                items_text=items_text,
                game_time_seconds=run_timer_seconds,
                mob_kills=mob_kills,
                kps=current_ui_kps_reader() if callable(current_ui_kps_reader) else None,
                minute_avg_kps=(
                    current_minute_kps_reader() if callable(current_minute_kps_reader) else None
                ),
                five_minute_avg_kps=(
                    current_five_minute_kps_reader() if callable(current_five_minute_kps_reader) else None
                ),
                player_level=player_level,
                stage_summary_rows=live_stage_summary_rows,
            )
        return True


def player_stats_refresh(owner) -> PlayerStatsRefresh:
    """Resolve the owner's ``PlayerStatsRefresh``, building it on first use.

    The same shape as ``player_stats_memory``, ``vod_capture``,
    ``run_lifecycle`` and ``refresh_tasks``: the service's dependencies are the
    owner's sibling services, tracker, recorder and view ports, so
    ``AppCoordinator`` cannot construct it in its own ``__init__``. The
    coordinator caches it when there is one; an app double built with
    ``object.__new__`` has none and keeps it in ``__dict__``.

    ``__dict__``, not ``getattr``: ``MegabonkApp.__getattr__`` forwards unknown
    names to its ``window``, so a ``getattr`` would consult the widget before
    deciding there is no coordinator.

    Every argument is a lambda rather than a bound method or an attribute grab.
    ``self.live_run_tracker`` was resolved eleven times in one method body and
    ``MegabonkApp`` replaces it per run; capturing it here would freeze
    whichever one existed when the service was first touched. Step 20 shipped
    that difference as a bug twice.

    Note the two **bare** attribute reads: ``owner._is_shutting_down`` and
    ``owner.player_stats_game_data_client`` are not wrapped in ``getattr`` with
    a default. That is deliberate -- the old code read them off ``self`` and let
    a missing attribute raise, and the game-data read sits inside a
    ``try``/``except Exception`` whose failure branch several test doubles rely
    on reaching. A tolerant ``getattr`` here would silently move them onto the
    success path.
    """
    coordinator = owner.__dict__.get("coordinator")
    if coordinator is not None:
        existing = getattr(coordinator, "player_stats_refresh", None)
        if existing is not None:
            return existing

    existing = owner.__dict__.get("_player_stats_refresh")
    if existing is not None:
        return existing

    service = PlayerStatsRefresh(
        shutdown_requested=lambda: owner._is_shutting_down,
        lifecycle_service=lambda: run_lifecycle(owner),
        coordinator_tick=lambda: ensure_refresh_coordinator(owner).tick(),
        memory_service=lambda: player_stats_memory(owner),
        store=lambda: live_snapshot_store(owner),
        live_stats_view=lambda: player_stats_view(owner),
        overlay=lambda: overlay_view(owner),
        recordings_list=lambda: recordings_list_view(owner),
        capture_service=lambda: vod_capture(owner),
        live_tracker=lambda: owner.live_run_tracker,
        recorder_handle=lambda: owner.player_stats_vod_recorder,
        tab_is_active=lambda: owner._is_live_stats_tab_active(),
        snapshot_is_pinned=lambda: player_stats_snapshot_is_pinned(owner),
        snapshot_buffer=lambda: owner.player_stats_vod_snapshots,
        select_snapshot=lambda index: setattr(
            owner, "player_stats_selected_snapshot_index", index
        ),
        game_data_client=lambda: owner.player_stats_game_data_client,
        set_game_data_client=lambda value: setattr(
            owner, "player_stats_game_data_client", value
        ),
    )
    if coordinator is not None:
        coordinator.player_stats_refresh = service
    else:
        owner.__dict__["_player_stats_refresh"] = service
    return service
