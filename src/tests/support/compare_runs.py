"""Builder for the Compare Runs tab.

Same contract as `tests/support/player_stats.py`: call the component's **real**
constructor with explicit fakes, rather than borrowing `MegabonkApp`'s MRO
through `object.__new__`. Adding a constructor argument breaks every call site
here loudly; `object.__new__` absorbs it silently and surfaces it as an
`AttributeError` at the first read.

Added by step 21d, the step that converted the tab -- the migration order the
plan in `test_componentization_inventory.py` states.

`build()` is **not** called: it needs real offscreen Qt. Tests that need widgets
assign the private ones they assert on, and the *built* tab is driven by
`tools/step21_vod_trace.py` across seventeen scenarios.
"""

from __future__ import annotations

from app.vod_library import VodLibrary
from ui.tabs.compare_runs.tab import CompareRunsTab


def build_compare_runs_tab(**overrides) -> CompareRunsTab:
    """A real `CompareRunsTab` with its three collaborators faked.

    `vod_library` defaults to a real `VodLibrary` over an empty index, not a
    stub: it is the object step 21 exists to introduce, and a test that stubs it
    proves nothing about the wiring.
    """
    defaults = {
        "tabview": None,
        "vod_library": VodLibrary(load_cached=tuple, refresh_index=tuple),
        "is_active": lambda: True,
        "schedule": None,
        # Pass a throttle over a fake clock and scheduler to assert on the
        # slider coalescing. Do not rely on the default: it defers to a
        # `QTimer` whenever a `QApplication` exists, and whether one exists in
        # a suite run depends on which test files ran first -- so a queued
        # frame may simply never arrive.
        "diff_throttle": None,
    }
    unknown = set(overrides) - set(defaults)
    assert not unknown, f"not CompareRunsTab constructor arguments: {sorted(unknown)}"
    defaults.update(overrides)
    return CompareRunsTab(**defaults)
