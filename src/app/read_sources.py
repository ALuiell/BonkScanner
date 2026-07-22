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
# come to ~2.7 ms and the warm path's 12 to ~0.24 ms, both far inside the
# bound -- which is the intended outcome, because a cold dictionary walk still
# produces a *coherent* pair, just a slower one. Section 12.4 asks this bound
# to catch a torn pair, not a slow one; `_find_run_stat_value_address`'s cost
# is explicitly out of scope (section 11) unless stop condition 5 fires.
#
# Re-run `tools/step28_span_measure.py --read-cost-us <measured>` from a live
# session to confirm the cold path stays inside this bound on real hardware.
KPS_GROUP_SPAN_LIMIT_SECONDS = 0.100

# Marks an exception that already went through `read_memory_source`'s
# `on_failure`, so a task's own outer catch-all does not record the same
# physical failure a second time. See `source_health_recorded` below.
_HEALTH_RECORDED_ATTR = "_step28_read_source_health_recorded"


def read_memory_source(
    context: RefreshTickContext,
    key: str,
    factory: Callable[[], Any],
    *,
    on_success: Callable[[], None],
    on_failure: Callable[[Exception], None],
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
            if not getattr(exc, _HEALTH_RECORDED_ATTR, False):
                on_failure(exc)
                try:
                    setattr(exc, _HEALTH_RECORDED_ATTR, True)
                except Exception:
                    pass
            raise
        on_success()
        return value

    return context.get_or_create_with_metadata(key, wrapped)


def source_health_recorded(exc: Exception) -> bool:
    """True if ``read_memory_source`` already recorded health for ``exc``.

    A task's own outer ``except`` must check this before calling its own
    ``record_memory_failure`` -- otherwise one physical read failure would
    advance the reconnect streak twice: once from ``on_failure`` here, once
    from the task's pre-existing catch-all. See step_28_plan.md section 12.5
    and the 28b task description.
    """
    return bool(getattr(exc, _HEALTH_RECORDED_ATTR, False))
