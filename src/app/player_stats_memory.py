"""Player-stats memory acquisition -- the reads themselves, the client lifecycle
they lazily drive, and the read-failure reconnect policy.

Split out of ``PlayerStatsMixin`` in step 14c and converted from
``PlayerStatsMemoryMixin`` into an ordinary constructed service in step 20 --
the last of the five app-side MRO bases. This is the layer that talks to
``infra.memory``: every ``read_*`` entry point, the ``_read_*_safe`` wrappers
that translate a memory error into a reconnect decision, the two close helpers,
and the error streaks they drive. It decides *what to read and when to give up
on a client*; it does not decide what to do with the values -- that is
``app/player_stats_refresh.py``.

**Every dependency is a callable, and that is not decoration.** A mixin method
read ``self`` late, on each call; a constructor argument reads it once. Step 20
was bitten by exactly this twice in one commit, so the two clients, the snapshot
store, the four demand predicates and the disabled-items cache all arrive as
callables that re-resolve per call, which is what ``self.<name>`` did. The two
``PlayerStatsClient``/``GameDataClient`` factories are *not*
injected: the service imports them and ``config`` directly, because a lazily
constructed client is this module's own decision, not a collaborator.

**What this service owns: the two reconnect streaks.** ``_player_stats_memory_
error_streak`` and ``_player_stats_game_data_memory_error_streak`` were app
state, but nothing outside the reconnect policy ever touched them -- only the
four ``record_*`` recorders and the two close helpers, all of which are this
module's. So they move in, exactly as ``VodCapture`` pulled in its nine
recording-lifecycle fields. The four module-level ``record_*`` functions survive
as **thin owner-taking adapters** (``refresh_tasks`` and
``player_stats_refresh`` call them ~14 times and pass the app), each resolving
the service and delegating; the streak now lives in one place instead of on a
shared ``self`` two other modules also wrote.

**What this service does *not* own: the two clients or the disabled-items
cache.** ``player_stats_client``/``player_stats_game_data_client`` are the
``AppCoordinator``'s (step 12b); they arrive as read/write callables that hit
the coordinator-delegating properties, which moved to ``MegabonkApp`` when this
mixin left its bases. ``player_stats_disabled_items_cache`` and its
``_refresh_pending`` flag are app state whose *other* readers and writers are
``gui_twitch`` (``open_twitch_command_settings_dialog``) and ``gui_dialogs`` --
neither in any step-20 metric, because ``--clusters`` scans only the five app
modules. Pulling the cache in here would silently desync those two, so it stays
app-owned and this service reads and writes it through injected accessors, the
same shape ``VodCapture`` used for the snapshot buffer.

``ModuleNotFoundError`` below is deliberately ``infra.memory.reader``'s, not the
builtin -- it shadows it, and the ``except`` clauses here depend on that. Do not
'clean up' the import.
"""
from __future__ import annotations

from typing import Any, Callable

from app import config
from app.read_sources import (
    DISABLED_ITEMS,
    LIVE_BANISHES,
    LIVE_DAMAGE_SOURCES,
    LIVE_TOMES,
    LIVE_WEAPONS,
    MAP_GENERATION_STATE,
    MOB_KILLS,
    OWNER_STATS,
    PASSIVE_ITEMS,
    PLAYER_LEVEL,
    PLAYER_STATS,
    RUN_TIMER,
    RUNTIME_ACTIVITY_STATE,
    RUNTIME_GAME_STATE,
    STAGE_TIMER_CONTEXT,
    read_memory_source,
    read_source,
    source_health_recorded,
)
from app.snapshot_store import live_snapshot_store
from core.stats.types import DamageSourceSnapshot, TomeSnapshot, WeaponSnapshot
from infra.memory.game_data_client import GameDataClient
from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError

PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD = 3


class PlayerStatsMemory:
    """The memory-read layer, constructible without Qt or ``MegabonkApp``.

    The two streak fields below keep their old ``_player_stats_*`` spellings
    deliberately: they moved owner (app -> service) but not meaning, and the
    differential trace and the mutation harness both anchor on the policy that
    drives them.
    """

    def __init__(
        self,
        *,
        read_stats_client: Callable[[], Any],
        write_stats_client: Callable[[Any], None],
        read_game_data_client: Callable[[], Any],
        write_game_data_client: Callable[[Any], None],
        snapshot_store: Callable[[], Any],
        recording_active: Callable[[], bool],
        live_stats_tab_active: Callable[[], bool],
        twitch_bot_active: Callable[[], bool],
        overlay_refresh_wanted: Callable[[], bool],
        read_disabled_items_cache: Callable[[], Any],
        write_disabled_items_cache: Callable[[Any], None],
        read_disabled_items_refresh_pending: Callable[[], bool],
        write_disabled_items_refresh_pending: Callable[[bool], None],
    ) -> None:
        self._read_stats_client = read_stats_client
        self._write_stats_client = write_stats_client
        self._read_game_data_client = read_game_data_client
        self._write_game_data_client = write_game_data_client
        self._snapshot_store = snapshot_store
        # Distinct private names -- not `_recorder`/`_is_live_stats_tab_active`,
        # which are `VodCapture`'s injected-attr spellings and the app's own
        # method names. Sharing them tripped `step20_metrics --clusters` into
        # reporting two services' private callables as one piece of unowned
        # state. Memory also needs only the recording *boolean*, not the
        # recorder object, so it injects a predicate.
        self._recording_active = recording_active
        self._live_stats_tab_active = live_stats_tab_active
        self._twitch_bot_active = twitch_bot_active
        self._overlay_refresh_wanted = overlay_refresh_wanted
        self._read_disabled_items_cache = read_disabled_items_cache
        self._write_disabled_items_cache = write_disabled_items_cache
        self._read_disabled_items_refresh_pending = read_disabled_items_refresh_pending
        self._write_disabled_items_refresh_pending = write_disabled_items_refresh_pending

        self._player_stats_memory_error_streak = 0
        self._player_stats_game_data_memory_error_streak = 0

    # -- the read-failure reconnect policy --------------------------------
    #
    # The single most invisible code in this layer: a counter nobody displays,
    # driving a reconnect nobody sees. A success resets the streak; a failure
    # counts **only** the three memory error types (any other exception is
    # ignored -- a silent ``return``); the client is closed and the streak reset
    # only at the threshold. These were the module-level ``record_*`` bodies;
    # the streak they mutated moved in with them.

    def record_memory_success(self) -> None:
        self._player_stats_memory_error_streak = 0

    def record_memory_failure(self, error: Exception) -> None:
        if not isinstance(error, (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError)):
            return
        self._player_stats_memory_error_streak = int(self._player_stats_memory_error_streak) + 1
        if self._player_stats_memory_error_streak < PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD:
            return
        try:
            self.close_player_stats_client()
        finally:
            self._player_stats_memory_error_streak = 0

    def record_game_data_success(self) -> None:
        self._player_stats_game_data_memory_error_streak = 0

    def record_game_data_failure(self, error: Exception) -> None:
        if not isinstance(error, (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError)):
            return
        self._player_stats_game_data_memory_error_streak = int(self._player_stats_game_data_memory_error_streak) + 1
        if self._player_stats_game_data_memory_error_streak < PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD:
            return
        try:
            self.close_player_stats_game_data_client()
        finally:
            self._player_stats_game_data_memory_error_streak = 0

    # -- client lifecycle -------------------------------------------------

    def _get_player_stats_client(self) -> PlayerStatsClient:
        if self._read_stats_client() is None:
            self._write_stats_client(PlayerStatsClient(config.PROCESS_NAME))
        return self._read_stats_client()

    def read_player_stats_only(self, context=None):
        client = self._get_player_stats_client()
        owner_stats = read_source(
            context, OWNER_STATS, client.resolve_owner_stats
        )
        return (
            read_source(
                context, PLAYER_STATS, lambda: client.get_player_stats(owner_stats)
            ),
            owner_stats,
        )

    def read_passive_items_only(self, owner_stats: int | None = None, context=None):
        client = self._get_player_stats_client()
        return read_source(
            context, PASSIVE_ITEMS, lambda: client.get_passive_items(owner_stats)
        )

    def read_player_stats_recording_state(self, context=None):
        if self._read_game_data_client() is None:
            self._write_game_data_client(GameDataClient(config.PROCESS_NAME))
        client = self._read_game_data_client()
        return read_source(
            context, MAP_GENERATION_STATE, client.get_map_generation_state
        )

    def read_player_stats_runtime_game_state(self, context=None):
        if self._read_game_data_client() is None:
            self._write_game_data_client(GameDataClient(config.PROCESS_NAME))
        client = self._read_game_data_client()
        return read_source(
            context, RUNTIME_GAME_STATE, client.get_runtime_game_state
        )

    def read_player_stats_runtime_activity_state(self, context=None):
        if self._read_game_data_client() is None:
            self._write_game_data_client(GameDataClient(config.PROCESS_NAME))
        reader = getattr(self._read_game_data_client(), "get_runtime_activity_state", None)
        if callable(reader):
            # The *activity* reader is a different fact from RUNTIME_GAME_STATE
            # -- five static-field blocks against six -- so it deliberately does
            # not share that key. Naming it does not collapse the two facts; it
            # only ensures the on-tick lifecycle probe uses the same read-pass
            # contract as every other on-tick memory fact.
            return read_source(context, RUNTIME_ACTIVITY_STATE, reader)
        # The fallback, however, IS the same fact, so it resolves the same key.
        return read_source(
            context, RUNTIME_GAME_STATE, self._read_game_data_client().get_runtime_game_state
        )

    def read_player_stats_recording_seed(self) -> int | None:
        return self.read_player_stats_recording_state().map_seed

    def _read_live_player_stats_data(self, context=None):
        """``context`` is the current ``RefreshTickContext`` when this runs from
        the ``full_player_snapshot`` task, and ``None`` for the manual/off-tick
        entry points (step_28_plan.md section 12.8, 28c commit 2).

        ``None`` keeps the pre-28c behaviour exactly -- a direct client call --
        rather than inventing a second pass for an off-tick caller, which
        stop condition 4 forbids.
        """
        stats, owner_stats = self.read_player_stats_only(context)
        items = ()
        items_available = True
        weapons: tuple[WeaponSnapshot, ...] = ()
        weapons_available = False
        tomes: tuple[TomeSnapshot, ...] = ()
        tomes_available = False
        banishes: tuple[str, ...] = ()
        banishes_available = False
        disabled_items = ()
        disabled_items_available = False
        damage_sources: tuple[DamageSourceSnapshot, ...] = ()
        damage_sources_available = False

        # 1. Read run timer and stage timer first to support match start detection
        run_timer_seconds = None
        stage_timer_seconds = None
        stage_index = None
        stage_duration_seconds = None
        try:
            run_timer_seconds = self._resolve_run_timer(context)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            run_timer_seconds = None
        except Exception:
            run_timer_seconds = None

        try:
            client = self._get_player_stats_client()
            stage_timer_seconds, stage_index, stage_duration_seconds = read_source(
                context, STAGE_TIMER_CONTEXT, client.get_stage_timer_context
            )
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            stage_timer_seconds = None
            stage_index = None
            stage_duration_seconds = None
        except Exception:
            stage_timer_seconds = None
            stage_index = None
            stage_duration_seconds = None

        # 2. Read map seed and stage ptr
        map_seed = None
        stage_ptr = 0
        try:
            recording_state = self.read_player_stats_recording_state(context)
            self.record_game_data_success()
            map_seed = recording_state.map_seed
            stage_ptr = recording_state.current_stage_ptr
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self.record_game_data_failure(exc)
            map_seed = None
            stage_ptr = 0
        except Exception:
            self.close_player_stats_game_data_client()
            map_seed = None
            stage_ptr = 0

        # 3. Detect match start
        snapshot_store = self._snapshot_store()
        is_new_match = snapshot_store.is_new_match(map_seed=map_seed, run_timer_seconds=run_timer_seconds)

        if is_new_match:
            self._write_disabled_items_refresh_pending(True)
            snapshot_store.reset_for_new_match()

        # 4. Read passive items
        try:
            items = self.read_passive_items_only(owner_stats, context)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            items_available = False
        except Exception:
            items_available = False

        # 5. Read optional live stats if relevant tabs/features are active
        if (
            self._recording_active()
            or self._live_stats_tab_active()
            or self._overlay_refresh_wanted()
            or self._twitch_bot_active()
        ):
            try:
                client = self._get_player_stats_client()
                weapons = read_source(context, LIVE_WEAPONS, lambda: client.get_live_weapons(owner_stats))
                weapons_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                weapons = ()
                weapons_available = False
            except Exception:
                weapons = ()
                weapons_available = False

            try:
                client = self._get_player_stats_client()
                tomes = read_source(context, LIVE_TOMES, lambda: client.get_live_tomes(owner_stats))
                tomes_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                tomes = ()
                tomes_available = False
            except Exception:
                tomes = ()
                tomes_available = False

            try:
                client = self._get_player_stats_client()
                banishes = read_source(context, LIVE_BANISHES, client.get_live_banishes)
                banishes_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                banishes = ()
                banishes_available = False
            except Exception:
                banishes = ()
                banishes_available = False

            # Refresh once per run, retrying until memory exposes a complete pool.
            try:
                should_read_disabled = (
                    self._read_disabled_items_refresh_pending()
                    or self._read_disabled_items_cache() is None
                )
                if should_read_disabled:
                    client = self._get_player_stats_client()
                    result = read_source(context, DISABLED_ITEMS, client.get_disabled_items)
                    if result.available:
                        self._write_disabled_items_cache(result.items)
                        self._write_disabled_items_refresh_pending(False)
                    cache = self._read_disabled_items_cache()
                    if cache is not None:
                        disabled_items = cache
                        disabled_items_available = True
                else:
                    disabled_items = self._read_disabled_items_cache()
                    disabled_items_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                disabled_items = ()
                disabled_items_available = False
            except Exception:
                disabled_items = ()
                disabled_items_available = False

            try:
                client = self._get_player_stats_client()
                damage_sources = read_source(context, LIVE_DAMAGE_SOURCES, client.get_live_damage_sources)
                damage_sources_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                damage_sources = ()
                damage_sources_available = False
            except Exception:
                damage_sources = ()
                damage_sources_available = False

        # 6. Read mob kills and player level
        try:
            client = self._get_player_stats_client()
            mob_kills = read_source(context, MOB_KILLS, client.get_killed_mobs)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            mob_kills = None
        except Exception:
            mob_kills = None

        try:
            client = self._get_player_stats_client()
            player_level = read_source(
                context, PLAYER_LEVEL, lambda: client.get_player_level(owner_stats)
            )
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            player_level = None
        except Exception:
            player_level = None

        # Update last seed and run timer values for the next tick
        snapshot_store.record_match_tick(map_seed=map_seed, run_timer_seconds=run_timer_seconds)

        return (
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
        )

    def _read_player_stats_recording_seed_safe(self) -> int | None:
        try:
            result = self.read_player_stats_recording_seed()
            self.record_game_data_success()
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self.record_game_data_failure(exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_state_safe(self, context=None):
        try:
            result = self.read_player_stats_recording_state(context)
            self.record_game_data_success()
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self.record_game_data_failure(exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_runtime_game_state_safe(self, context=None):
        try:
            result = self.read_player_stats_runtime_game_state(context)
            self.record_game_data_success()
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self.record_game_data_failure(exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_runtime_activity_state_safe(self, context=None):
        try:
            result = self.read_player_stats_runtime_activity_state(context)
            self.record_game_data_success()
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self.record_game_data_failure(exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _resolve_run_timer(self, context=None) -> float | None:
        """The single physical run-timer read for a pass.

        With a ``context`` this resolves RUN_TIMER through the pass, so the
        combat task, the full snapshot and the recording lifecycle share one
        physical read of ``0x2f62398+0x20`` per tick instead of taking three.
        Without one it calls the client directly, unchanged.

        Health accounting stays with the physical read either way: through the
        pass it is ``read_memory_source``'s job, and a cached hit records
        nothing (section 12.5).
        """
        return read_source(
            context,
            RUN_TIMER,
            self._get_player_stats_client().get_run_timer,
            on_success=self.record_memory_success,
            on_failure=self.record_memory_failure,
        )

    def _read_player_stats_recording_run_timer_safe(self, context=None) -> float | None:
        try:
            result = self._resolve_run_timer(context)
            if context is None:
                self.record_memory_success()
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            if context is None or not source_health_recorded(context, exc):
                self.record_memory_failure(exc)
            return None
        except Exception:
            self.close_player_stats_client()
            return None

    def close_player_stats_client(self):
        # The instance is owned by the coordinator (step 12b); reach it through
        # the injected accessor, which delegates to the coordinator-owned property.
        player_stats_client = self._read_stats_client()
        if player_stats_client:
            try:
                player_stats_client.close()
            except Exception:
                pass
            self._write_stats_client(None)
        self._snapshot_store().reset_match_metadata()
        self._player_stats_memory_error_streak = 0

    def close_player_stats_game_data_client(self):
        game_data_client = self._read_game_data_client()
        if game_data_client:
            try:
                game_data_client.close()
            except Exception:
                pass
            self._write_game_data_client(None)
        self._player_stats_game_data_memory_error_streak = 0


def player_stats_memory(owner) -> PlayerStatsMemory:
    """Resolve the owner's ``PlayerStatsMemory``, building it on first use.

    The same shape as ``vod_capture`` and ``run_lifecycle``: the service's
    dependencies are the owner's clients, snapshot store, recorder, demand
    predicates and disabled-items cache, so ``AppCoordinator`` cannot construct
    it in its own ``__init__``. The coordinator caches it when there is one; an
    app double built with ``object.__new__`` has none and keeps it in
    ``__dict__``.

    ``__dict__``, not ``getattr``: ``MegabonkApp.__getattr__`` forwards unknown
    names to its ``window``, so a ``getattr`` would consult the widget before
    deciding there is no coordinator.

    Every argument is a lambda rather than a bound method or attribute grab:
    ``self.player_stats_client`` resolved late, on every call; capturing the
    client here would freeze whichever one happened to exist when the service
    was first touched. Step 20 shipped that difference as a bug twice.
    """
    coordinator = owner.__dict__.get("coordinator")
    if coordinator is not None:
        existing = getattr(coordinator, "player_stats_memory", None)
        if existing is not None:
            return existing

    existing = owner.__dict__.get("_player_stats_memory")
    if existing is not None:
        return existing

    service = PlayerStatsMemory(
        read_stats_client=lambda: owner.player_stats_client,
        write_stats_client=lambda value: setattr(owner, "player_stats_client", value),
        read_game_data_client=lambda: owner.player_stats_game_data_client,
        write_game_data_client=lambda value: setattr(owner, "player_stats_game_data_client", value),
        snapshot_store=lambda: live_snapshot_store(owner),
        recording_active=lambda: owner.player_stats_vod_recorder.is_recording,
        live_stats_tab_active=lambda: owner._is_live_stats_tab_active(),
        twitch_bot_active=lambda: owner._is_twitch_bot_active(),
        overlay_refresh_wanted=lambda: owner.overlay_should_refresh_live_stats(),
        read_disabled_items_cache=lambda: getattr(owner, "player_stats_disabled_items_cache", None),
        write_disabled_items_cache=lambda value: setattr(
            owner, "player_stats_disabled_items_cache", value
        ),
        read_disabled_items_refresh_pending=lambda: getattr(
            owner, "player_stats_disabled_items_refresh_pending", False
        ),
        write_disabled_items_refresh_pending=lambda value: setattr(
            owner, "player_stats_disabled_items_refresh_pending", value
        ),
    )
    if coordinator is not None:
        coordinator.player_stats_memory = service
    else:
        owner.__dict__["_player_stats_memory"] = service
    return service


# The four module-level recorders survive as thin owner-taking adapters. Their
# ~14 call sites in ``refresh_tasks`` and ``player_stats_refresh`` pass the app
# and stay unchanged; each resolves the service and delegates to the streak
# policy that now lives there. The game-data pair became module-level in step
# 20's second commit (1d09c1b) to retire twelve class-qualified call sites that
# named this class -- the exact spelling that stranded the Chaos Tome panel for
# two commits at step 14b, through a green suite and a working exe.


def record_player_stats_game_data_memory_success(owner) -> None:
    player_stats_memory(owner).record_game_data_success()


def record_player_stats_game_data_memory_failure(owner, error: Exception) -> None:
    player_stats_memory(owner).record_game_data_failure(error)


def record_player_stats_memory_success(owner) -> None:
    player_stats_memory(owner).record_memory_success()


def record_player_stats_memory_failure(owner, error: Exception) -> None:
    player_stats_memory(owner).record_memory_failure(error)
