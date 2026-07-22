"""Step 26: the tab-switch router, driven as an object.

One test **moved** here from `test_gui_run_control.py`
(`test_refresh_right_tab_after_switch_immediately_refreshes_live_stats`), not
copied -- the migration rule `test_componentization_inventory`'s header states
is that a call site is migrated by the step that converts its subject. It built
`object.__new__(MegabonkApp)`, hung two lambdas off it and called
`MegabonkApp._refresh_right_tab_after_switch(app)` with that as `self`; it
calls a real constructor now, which is what takes `MAX_OBJECT_NEW_APP_DOUBLES`
from 11 to 9.

The rest are new, and each locks in behaviour this step *changed the shape of*
rather than re-testing the router's arithmetic:

* Every port is a supplier, and the router's slots fire during `build_layout`
  while three of them still answer `None` (`TabRouter`'s header explains why
  the `currentChanged` connects cannot move). `test_*_before_the_views_exist`
  is that moment. It matters more than it looks: **Qt swallows exceptions
  raised inside a slot**, so the only symptom of getting this wrong is a
  traceback on stderr, which no unit test and no `pytest` run can see. The
  suite cannot prove the app starts clean -- `tools/step23_startup_smoke.py`
  does that -- but it can prove the router tolerates the state the startup
  smoke would find it in.
* The four `hasattr(self, "ensure_..._chooser_for_empty_selection")` guards are
  gone, replaced by `is None` checks on the views. `test_*_before_the_views_
  exist` and `test_right_tab_switch_refreshes_recordings_twice` are the pair
  that says the replacement guards the real question: absent view, no call;
  present view, both calls.
* `_refresh_recording_tabs` runs **twice** per switch, once synchronously and
  once from `after_idle`. That is preserved from the two copies it replaced,
  and `test_right_tab_switch_refreshes_recordings_twice` counts it, so a later
  "simplification" has to argue with a number rather than with a comment.

No real Qt widget is constructed anywhere in this file, for the reason step 25
recorded twice: a test that builds one after a `QApplication` exists crashes
the interpreter with 0xC0000409 and exit code 127, taking the report with it.
`FakeTabWidget` is the whole of the Qt surface the router touches.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app import config
from ui.layout import TabRouter, _is_tab_active


class FakeTabWidget:
    """The two methods `_is_tab_active` calls. Deliberately not a QTabWidget."""

    def __init__(self, active_tab: str) -> None:
        self.active_tab = active_tab

    def currentIndex(self) -> int:
        return 0

    def tabText(self, _index: int) -> str:
        return self.active_tab


class FakeRecordingsView:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def refresh_vods_list(self) -> None:
        self._calls.append("vods")

    def ensure_recordings_chooser_for_empty_selection(self) -> None:
        self._calls.append("vods_chooser")


class FakeCompareRunsView:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def refresh_compare_runs_list(self) -> None:
        self._calls.append("compare")

    def ensure_compare_runs_chooser_for_empty_selection(self) -> None:
        self._calls.append("compare_chooser")


def build_router(
    *,
    active_tab: str | None = None,
    left_tab: str | None = None,
    views: bool = True,
    templates_panel: bool = True,
):
    """A router and the call log its ten collaborators write to.

    `views=False` and `templates_panel=False` reproduce the state the router is
    in while `build_layout` is still running, which is the state its slots
    actually fire in.
    """
    calls: list[str] = []
    idle: list[object] = []
    tabview = None if active_tab is None else FakeTabWidget(active_tab)
    left_tabview = None if left_tab is None else FakeTabWidget(left_tab)
    router = TabRouter(
        left_tabview=lambda: left_tabview,
        tabview=lambda: tabview,
        templates_panel=lambda: (
            SimpleNamespace(refresh_scores_ui=lambda: calls.append("scores"))
            if templates_panel
            else None
        ),
        recordings_view=lambda: FakeRecordingsView(calls) if views else None,
        compare_runs_view=lambda: FakeCompareRunsView(calls) if views else None,
        overlay=SimpleNamespace(
            refresh_overlay_ui=lambda: calls.append("overlay")
        ),
        template_filters=SimpleNamespace(
            sync=lambda announce=False: calls.append(f"sync:{announce}")
        ),
        update_status=lambda: calls.append("status"),
        refresh_live_player_stats=lambda: calls.append("live"),
        schedule_idle=idle.append,
    )
    return router, calls, idle


class TabActiveTests(unittest.TestCase):
    def test_predicate_matches_the_showing_tab(self) -> None:
        self.assertTrue(_is_tab_active(FakeTabWidget("Live Stats"), "Live Stats"))
        self.assertFalse(_is_tab_active(FakeTabWidget("Logs"), "Live Stats"))

    def test_predicate_answers_no_when_there_is_no_tab_bar(self) -> None:
        """The guard the four mixin predicates did not have.

        They read `self.tabview.tabText(...)` unguarded. Reached before
        `build_layout` builds the bar -- which is exactly when the router's
        slots first fire -- that is an `AttributeError` inside a Qt slot, and
        Qt swallows those.
        """
        self.assertFalse(_is_tab_active(None, "Live Stats"))


class RightTabRouterTests(unittest.TestCase):
    def test_right_tab_switch_refreshes_recordings_twice(self) -> None:
        """Once synchronously, once from `after_idle`. Counted, not assumed.

        `on_right_tab_changed` and `_refresh_right_tab_after_switch` each ran
        the same eight lines before step 26 folded them into
        `_refresh_recording_tabs`. Folding the *text* must not fold the
        *calls*: the two passes straddle Qt's redraw.
        """
        router, calls, idle = build_router(active_tab="Recordings")

        router.on_right_tab_changed()
        self.assertEqual(calls, ["vods", "vods_chooser"])
        self.assertEqual(len(idle), 1)

        idle[0]()
        self.assertEqual(
            calls, ["vods", "vods_chooser", "vods", "vods_chooser"]
        )

    def test_compare_runs_switch_refreshes_the_list_and_the_chooser(self) -> None:
        router, calls, idle = build_router(active_tab="Compare Runs")

        router.on_right_tab_changed()
        idle[0]()

        self.assertEqual(
            calls, ["compare", "compare_chooser", "compare", "compare_chooser"]
        )

    def test_refresh_right_tab_after_switch_immediately_refreshes_live_stats(self) -> None:
        """Moved from `test_gui_run_control.py`; same assertion, real object."""
        router, calls, _idle = build_router(active_tab="Live Stats")

        router._refresh_right_tab_after_switch()

        self.assertEqual(calls, ["live"])

    def test_refresh_right_tab_after_switch_repaints_the_overlay_tab(self) -> None:
        router, calls, _idle = build_router(active_tab="OBS Overlay")

        router._refresh_right_tab_after_switch()

        self.assertEqual(calls, ["overlay"])

    def test_right_tab_switch_touches_nothing_before_the_views_exist(self) -> None:
        """The state the router's slots first fire in.

        `_build_right_panel` connects `currentChanged` before `addTab` runs, so
        the first switch this object sees happens while `_recordings_view` and
        `_compare_runs_view` are still `None`. The four `hasattr` guards this
        replaced were permanently true and would not have caught it; what kept
        the app up was that the predicates compared tab *text* and happened not
        to match during the initial `addTab` calls.
        """
        router, calls, idle = build_router(active_tab="Recordings", views=False)

        router.on_right_tab_changed()
        idle[0]()

        self.assertEqual(calls, [])

    def test_refresh_vods_list_if_visible_repaints_only_the_showing_tab(self) -> None:
        """`RecordingsListView`'s single operation, called by `app/`.

        `vod_capture` and `player_stats_refresh` reach this through
        `recordings_list_view(owner)`, whose fallback to the app object step 26
        closed by injecting this object.
        """
        router, calls, _idle = build_router(active_tab="Recordings")
        router._refresh_vods_list_if_visible()
        self.assertEqual(calls, ["vods"])

        router, calls, _idle = build_router(active_tab="Logs")
        router._refresh_vods_list_if_visible()
        self.assertEqual(calls, [])


class LeftTabRouterTests(unittest.TestCase):
    def test_left_tab_switch_persists_the_evaluation_mode(self) -> None:
        router, calls, _idle = build_router(left_tab="Scores")
        user_config: dict[str, object] = {}

        with patch.object(config, "EVALUATION_MODE", "templates"), \
             patch.object(config, "user_config", user_config), \
             patch.object(config, "save_config") as save_config:
            router.on_left_tab_changed()

            self.assertEqual(config.EVALUATION_MODE, "scores")
            self.assertEqual(user_config["EVALUATION_MODE"], "scores")
            save_config.assert_called_once_with(user_config)

        self.assertEqual(calls, ["scores", "sync:True", "status"])

    def test_left_tab_switch_to_templates_writes_templates(self) -> None:
        router, _calls, _idle = build_router(left_tab="Templates")

        with patch.object(config, "EVALUATION_MODE", "scores"), \
             patch.object(config, "user_config", {}), \
             patch.object(config, "save_config"):
            router.on_left_tab_changed()

            self.assertEqual(config.EVALUATION_MODE, "templates")

    def test_left_tab_switch_returns_before_the_bar_exists(self) -> None:
        """`_build_left_tabs` connects the signal before it builds the panel.

        The mixin's `if self.left_tabview is None: return` is preserved
        verbatim. Without it, `setCurrentIndex` at the end of `_build_left_tabs`
        would write `config.json` from inside a slot with no bar to read.
        """
        router, calls, _idle = build_router(left_tab=None)

        with patch.object(config, "save_config") as save_config:
            router.on_left_tab_changed()

        save_config.assert_not_called()
        self.assertEqual(calls, [])

    def test_left_tab_switch_skips_a_panel_that_does_not_exist_yet(self) -> None:
        """`MegabonkApp.refresh_scores_ui`'s `is None` guard, which came here.

        The app's delegator existed only because the router called it on the
        application; the guard inside it was about *this* object's firing
        order, so it moved with the caller rather than staying behind.
        """
        router, calls, _idle = build_router(left_tab="Scores", templates_panel=False)

        with patch.object(config, "user_config", {}), \
             patch.object(config, "save_config"):
            router.on_left_tab_changed()

        self.assertEqual(calls, ["sync:True", "status"])


if __name__ == "__main__":
    unittest.main()
