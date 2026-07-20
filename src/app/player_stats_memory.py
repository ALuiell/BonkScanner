"""Player-stats memory acquisition -- the reads themselves, and the client
lifecycle they lazily drive.

Split out of ``PlayerStatsMixin`` in step 14c. This is the layer that talks to
``infra.memory``: every ``read_*`` entry point, the ``_read_*_safe`` wrappers
that translate a memory error into a reconnect decision, and the close/record
helpers that own the error streaks. It decides *what to read and when to give
up on a client*; it does not decide what to do with the values -- that is
``app/player_stats_refresh.py``.

Still a mixin on ``MegabonkApp``: 20-odd of these methods are called
class-qualified from the suite (``gui.MegabonkApp.read_player_stats_only(app)``),
which resolves only through the MRO. Converting it into a constructed service
is the rest of step 20.

**The two streak recorders are no longer part of that.** Step 20 made both
module-level functions (below), retiring the twelve class-qualified production
call sites that named this class -- ten here and two in
``app/player_stats_refresh.py``. That was the largest single obstacle to
converting this mixin, and the one with a live precedent: the same spelling
stranded the Chaos Tome panel for two commits at step 14b, through a green
suite and a working exe.

Their player-stats siblings, ``record_player_stats_memory_success``/``_failure``
and ``PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD``, moved here from
``app/refresh_tasks.py`` in the prep commit for that conversion. One reconnect
policy over two clients now lives in one place, and -- the point of doing it
first -- the move deletes the ``player_stats_memory -> refresh_tasks`` import
edge, so ``refresh_tasks`` can later import this module to resolve the memory
service without closing an import cycle.

``ModuleNotFoundError`` below is deliberately ``infra.memory.reader``'s, not the
builtin -- it shadows it, and the ``except`` clauses here depend on that. Do not
'clean up' the import.
"""
from __future__ import annotations

from app import config
from app.snapshot_store import live_snapshot_store
from core.stats.types import DamageSourceSnapshot, TomeSnapshot, WeaponSnapshot
from infra.memory.game_data_client import GameDataClient
from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError

# The reconnect threshold and the two ``record_player_stats_memory_*`` streak
# recorders (below) moved here from ``app/refresh_tasks.py`` alongside their
# game-data siblings. They read no widget -- only memory state and the memory
# client -- so this is their home. Keeping them here also breaks the
# ``player_stats_memory -> refresh_tasks`` import edge, which the later service
# conversion needs gone: once ``refresh_tasks`` must import this module to reach
# ``_get_player_stats_client`` through a resolver, the old edge would have closed
# a module-level import cycle.
PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD = 3


def record_player_stats_game_data_memory_success(owner) -> None:
    """Reset the game-data client's read-failure streak.

    A module-level function taking the owner, not a method. Until step 20 this
    was ``PlayerStatsMemoryMixin._record_player_stats_game_data_memory_success``
    and every one of its ten call sites -- plus two in
    ``app/player_stats_refresh.py`` -- named the class explicitly, because a
    plain ``self.`` call would have been a hidden cross-mixin read.

    That spelling is the exact failure mode step 14b shipped: a class-qualified
    call site resolves through ``MegabonkApp``'s MRO, does **not** follow its
    target when the method moves onto a component, and is invisible to the MRO
    resolution check. The Chaos Tome panel was broken for two commits through a
    green suite and a reported-working exe.

    A free function has no class to be orphaned from, so this **retires** the
    failure mode rather than relocating it -- the same move step 19 made for
    ``_chaos_stats_in_game_order``. It is also the shape the sibling pair in
    ``app/refresh_tasks.py`` already had; the two are one policy over two
    clients, and until now only one of them looked it.
    """
    owner._player_stats_game_data_memory_error_streak = 0


def record_player_stats_game_data_memory_failure(owner, error: Exception) -> None:
    """Count a game-data read failure, reconnecting the client at the threshold.

    Only the three memory error types count. Anything else returns silently and
    is deliberately not a reconnect reason -- see the paired
    ``except Exception`` branches in the ``_read_*_safe`` wrappers, which close
    the client outright instead. Two different policies, and the discrimination
    between them is this one ``isinstance`` check.
    """
    if not isinstance(error, (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError)):
        return
    streak = int(getattr(owner, "_player_stats_game_data_memory_error_streak", 0)) + 1
    owner._player_stats_game_data_memory_error_streak = streak
    if streak < PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD:
        return
    try:
        owner.close_player_stats_game_data_client()
    finally:
        owner._player_stats_game_data_memory_error_streak = 0


def record_player_stats_memory_success(owner) -> None:
    """Reset the player-stats client's read-failure streak.

    The sibling of ``record_player_stats_game_data_memory_success`` above --
    one reconnect policy over the two memory clients. It lived in
    ``app/refresh_tasks.py`` until this commit; moving it here (with its failure
    partner and the threshold) is what lets the coming service conversion have
    ``refresh_tasks`` import ``player_stats_memory`` without closing an import
    cycle. ``refresh_tasks`` and ``app/player_stats_refresh.py`` still call it,
    now via that import.
    """
    owner._player_stats_memory_error_streak = 0


def record_player_stats_memory_failure(owner, error: Exception) -> None:
    """Count a player-stats read failure, reconnecting the client at the threshold.

    Same discrimination as the game-data sibling: only the three memory error
    types count. Anything else returns silently and is left to the paired
    ``except Exception`` branches in the ``_read_*_safe`` wrappers, which close
    the client outright instead.
    """
    if not isinstance(error, (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError)):
        return
    streak = int(getattr(owner, "_player_stats_memory_error_streak", 0)) + 1
    owner._player_stats_memory_error_streak = streak
    if streak < PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD:
        return
    try:
        owner.close_player_stats_client()
    finally:
        owner._player_stats_memory_error_streak = 0


class PlayerStatsMemoryMixin:
    # Owned by AppCoordinator (step 12b). These properties delegate to it, with a
    # __dict__ fallback so app doubles built with object.__new__ (no coordinator)
    # keep working: a test that sets app.player_stats_client = <fake> round-trips
    # through _player_stats_client with zero test changes.
    @property
    def player_stats_client(self):
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            return coordinator.player_stats_client
        return self.__dict__.get("_player_stats_client")

    @player_stats_client.setter
    def player_stats_client(self, value) -> None:
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            coordinator.player_stats_client = value
        else:
            self.__dict__["_player_stats_client"] = value

    @property
    def player_stats_game_data_client(self):
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            return coordinator.player_stats_game_data_client
        return self.__dict__.get("_player_stats_game_data_client")

    @player_stats_game_data_client.setter
    def player_stats_game_data_client(self, value) -> None:
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            coordinator.player_stats_game_data_client = value
        else:
            self.__dict__["_player_stats_game_data_client"] = value

    def _get_player_stats_client(self) -> PlayerStatsClient:
        if self.player_stats_client is None:
            self.player_stats_client = PlayerStatsClient(config.PROCESS_NAME)
        return self.player_stats_client

    def read_player_stats_only(self):
        client = self._get_player_stats_client()
        owner_stats = client.resolve_owner_stats()
        return client.get_player_stats(owner_stats), owner_stats

    def read_passive_items_only(self, owner_stats: int | None = None):
        client = self._get_player_stats_client()
        return client.get_passive_items(owner_stats)

    def read_player_stats_recording_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        return self.player_stats_game_data_client.get_map_generation_state()

    def read_player_stats_runtime_game_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        return self.player_stats_game_data_client.get_runtime_game_state()

    def read_player_stats_runtime_activity_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        reader = getattr(self.player_stats_game_data_client, "get_runtime_activity_state", None)
        if callable(reader):
            return reader()
        return self.player_stats_game_data_client.get_runtime_game_state()

    def read_player_stats_recording_seed(self) -> int | None:
        return self.read_player_stats_recording_state().map_seed

    def _read_live_player_stats_data(self):
        stats, owner_stats = self.read_player_stats_only()
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
            client = self._get_player_stats_client()
            run_timer_seconds = client.get_run_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            run_timer_seconds = None
        except Exception:
            run_timer_seconds = None

        try:
            client = self._get_player_stats_client()
            stage_timer_seconds, stage_index, stage_duration_seconds = (
                client.get_stage_timer_context()
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
            recording_state = self.read_player_stats_recording_state()
            record_player_stats_game_data_memory_success(self)
            map_seed = recording_state.map_seed
            stage_ptr = recording_state.current_stage_ptr
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            record_player_stats_game_data_memory_failure(self, exc)
            map_seed = None
            stage_ptr = 0
        except Exception:
            self.close_player_stats_game_data_client()
            map_seed = None
            stage_ptr = 0

        # 3. Detect match start
        snapshot_store = live_snapshot_store(self)
        is_new_match = snapshot_store.is_new_match(map_seed=map_seed, run_timer_seconds=run_timer_seconds)

        if is_new_match:
            self.player_stats_disabled_items_refresh_pending = True
            snapshot_store.reset_for_new_match()

        # 4. Read passive items
        try:
            items = self.read_passive_items_only(owner_stats)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            items_available = False
        except Exception:
            items_available = False

        # 5. Read optional live stats if relevant tabs/features are active
        if (
            self.player_stats_vod_recorder.is_recording
            or self._is_live_stats_tab_active()
            or self.overlay_should_refresh_live_stats()
            or self._is_twitch_bot_active()
        ):
            try:
                client = self._get_player_stats_client()
                weapons = client.get_live_weapons(owner_stats)
                weapons_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                weapons = ()
                weapons_available = False
            except Exception:
                weapons = ()
                weapons_available = False

            try:
                client = self._get_player_stats_client()
                tomes = client.get_live_tomes(owner_stats)
                tomes_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                tomes = ()
                tomes_available = False
            except Exception:
                tomes = ()
                tomes_available = False

            try:
                client = self._get_player_stats_client()
                banishes = client.get_live_banishes()
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
                    getattr(self, "player_stats_disabled_items_refresh_pending", False)
                    or getattr(self, "player_stats_disabled_items_cache", None) is None
                )
                if should_read_disabled:
                    client = self._get_player_stats_client()
                    result = client.get_disabled_items()
                    if result.available:
                        self.player_stats_disabled_items_cache = result.items
                        self.player_stats_disabled_items_refresh_pending = False
                    cache = getattr(self, "player_stats_disabled_items_cache", None)
                    if cache is not None:
                        disabled_items = cache
                        disabled_items_available = True
                else:
                    disabled_items = getattr(self, "player_stats_disabled_items_cache", ())
                    disabled_items_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                disabled_items = ()
                disabled_items_available = False
            except Exception:
                disabled_items = ()
                disabled_items_available = False

            try:
                client = self._get_player_stats_client()
                damage_sources = client.get_live_damage_sources()
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
            mob_kills = client.get_killed_mobs()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            mob_kills = None
        except Exception:
            mob_kills = None

        try:
            client = self._get_player_stats_client()
            player_level = client.get_player_level(owner_stats)
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
            record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_state_safe(self):
        try:
            result = self.read_player_stats_recording_state()
            record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_runtime_game_state_safe(self):
        try:
            result = self.read_player_stats_runtime_game_state()
            record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_runtime_activity_state_safe(self):
        try:
            result = self.read_player_stats_runtime_activity_state()
            record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_run_timer_safe(self) -> float | None:
        try:
            result = self._get_player_stats_client().get_run_timer()
            record_player_stats_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            record_player_stats_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_client()
            return None

    def close_player_stats_client(self):
        # The instance is owned by the coordinator now (step 12b); reach it through
        # the property rather than __dict__, which no longer holds it.
        player_stats_client = self.player_stats_client
        if player_stats_client:
            try:
                player_stats_client.close()
            except Exception:
                pass
            self.player_stats_client = None
        live_snapshot_store(self).reset_match_metadata()
        self._player_stats_memory_error_streak = 0

    def close_player_stats_game_data_client(self):
        game_data_client = self.player_stats_game_data_client
        if game_data_client:
            try:
                game_data_client.close()
            except Exception:
                pass
            self.player_stats_game_data_client = None
        self._player_stats_game_data_memory_error_streak = 0

