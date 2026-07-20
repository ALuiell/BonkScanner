"""Which recorded snapshot the Live Stats timeline is currently showing.

One predicate, in its own module, because **two packages need it and they
already import in the other direction**. ``app/player_stats_refresh.py``
imports ``app/refresh_tasks.py`` for the memory-streak recorders, so putting
this in either of them and importing it from the other creates a real import
cycle -- the failure step 19 shipped once and that neither the suite nor
``test_import_direction.py`` can see, because both analyse ASTs rather than
importing.

The three names it reads -- ``player_stats_snapshot_pinned``,
``player_stats_selected_snapshot_index`` and ``player_stats_vod_snapshots`` --
are the app-owned snapshot buffer that step 20 deliberately did **not** move
into ``VodCapture``: their readers are the Live Stats tab and ``gui_layout``,
and the tab writes two of them back through its selection callback. So a module
named after that state is where a question about that state belongs.
"""
from __future__ import annotations


def player_stats_snapshot_is_pinned(owner) -> bool:
    """Has the user scrubbed the Live Stats timeline to a specific snapshot?

    Before this predicate, every live refresh tick ran
    ``player_stats_selected_snapshot_index = None`` and repainted live values,
    unconditionally. Dragging the slider mid-recording therefore showed the
    chosen snapshot for exactly one tick before the Run Summary and stage
    summary cards reverted to the live run -- reported from a live drive on
    2026-07-19, and present long before the step-18 pilot that made the path
    easy to exercise.

    **It was applied to one of the three writers, and the other two kept
    reverting the stage summary.** ``d7d1350`` guarded the slow refresh tick in
    ``player_stats_refresh.py``; ``9c59abd`` had just moved two *fast*-task
    stage-summary writes out of the widget and into ``PlayerStatsView``, and
    those went unguarded. At the fast cadence they repainted live rows over a
    scrubbed snapshot roughly once a second, which is what "the stage summary
    flickers" was -- reported from a live drive on 2026-07-20. Every other panel
    looked correct because the fast tasks write only these two.

    A module-level function rather than a method: this is a decision the app
    layer makes about its own state, and ``MegabonkApp``'s MRO does not need
    another name in it.

    The range check is what stops a stale pin from freezing the view. If the
    snapshot list is emptied (recording stops, a new run starts) the pin cannot
    be honoured even if the flag were missed, so the display falls back to live
    rather than sticking.
    """
    if not getattr(owner, "player_stats_snapshot_pinned", False):
        return False
    index = getattr(owner, "player_stats_selected_snapshot_index", None)
    if index is None:
        return False
    snapshots = getattr(owner, "player_stats_vod_snapshots", None) or ()
    return 0 <= index < len(snapshots)
