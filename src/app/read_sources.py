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

# Namespaced so these can never collide with the collaborator-cache keys
# `refresh_tasks.py` already uses under `context.get_or_create` ("player_stats_
# client", "owner_stats") -- see step_28_plan.md section 12.7.
PLAYER_STATS_CLIENT = "collaborator.player_stats_client"
OWNER_STATS = "memory.player_stats.owner_stats"
RUN_TIMER = "memory.player_stats.run_timer"
MOB_KILLS = "memory.player_stats.mob_kills"

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
