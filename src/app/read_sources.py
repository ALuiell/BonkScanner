"""Named on-tick memory sources and the physical-read/health helper.

Step 28a. Plain namespaced string constants -- no registry object, no
``ReadRequirement``, no demand object (step_28_plan.md section 12.7: "No
runtime registry, demand object or cadence merger is introduced"). A source
names a logical fact; the pass (``RefreshTickContext``) already caches it by
key and isolates its failure from every other key, so naming it is all this
module adds.

Only the four sources 28a/28b need. The remaining on-tick reads are enrolled
in 28d, not here.
"""
from __future__ import annotations

from typing import Any, Callable

from app.refresh_coordinator import RefreshTickContext

# Namespaced per step_28_plan.md section 12.7. These are not "new keys beside"
# the collaborator-cache keys `refresh_tasks.py` uses -- they *are* those keys:
# `_fast_task_client` and `_fast_task_owner_stats` spell them from here, so
# each fact has exactly one spelling and resolves once per pass. The bare
# "player_stats_client"/"owner_stats" literals they used before 28c would have
# given `OWNER_STATS` a second, separate cache entry and a second physical
# `resolve_owner_stats()` per pass once 28d enrolled it.
PLAYER_STATS_CLIENT = "collaborator.player_stats_client"
OWNER_STATS = "memory.player_stats.owner_stats"
RUN_TIMER = "memory.player_stats.run_timer"
MOB_KILLS = "memory.player_stats.mob_kills"

# 28d: the remaining on-tick facts. One key per logical fact, not per client
# method -- an indivisible aggregate gets one aggregate key (section 12.7).
# A fact read by two call sites resolves once per pass; that is the whole
# point of naming it.
PLAYER_STATS = "memory.player_stats.player_stats"
PASSIVE_ITEMS = "memory.player_stats.passive_items"
# Luck (stat 30) alone, deliberately **not** folded into `PLAYER_STATS`. That
# key resolves a full per-stat walk, and sharing it would make every fast pass
# that wants Luck pay for one. Two keys for two facts of different cost, per
# section 12.7's "one key per logical fact": "the whole stat block" and "the
# rarity roll's only input" are not the same fact.
LUCK = "memory.player_stats.luck"
SIZE = "memory.player_stats.size"
STAGE_TIMER_CONTEXT = "memory.player_stats.stage_timer_context"
PLAYER_LEVEL = "memory.player_stats.player_level"
LIVE_WEAPONS = "memory.player_stats.live_weapons"
LIVE_TOMES = "memory.player_stats.live_tomes"
LIVE_BANISHES = "memory.player_stats.live_banishes"
LIVE_DAMAGE_SOURCES = "memory.player_stats.live_damage_sources"
DISABLED_ITEMS = "memory.player_stats.disabled_items"
POWERUP_TRACKING_SNAPSHOT = "memory.player_stats.powerup_tracking_snapshot"
EXPECTED_CHEST_INPUTS = "memory.player_stats.expected_chest_inputs"
CHAOS_TRACKING_STATE = "memory.player_stats.chaos_tracking_state"
VERIFIER_STAT_COMPONENTS = "memory.player_stats.verifier_stat_components"
CHARACTER_PASSIVE_READING = "memory.player_stats.character_passive_reading"
SHRINE_TRACKING_STATE = "memory.player_stats.shrine_tracking_state"
CHEST_COUNTERS = "memory.player_stats.chest_counters"

MAP_GENERATION_STATE = "memory.game_data.map_generation_state"
RUNTIME_GAME_STATE = "memory.game_data.runtime_game_state"
RUNTIME_ACTIVITY_STATE = "memory.game_data.runtime_activity_state"
MAP_ACTIVITY_VALUES = "memory.game_data.map_activity_values"

# The accepted coherence window for the RUN_TIMER/MOB_KILLS group, measured as
# max(finished_at) - min(started_at) over its members.
#
# Not invented from the task cadence (step_28_plan.md section 12.4 forbids
# that) and not tuned until a test passed. `tools/step28_span_measure.py`
# measures the quantity that dominates the span -- the number of
# ReadProcessMemory calls on each path -- against a scripted 40-entry RunStats
# dictionary:
#
#     warm (address cache hit):            12 reads per pass
#     cold (`_find_run_stat_value_address`
#           walks the dictionary with a
#           read_mono_string per entry):   134 reads
#     ratio:                               11.2x
#
# So a stable separation exists and stop condition 1 does not fire. What that
# harness cannot supply without a live game process is the cost of one
# ReadProcessMemory, and this file does not invent one -- so the limit is set
# from the other end of section 12.4's rule, "below a window that would make
# the pair misleading", which is derivable here:
#
# the refresh driver's fastest configured interval is 100 ms (config.py:784-793).
# A group whose two members are more than a whole fastest-pass apart was not
# read together in any meaningful sense, and a kill delta divided by that
# interval is a wrong number rather than a stale one. Below that, the pair is
# coherent: even at a pessimistic 20 us per read, the cold path's 134 reads

# The accepted coherence window for the RUN_TIMER/MOB_KILLS group, measured as
# max(finished_at) - min(started_at) over its members.
#
# Not invented from the task cadence (step_28_plan.md section 12.4 forbids
# that) and not tuned until a test passed. `tools/span_measure.py`
# measures the quantity that dominates the span -- the number of
# ReadProcessMemory calls on each path -- against a scripted 40-entry RunStats
# dictionary:
#
#     warm (address cache hit):            12 reads per pass
#     cold (`_find_run_stat_value_address`
#           walks the dictionary with a
#           read_mono_string per entry):   134 reads
#     ratio:                               11.2x
#
# So a stable separation exists and stop condition 1 does not fire. What that
# harness cannot supply without a live game process is the cost of one
# ReadProcessMemory, and this file does not invent one -- so the limit is set
# from the other end of section 12.4's rule, "below a window that would make
# the pair misleading", which is derivable here:
#
# the refresh driver's fastest configured interval is 100 ms (config.py:784-793).
# A group whose two members are more than a whole fastest-pass apart was not
# read together in any meaningful sense, and a kill delta divided by that
# interval is a wrong number rather than a stale one. Below that, the pair is
# coherent: even at a pessimistic 20 us per read, the cold path's 134 reads
# come to ~2.7 ms and the warm path's 12 to ~0.24 ms, both far inside the
# bound -- which is the intended outcome, because a cold dictionary walk still
# produces a *coherent* pair, just a slower one. Section 12.4 asks this bound
# to catch a torn pair, not a slow one; `_find_run_stat_value_address`'s cost
# is explicitly out of scope (section 11) unless stop condition 5 fires.
#
# Re-run `tools/span_measure.py --read-cost-us <measured>` from a live
# session to confirm the cold path stays inside this bound on real hardware.
KPS_GROUP_SPAN_LIMIT_SECONDS = 0.100

# Health markers are scoped to one pass. Keeping them on the exception object
# itself is incorrect because a factory is allowed to raise the same exception
# instance on a later pass; that later physical attempt must be counted again.
_HEALTH_RECORDED_IDS_ATTR = "_step28_health_recorded_error_ids"


def read_source(
    context: RefreshTickContext | None,
    key: str,
    factory: Callable[[], Any],
    *,
    on_success: Callable[[], None] | None = None,
    on_failure: Callable[[Exception], None] | None = None,
) -> Any:
    """Enrolment in one line, with the two things 28d must not change.

    ``context is None`` -- a manual or off-tick caller -- calls ``factory``
    directly, exactly as the site did before enrolment. No second pass is
    invented for it (stop condition 4).

    ``on_success``/``on_failure`` default to *nothing*. Most of the 28d sites
    record no memory health at all: they swallow a read failure into an
    ``available=False`` flag and leave the reconnect streak alone. Enrolling
    them with real health callbacks would change error policy, which section
    12.8's 28d forbids -- so the default is to preserve whatever the site
    already did, and only the sites that already recorded health pass
    callbacks.
    """
    if context is None:
        return factory()
    return read_memory_source(
        context, key, factory, on_success=on_success, on_failure=on_failure
    )


def read_memory_source(
    context: RefreshTickContext,
    key: str,
    factory: Callable[[], Any],
    *,
    on_success: Callable[[], None] | None = None,
    on_failure: Callable[[Exception], None] | None = None,
) -> Any:
    """Read ``key`` through ``context``, recording memory health exactly once
    per physical attempt (step_28_plan.md section 12.5).

    ``on_success``/``on_failure`` run only inside the callable handed to
    ``get_or_create_with_metadata`` -- i.e. only on the cache miss that
    actually calls ``factory``. A second consumer of the same key in the same
    pass gets the cached value or re-raises the cached exception without
    ``factory``, ``on_success`` or ``on_failure`` running again.

    Deliberately not a "safe" wrapper: a structural failure is not swallowed
    into ``None`` here, because that would erase the distinction between a
    value and a failed source (section 12.5). Callers translate the raised
    exception into their own existing failure policy.
    """

    def wrapped() -> Any:
        try:
            value = factory()
        except Exception as exc:
            recorded_ids = getattr(context, _HEALTH_RECORDED_IDS_ATTR, None)
            if recorded_ids is None:
                recorded_ids = set()
                setattr(context, _HEALTH_RECORDED_IDS_ATTR, recorded_ids)
            if on_failure is not None and id(exc) not in recorded_ids:
                on_failure(exc)
                recorded_ids.add(id(exc))
            raise
        if on_success is not None:
            on_success()
        return value

    return context.get_or_create_with_metadata(key, wrapped)


def source_health_recorded(context: RefreshTickContext, exc: Exception) -> bool:
    """True if ``read_memory_source`` already recorded health for ``exc``.

    A task's own outer ``except`` must check this before calling its own
    ``record_memory_failure`` -- otherwise one physical read failure would
    advance the reconnect streak twice: once from ``on_failure`` here, once
    from the task's pre-existing catch-all. See step_28_plan.md section 12.5
    and the 28b task description.
    """
    recorded_ids = getattr(context, _HEALTH_RECORDED_IDS_ATTR, ())
    return id(exc) in recorded_ids
